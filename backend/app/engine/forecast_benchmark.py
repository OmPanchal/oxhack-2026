"""Small exact offline scheduling benchmark; independent of ML and execution.

Prices/forecasts are provided by the caller. Capacity is an explicit synthetic
constant assumption in this benchmark, never inferred from historical prices.
This module is not a production API optimizer or a cloud execution adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Workload:
    id: str
    arrival: int
    duration: int
    deadline: int
    allowed_pools: tuple[str, ...]
    units: int
    priority: int = 1

    def __post_init__(self):
        if self.duration < 1 or self.units < 1 or not self.allowed_pools:
            raise ValueError("Positive whole-instance workload requirements required")


@dataclass(frozen=True)
class Allocation:
    job_id: str
    pool: str
    start: int
    end: int
    units: int
    projected_cost: float


def _usage(reservations):
    usage = {}
    for plan in reservations:
        for slot in range(plan.start, plan.end):
            key = plan.pool, slot
            usage[key] = usage.get(key, 0) + plan.units
    return usage


def exact_plan(pending, running, quotes, capacity, current_slot):
    """Maximize feasible job count, then priority, then minimize quoted cost.

    Exhaustive search is intentional: the frozen benchmark releases two-job
    bursts per compatibility group. Shared reservations use half-open intervals.
    Only quoted execution windows are considered; no last-price extrapolation.
    """
    if any(job.arrival > current_slot for job in pending):
        raise ValueError("Do not expose future arrivals to planning")
    if len({j.id for j in pending}) != len(pending) or {j.id for j in pending} & {p.job_id for p in running}:
        raise ValueError("Pending/running jobs must be distinct")
    if any(not math.isfinite(p) or p < 0 for p in quotes.values()):
        raise ValueError("Nonnegative finite quotes required")
    ordered = sorted(pending, key=lambda j: (j.deadline-current_slot-j.duration, -j.priority, j.arrival, j.id))
    usage = _usage(running)
    domains = []
    for job in ordered:
        candidates = []
        for pool in sorted(job.allowed_pools):
            for start in range(current_slot, job.deadline-job.duration+1):
                slots = range(start, start+job.duration)
                if all((pool, t) in quotes and usage.get((pool, t), 0)+job.units <= capacity.get(pool, 0) for t in slots):
                    cost = sum(quotes[pool, t]*job.units for t in slots)
                    candidates.append(Allocation(job.id, pool, start, start+job.duration, job.units, cost))
        domains.append(sorted(candidates, key=lambda p: (p.projected_cost, p.start, p.pool)))
    best_key, best = None, []

    def search(index, plans, priority, cost):
        nonlocal best_key, best
        if best_key is not None and len(plans)+len(ordered)-index < -best_key[0]:
            return
        if index == len(ordered):
            signature = tuple((p.job_id, p.start, p.pool) for p in sorted(plans, key=lambda p: p.job_id))
            key = (-len(plans), -priority, cost, signature)
            if best_key is None or key < best_key:
                best_key, best = key, list(plans)
            return
        for candidate in domains[index]:
            slots = list(range(candidate.start, candidate.end))
            if any(usage.get((candidate.pool, t), 0)+candidate.units > capacity.get(candidate.pool, 0) for t in slots):
                continue
            for t in slots:
                usage[candidate.pool, t] = usage.get((candidate.pool, t), 0)+candidate.units
            search(index+1, plans+[candidate], priority+ordered[index].priority, cost+candidate.projected_cost)
            for t in slots:
                usage[candidate.pool, t] -= candidate.units
        search(index+1, plans, priority, cost)

    search(0, [], 0, 0.0)
    return best


def immediate_plan(pending, running, observed, capacity, current_slot, *, cheapest):
    """FIFO or cheapest-now admission, without future realized prices."""
    committed = list(running)
    result = []
    for job in sorted(pending, key=lambda j: (j.arrival, j.id)):
        if current_slot+job.duration > job.deadline:
            continue
        usage = _usage(committed)
        pools = [pool for pool in sorted(job.allowed_pools) if pool in observed and
                 all(usage.get((pool, t), 0)+job.units <= capacity.get(pool, 0)
                     for t in range(current_slot, current_slot+job.duration))]
        if not pools:
            continue
        pool = min(pools, key=lambda p: (observed[p], p)) if cheapest else pools[0]
        plan = Allocation(job.id, pool, current_slot, current_slot+job.duration, job.units,
                          observed[pool]*job.duration*job.units)
        result.append(plan)
        committed.append(plan)
    return result


def replay(workloads, pools, capacity, observed_at, forecasts_at, start, end, strategy):
    """Independent strategy state; reveal only arrivals and current observations.

    observed_at(t) returns only slot t's realized unit prices. forecasts_at(t)
    returns predictions generated at t, not actual future prices. Running plans
    never enter pending planning or migrate. Charge each running slot as observed.
    """
    valid = {"FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"}
    if strategy not in valid:
        raise ValueError("Unknown strategy")
    if len({j.id for j in workloads}) != len(workloads):
        raise ValueError("Unique job IDs required")
    if any(not set(j.allowed_pools) <= set(pools) for j in workloads):
        raise ValueError("Workload refers to an incompatible or unknown pool")
    jobs = {j.id: j for j in workloads}
    statuses = {j.id: "PENDING" for j in workloads}
    running, executions = [], []
    costs = {j.id: 0.0 for j in workloads}
    for current in range(start, end):
        for plan in running:
            if plan.end == current:
                statuses[plan.job_id] = "COMPLETED"
        running = [p for p in running if p.end > current]
        for job in workloads:
            if statuses[job.id] == "PENDING" and job.arrival <= current and current+job.duration > job.deadline:
                statuses[job.id] = "MISSED"
        pending = [j for j in workloads if j.arrival <= current and statuses[j.id] == "PENDING"]
        observed = observed_at(current)
        if strategy in {"FIFO", "CHEAPEST_NOW"}:
            plans = immediate_plan(pending, running, observed, capacity, current, cheapest=strategy == "CHEAPEST_NOW")
        else:
            if strategy == "OPTIMIZER_WITH_ML":
                quotes = dict(forecasts_at(current))
            else:
                quotes = {(pool, t): price for pool, price in observed.items() for t in range(current+1, current+7)}
            quotes.update({(pool, current): price for pool, price in observed.items()})
            plans = [p for p in exact_plan(pending, running, quotes, capacity, current) if p.start == current]
        for plan in plans:
            if statuses[plan.job_id] != "PENDING":
                raise AssertionError("Duplicate running job")
            statuses[plan.job_id] = "RUNNING"
            running.append(plan)
            executions.append(plan)
        usage = _usage(running)
        if any(units > capacity.get(pool, 0) for (pool, _), units in usage.items()):
            raise AssertionError("Shared capacity over-allocation")
        for plan in running:
            if plan.start <= current < plan.end:
                if plan.pool not in observed:
                    raise ValueError("Cannot bill a missing observed price")
                costs[plan.job_id] += observed[plan.pool]*plan.units
    for plan in running:
        if plan.end <= end:
            statuses[plan.job_id] = "COMPLETED"
    for job in workloads:
        if statuses[job.id] != "COMPLETED" and job.deadline <= end:
            statuses[job.id] = "MISSED"
    completed_ids = sorted(j for j, state in statuses.items() if state == "COMPLETED")
    missed_ids = sorted(j for j, state in statuses.items() if state == "MISSED" or
                        (state != "COMPLETED" and jobs[j].deadline <= end))
    unfinished_ids = sorted(set(statuses)-set(completed_ids)-set(missed_ids))
    return dict(strategy=strategy, totalSpendUsd=sum(costs.values()), completedJobs=len(completed_ids),
        missedDeadlines=len(missed_ids), failedJobs=0, unfinishedJobs=len(unfinished_ids),
        recoveryCostUsd=0, completedJobIds=completed_ids, missedJobIds=missed_ids,
        unfinishedJobIds=unfinished_ids, jobs=[dict(jobId=j, status=statuses[j], costUsd=costs[j]) for j in sorted(jobs)],
        executions=[dict(jobId=p.job_id, pool=p.pool, startSlot=p.start, endSlot=p.end,
                         projectedCostUsd=p.projected_cost) for p in executions])
