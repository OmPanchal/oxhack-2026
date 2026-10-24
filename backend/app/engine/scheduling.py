"""Commit scheduling against fresh SQLite state. No cloud or Docker execution."""
import sqlite3

from app.api.schemas import Decision, ExecutionMode, Forecast, Job, MarketSnapshot, OptimizationInput, OptimizerConfig, Reservation
from app.api.runtime_schemas import DecisionDetail
from app.audit.events import append_event
from app.database import Database
from app.engine.optimizer import ConstrainedPortfolioOptimizer, DecisionEvidence, OptimizationPlan
from app.jobs.store import write_job
from app.execution.control import DispatchControl
from app.execution.docker import TASK


class SchedulingService:
    def __init__(self, database: Database, optimizer: ConstrainedPortfolioOptimizer | None = None):
        self.database = database
        self.optimizer = optimizer or ConstrainedPortfolioOptimizer()

    def run(self, *, current_slot: int, market: list[MarketSnapshot], forecasts: list[Forecast],
            config: OptimizerConfig | None = None, execution_mode: ExecutionMode = "PAPER") -> OptimizationPlan:
        if execution_mode not in {"PAPER", "SIMULATED"}:
            raise ValueError("LOCAL dispatch requires the execution adapter; use PAPER to inspect a plan")
        with self.database.transaction() as connection:
            return self.run_in_transaction(connection, current_slot=current_slot, market=market,
                                           forecasts=forecasts, config=config, execution_mode=execution_mode)

    def run_in_transaction(self, connection: sqlite3.Connection, *, current_slot: int,
                           market: list[MarketSnapshot], forecasts: list[Forecast],
                           config: OptimizerConfig | None = None, execution_mode: ExecutionMode = "PAPER",
                           forecast_mode: str | None = None) -> OptimizationPlan:
        if execution_mode not in {"PAPER", "SIMULATED", "LOCAL"}:
            raise ValueError("LOCAL dispatch requires the execution adapter")
        jobs = [Job.model_validate_json(row["payload"]) for row in
                connection.execute("SELECT payload FROM jobs ORDER BY id")]
        reservations = [Reservation.model_validate_json(row["payload"]) for row in
                        connection.execute("SELECT payload FROM reservations ORDER BY job_id")]
        pending = [job for job in jobs if job.status == "PENDING"]
        unsupported = []
        if execution_mode == "LOCAL":
            supported = []
            for job in pending:
                if (job.docker_task_id == TASK.id and job.resource_type == "CPU"
                        and job.resource_units == 1 and job.gpu_type is None and "local" in job.allowed_regions):
                    supported.append(job)
                else:
                    unsupported.append(job)
            pending = supported
            # The local adapter exposes a single execution slot, irrespective of
            # a configured market fixture claiming a larger machine.
            market = [row.model_copy(update={"available_units": min(1, row.available_units)})
                      if row.available_units is not None else row
                      for row in market if row.region == "local" and row.resource_type == "CPU" and row.gpu_type is None]
            forecasts = [row for row in forecasts
                         if row.region == "local" and row.resource_type == "CPU" and row.gpu_type is None]
        inputs = OptimizationInput(
            current_slot=current_slot, pending_jobs=pending,
            running_jobs=[job for job in jobs if job.status == "RUNNING"], market=market,
            forecasts=forecasts, reservations=reservations, config=config or OptimizerConfig(),
            execution_mode=execution_mode,
        )
        plan = self.optimizer.plan(inputs)
        for job in unsupported:
            plan.decisions.append(Decision(job_id=job.id, decided_at_slot=current_slot, action="WAIT",
                reason_code="LOCAL_TASK_UNSUPPORTED", execution_mode="LOCAL",
                explanation="Automatic local execution requires an allowlisted one-CPU task and the explicit local region."))
            plan.evidence[job.id] = DecisionEvidence(None, (), None, None, None)
        dispatch_paused = DispatchControl.read(connection).paused
        by_id = {job.id: job for job in jobs if job.status == "PENDING"}
        kinds = {row.data_kind for row in market}
        data_kind = "MIXED" if len(kinds) > 1 else next(iter(kinds), None)
        for decision in plan.decisions:
            cursor = connection.execute("INSERT INTO decisions (job_id, payload) VALUES (?, ?)",
                                        (decision.job_id, decision.model_dump_json(by_alias=True)))
            evidence = plan.evidence[decision.job_id]
            detail = DecisionDetail(
                decision_id=cursor.lastrowid, job_id=decision.job_id, decided_at_slot=current_slot,
                forecast_mode=forecast_mode, execution_mode=execution_mode,
                deadline_slack_slots=evidence.deadline_slack_slots, forecasts_used=list(evidence.forecasts),
                cost_breakdown=evidence.cost_breakdown, availability_probability=evidence.availability_probability,
                interruption_probability=evidence.interruption_probability, data_kind=data_kind,
                market_sources=sorted({row.source for row in market}),
                pricing_assumption=evidence.pricing_assumption,
                dispatch_blocked=dispatch_paused,
                dispatch_block_reason="DISPATCH_PAUSED" if dispatch_paused else None,
            )
            connection.execute("INSERT INTO decision_details (decision_id, payload) VALUES (?, ?)",
                               (cursor.lastrowid, detail.model_dump_json(by_alias=True)))
            append_event(connection, "DECISION_RECORDED", decision.job_id,
                         decision.model_dump(mode="json", by_alias=True), execution_mode)
            if execution_mode == "PAPER" or dispatch_paused:
                continue
            if execution_mode == "LOCAL" and decision.action != "INFEASIBLE":
                continue
            job = by_id[decision.job_id]
            if decision.action in {"RUN", "ROUTE", "FALLBACK"}:
                reservation = Reservation(
                    job_id=job.id, region=decision.region, resource_type=job.resource_type,
                    gpu_type=job.gpu_type, resource_units=job.resource_units,
                    start_slot=decision.planned_start_slot, end_slot=decision.planned_end_slot,
                )
                connection.execute("INSERT INTO reservations (job_id, payload) VALUES (?, ?)",
                                   (job.id, reservation.model_dump_json(by_alias=True)))
                job.status = "RUNNING"
                write_job(connection, job)
                append_event(connection, "JOB_STARTED", job.id,
                             reservation.model_dump(mode="json", by_alias=True), execution_mode)
            elif decision.action == "INFEASIBLE":
                job.status = "INFEASIBLE"
                write_job(connection, job)
                append_event(connection, "JOB_STATUS_CHANGED", job.id,
                             {"fromStatus": "PENDING", "toStatus": "INFEASIBLE",
                              "reason": decision.reason_code}, execution_mode)
        return plan
