"""Backend-owned comparisons with explicit workload and execution-scope guards."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import json
from typing import Callable

from app.api.metrics_schemas import (JobProjection, LifecycleCounts, LiveMetrics, ModelEvaluation, ModelMetrics,
    PolicyComparison, ReplayJobMetrics, ReplayMetrics, StrategyMetrics)
from app.api.replay_schemas import ReplaySession, StrategyRun, replay_provenance
from app.api.schemas import Decision, Job
from app.database import Database
from app.engine.accounting import reconcile, replay_totals
from app.engine.forecast_bridge import EngineUnavailable
from app.engine.money import total_usd


def percent_difference(difference, baseline):
    if baseline == 0:
        return None
    return float((Decimal(str(difference)) / Decimal(str(baseline)) * 100).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_EVEN))


def summarize(session: ReplaySession, run: StrategyRun) -> StrategyMetrics:
    reconcile(session, run)
    details = []
    for job in sorted(run.jobs, key=lambda row: row.id):
        charges = [row for row in run.charges if row.job_id == job.id]
        start = next((row for row in run.decisions if row.job_id == job.id
                      and row.action in {"RUN", "ROUTE", "FALLBACK"}), None)
        completion = next((row.slot for row in run.outcomes if row.job_id == job.id and row.status == "COMPLETED"), None)
        components = [total_usd(getattr(row, field) for row in charges)
                      for field in ["compute_usd", "startup_usd", "transfer_usd", "carbon_usd"]]
        details.append(ReplayJobMetrics(job_id=job.id, status=job.status, resource_units=job.resource_units,
            resource_unit_hours=len(charges) * job.resource_units,
            started_at_slot=start.planned_start_slot if start else None, completed_at_slot=completion,
            deadline_slot=job.deadline_slot, completion_slack_slots=job.deadline_slot - completion if completion is not None else None,
            missed_deadline=job.id in run.missed_deadline_ids, compute_spend_usd=components[0],
            startup_cost_usd=components[1], transfer_cost_usd=components[2], carbon_cost_usd=components[3],
            total_spend_usd=total_usd(components), projected_cost_at_start_usd=start.projected_cost_usd if start else None))
    return StrategyMetrics(strategy=run.strategy, status=run.status, error=run.error,
        model_versions=sorted(set(run.model_versions_used) | {row.model_version for row in run.forecasts}), totals=replay_totals(run),
        completed_job_ids=sorted(job.id for job in run.jobs if job.status == "COMPLETED"),
        failed_job_ids=sorted(job.id for job in run.jobs if job.status == "FAILED"),
        infeasible_job_ids=sorted(job.id for job in run.jobs if job.status == "INFEASIBLE"),
        unfinished_job_ids=sorted(job.id for job in run.jobs if job.status in {"PENDING", "RUNNING"}),
        missed_deadline_job_ids=sorted(set(run.missed_deadline_ids)), jobs=details)


def compare(candidate, baseline, candidate_run, baseline_run, completed):
    def completed_work(run):
        return {job.id: job.model_dump(exclude={"status"}) for job in run.jobs if job.status == "COMPLETED"}
    same_work = completed_work(candidate_run) == completed_work(baseline_run)
    same_outcomes = ({job.id: job.status for job in candidate_run.jobs} == {job.id: job.status for job in baseline_run.jobs}
                     and {job.id: job.model_dump(exclude={"status"}) for job in candidate_run.jobs}
                     == {job.id: job.model_dump(exclude={"status"}) for job in baseline_run.jobs}
                     and candidate.missed_deadline_job_ids == baseline.missed_deadline_job_ids)
    all_completed = bool(candidate_run.jobs) and all(job.status == "COMPLETED" for job in candidate_run.jobs + baseline_run.jobs)
    available = candidate.status == baseline.status == "ACTIVE"
    if "UNAVAILABLE" in {candidate.status, baseline.status}:
        reason, message = "STRATEGY_UNAVAILABLE", "A required provider is unavailable; no savings comparison is valid."
    elif "ERROR" in {candidate.status, baseline.status}:
        reason, message = "STRATEGY_ERROR", "A strategy failed; retained partial costs are not a valid savings result."
    elif not completed:
        reason, message = "IN_PROGRESS", "Replay is still in progress; accrued cost differences are provisional."
    elif not same_work:
        reason, message = "DIFFERENT_WORKLOADS", "Policies completed different job IDs or requirements; this is only a cost difference."
    elif not same_outcomes:
        reason, message = "DIFFERENT_OUTCOMES", "Lifecycle or deadline outcomes differ; this is only a cost difference."
    elif candidate.totals.unfinished_jobs or baseline.totals.unfinished_jobs:
        reason, message = "UNFINISHED_WORK", "Pending/running work remains; differing partial progress cannot be reported as savings."
    elif not candidate.completed_job_ids:
        reason, message = "NO_COMPLETED_WORK", "Neither strategy completed work; lower spend is not reported as savings."
    else:
        reason, message = "COMPARABLE", "Completed workloads and lifecycle/deadline outcomes match; totals include failed work."
    delta = total_usd([baseline.totals.total_spend_usd, -candidate.totals.total_spend_usd]) if available else None
    comparable = reason == "COMPARABLE"
    return PolicyComparison(strategy=candidate.strategy, baseline=baseline.strategy, comparable=comparable,
        reason_code=reason, explanation=message, baseline_spend_usd=baseline.totals.total_spend_usd if available else None,
        strategy_spend_usd=candidate.totals.total_spend_usd if available else None, cost_difference_usd=delta,
        savings_usd=delta if comparable else None,
        savings_percent=percent_difference(delta, baseline.totals.total_spend_usd) if comparable else None,
        same_completed_jobs=same_work, same_outcomes=same_outcomes, all_jobs_completed=all_completed)


def replay_metrics(session: ReplaySession | None) -> ReplayMetrics:
    if session is None:
        return ReplayMetrics(status="NOT_INITIALIZED")
    summaries = [summarize(session, run) for run in session.runs]
    completed = session.current_slot == session.scenario.end_slot
    comparisons = [compare(summaries[index], summaries[base], session.runs[index], session.runs[base], completed)
                   for index in range(len(summaries)) for base in range(index)]
    return ReplayMetrics(status="COMPLETED" if completed else "IN_PROGRESS", scenario_id=session.scenario.id,
        origin_utc=session.scenario.origin_utc, as_of_slot=session.current_slot, end_slot=session.scenario.end_slot,
        start_slot=session.scenario.start_slot, provenance=replay_provenance(session),
        strategies=summaries, comparisons=comparisons)


def live_metrics(database: Database) -> LiveMetrics:
    with database.transaction() as connection:
        stored = connection.execute("SELECT payload FROM engine_state WHERE id = 1").fetchone()
        state = json.loads(stored["payload"]) if stored else {"currentSlot": 0, "executionMode": "PAPER"}
        jobs = [Job.model_validate_json(row["payload"]) for row in connection.execute("SELECT payload FROM jobs ORDER BY id")]
        latest = {}
        for row in connection.execute("SELECT payload FROM decisions ORDER BY id"):
            decision = Decision.model_validate_json(row["payload"])
            latest[decision.job_id] = decision
        completions = {}
        for row in connection.execute("SELECT job_id, payload FROM audit_events WHERE event_type = 'JOB_STATUS_CHANGED' ORDER BY id"):
            payload = json.loads(row["payload"])
            if payload.get("toStatus") == "COMPLETED":
                completions[row["job_id"]] = payload.get("observedAtSlot")
    projections, unpriced, missed, unknown = [], [], [], []
    for job in jobs:
        if job.status == "COMPLETED":
            completion = completions.get(job.id)
            if completion is None:
                unknown.append(job.id)
            elif completion > job.deadline_slot:
                missed.append(job.id)
        elif job.deadline_slot <= state["currentSlot"]:
            missed.append(job.id)
        if job.status not in {"PENDING", "RUNNING"}:
            continue
        decision = latest.get(job.id)
        if decision is None or decision.projected_cost_usd is None:
            unpriced.append(job.id)
        if decision is not None:
            projections.append(JobProjection(job_id=job.id, decided_at_slot=decision.decided_at_slot,
                execution_mode=decision.execution_mode, projected_cost_usd=decision.projected_cost_usd))
    subtotal = total_usd(row.projected_cost_usd for row in projections if row.projected_cost_usd is not None)
    counts = {status: sum(job.status == status for job in jobs) for status in ["PENDING", "RUNNING", "COMPLETED", "FAILED", "INFEASIBLE"]}
    lifecycle = LifecycleCounts(pending_jobs=counts["PENDING"], running_jobs=counts["RUNNING"],
        completed_jobs=counts["COMPLETED"], failed_jobs=counts["FAILED"], infeasible_jobs=counts["INFEASIBLE"],
        unfinished_jobs=counts["PENDING"] + counts["RUNNING"], missed_deadlines=len(missed))
    return LiveMetrics(as_of_slot=state["currentSlot"], active_execution_mode=state["executionMode"], job_counts=lifecycle,
        missed_deadline_job_ids=missed, unknown_completion_time_job_ids=unknown,
        known_projected_cost_usd=subtotal, projected_portfolio_cost_usd=None if unpriced else subtotal,
        unpriced_outstanding_job_ids=unpriced, projections=projections)


class ModelMetricsService:
    def __init__(self, provider: Callable[[], ModelEvaluation] | None = None, clock=None):
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def read(self) -> ModelMetrics:
        if self.provider is None:
            return ModelMetrics(status="UNAVAILABLE", reason="No evaluated model provider is configured")
        try:
            raw = self.provider()
            report = ModelEvaluation.model_validate(raw.model_dump() if isinstance(raw, ModelEvaluation) else raw)
            if report.evaluated_at_utc > self.clock():
                raise ValueError("Model evaluation is dated in the future")
        except Exception as exc:
            raise EngineUnavailable("MODEL_METRICS_INVALID", f"Model evaluation is unavailable or invalid: {exc}") from exc
        mae_delta = float(Decimal(str(report.persistence_mae)) - Decimal(str(report.mae)))
        rmse_delta = float(Decimal(str(report.persistence_rmse)) - Decimal(str(report.rmse)))
        return ModelMetrics(status="EVALUATED", evaluation=report, mae_improvement=mae_delta, rmse_improvement=rmse_delta,
            mae_improvement_percent=percent_difference(mae_delta, report.persistence_mae),
            rmse_improvement_percent=percent_difference(rmse_delta, report.persistence_rmse))
