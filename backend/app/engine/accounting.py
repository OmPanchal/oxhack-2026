"""Decimal reconciliation of simulated charges against their realized world."""
from decimal import Decimal

from app.api.replay_schemas import ReplayCounters, ReplaySession, StrategyRun
from app.engine.money import decimal_usd, total_usd


class AccountingError(ValueError):
    pass


def replay_totals(run: StrategyRun) -> ReplayCounters:
    components = [total_usd(getattr(row, field) for row in run.charges)
                  for field in ["compute_usd", "startup_usd", "transfer_usd", "carbon_usd"]]
    counts = {status: sum(job.status == status for job in run.jobs)
              for status in ["COMPLETED", "FAILED", "INFEASIBLE", "PENDING", "RUNNING"]}
    return ReplayCounters(compute_spend_usd=components[0], startup_cost_usd=components[1],
        transfer_cost_usd=components[2], carbon_cost_usd=components[3], total_spend_usd=total_usd(components),
        completed_jobs=counts["COMPLETED"], failed_jobs=counts["FAILED"], infeasible_jobs=counts["INFEASIBLE"],
        pending_jobs=counts["PENDING"], running_jobs=counts["RUNNING"],
        unfinished_jobs=counts["PENDING"] + counts["RUNNING"], missed_deadlines=len(set(run.missed_deadline_ids)))


def reconcile(session: ReplaySession, run: StrategyRun):
    jobs = {job.id: job for job in run.jobs}
    if len(jobs) != len(run.jobs):
        raise AccountingError("Duplicate replay job IDs")
    starts = {}
    for decision in run.decisions:
        if decision.action in {"RUN", "ROUTE", "FALLBACK"}:
            if decision.job_id in starts:
                raise AccountingError("Replay job started more than once")
            starts[decision.job_id] = decision
    endings = {outcome.job_id: outcome for outcome in run.outcomes}
    if len(endings) != len(run.outcomes) or not set(starts).issubset(jobs):
        raise AccountingError("Duplicate outcomes or starts for unknown jobs")
    history = {(row.slot, row.region, row.resource_type, row.gpu_type): row for row in session.history}
    seen = set()
    charged_models = {}
    for charge in run.charges:
        key = charge.job_id, charge.slot
        job, start = jobs.get(charge.job_id), starts.get(charge.job_id)
        if key in seen or job is None or start is None or not 0 <= charge.slot < session.current_slot:
            raise AccountingError("Duplicate or unowned replay charge")
        seen.add(key)
        if (start.planned_start_slot is None or start.planned_end_slot is None
                or not start.planned_start_slot <= charge.slot < start.planned_end_slot):
            raise AccountingError("Charge outside execution window")
        gpu_type = charge.gpu_type if charge.gpu_type is not None else job.gpu_type
        if job.resource_type == 'GPU':
            if gpu_type is None:
                raise AccountingError('Replay charge lacks its selected GPU model; reset replay to record allocations')
            allowed = job.allowed_gpu_types or ([job.gpu_type] if job.gpu_type else [])
            if allowed and gpu_type not in allowed:
                raise AccountingError('Replay charge uses incompatible GPU hardware')
        elif gpu_type is not None:
            raise AccountingError('CPU replay charge contains GPU hardware')
        if job.id in charged_models and charged_models[job.id] != gpu_type:
            raise AccountingError('Non-preemptive replay job changed GPU model')
        charged_models[job.id] = gpu_type
        row = history.get((charge.slot, start.region, job.resource_type, gpu_type))
        if row is None:
            raise AccountingError("Charge lacks a realized market observation")
        if session.config.carbon_price_usd_per_kg and row.carbon_kg_per_unit_hour is None:
            raise AccountingError("Carbon charge lacks observed carbon intensity")
        expected = [Decimal(str(row.price_usd_per_unit_hour)) * job.resource_units,
                    session.config.startup_cost_usd if charge.slot == start.planned_start_slot else 0,
                    session.config.transfer_cost_usd if charge.slot == start.planned_start_slot
                    and start.region != job.allowed_regions[0] else 0,
                    Decimal(str(row.carbon_kg_per_unit_hour or 0)) * job.resource_units
                    * Decimal(str(session.config.carbon_price_usd_per_kg))]
        actual = [charge.compute_usd, charge.startup_usd, charge.transfer_usd, charge.carbon_usd]
        if any(value < 0 for value in actual) or any(decimal_usd(a) != decimal_usd(b) for a, b in zip(actual, expected)):
            raise AccountingError("Replay charge does not match realized prices/overheads")
    for job_id, job in jobs.items():
        start = starts.get(job_id)
        if start is None:
            if job.status in {"RUNNING", "COMPLETED", "FAILED"}:
                raise AccountingError("Execution state lacks a recorded start")
            continue
        end = endings.get(job_id)
        stop = min(session.current_slot, start.planned_end_slot,
                   end.slot if end is not None else start.planned_end_slot)
        expected_slots = set(range(start.planned_start_slot, stop))
        actual_slots = {slot for owner, slot in seen if owner == job_id}
        if actual_slots != expected_slots:
            raise AccountingError("Missing or extra charged execution hours")
        if job.status in {"COMPLETED", "FAILED"} and (end is None or end.status != job.status):
            raise AccountingError("Terminal state lacks its execution outcome")
    for run_job in run.jobs:
        spent = total_usd(value for charge in run.charges if charge.job_id == run_job.id
                          for value in [charge.compute_usd, charge.startup_usd, charge.transfer_usd, charge.carbon_usd])
        if run_job.max_budget_usd is not None and decimal_usd(spent) > decimal_usd(run_job.max_budget_usd):
            raise AccountingError("Realized replay spend exceeded the job budget")
    expected_missed = {job.id for job in run.jobs if (
        (job.status != "COMPLETED" and job.deadline_slot <= session.current_slot)
        or (job.status == "COMPLETED" and endings[job.id].slot > job.deadline_slot))}
    if set(run.missed_deadline_ids) != expected_missed:
        raise AccountingError("Missed deadline counts do not match job outcomes")
