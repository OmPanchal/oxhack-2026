"""Immediate-start baselines using only current observations and commitments."""
from app.api.schemas import Decision, OptimizationInput
from app.engine.optimizer import resource_key
from app.engine.money import within_budget


def immediate_policy(inputs: OptimizationInput, *, cheapest_now: bool) -> list[Decision]:
    market = {resource_key(row): row for row in inputs.market if row.slot == inputs.current_slot}
    occupied = {}
    for row in inputs.reservations:
        if row.start_slot <= inputs.current_slot < row.end_slot:
            key = resource_key(row)
            occupied[key] = occupied.get(key, 0) + row.resource_units
    total = sum(occupied.values())
    decisions = []
    for job in sorted(inputs.pending_jobs, key=lambda row: (row.arrival_slot, row.id)):
        base = dict(job_id=job.id, decided_at_slot=inputs.current_slot, execution_mode="SIMULATED")
        if inputs.current_slot + job.duration_slots + inputs.config.safety_buffer_slots > job.deadline_slot:
            decisions.append(Decision(**base, action="INFEASIBLE", reason_code="DEADLINE_INFEASIBLE",
                                      explanation="Cannot finish before the deadline and safety buffer."))
            continue
        feasible = []
        for key, row in market.items():
            if (row.region not in job.allowed_regions or row.resource_type != job.resource_type
                    or row.gpu_type != job.gpu_type or job.arrival_slot > inputs.current_slot):
                continue
            if row.available_units is None or occupied.get(key, 0) + job.resource_units > row.available_units:
                continue
            limit = inputs.config.portfolio_resource_limit
            if limit is not None and total + job.resource_units > limit:
                continue
            if inputs.config.carbon_price_usd_per_kg and row.carbon_kg_per_unit_hour is None:
                continue
            transfer = inputs.config.transfer_cost_usd if row.region != job.allowed_regions[0] else 0
            estimate = ((row.price_usd_per_unit_hour + (row.carbon_kg_per_unit_hour or 0)
                         * inputs.config.carbon_price_usd_per_kg) * job.resource_units * job.duration_slots
                        + inputs.config.startup_cost_usd + transfer)
            if not within_budget(estimate, job.max_budget_usd):
                continue
            feasible.append((row, estimate))
        feasible.sort(key=lambda pair: (pair[0].price_usd_per_unit_hour if cheapest_now else 0, pair[0].region))
        if not feasible:
            decisions.append(Decision(**base, action="WAIT", reason_code="NO_CURRENT_FEASIBLE_CAPACITY",
                                      explanation="No currently feasible region; no deliberate wait for future prices."))
            continue
        row, estimate = feasible[0]
        key = resource_key(row)
        occupied[key] = occupied.get(key, 0) + job.resource_units
        total += job.resource_units
        decisions.append(Decision(**base, action="RUN" if row.region == job.allowed_regions[0] else "ROUTE",
                                  region=row.region, planned_start_slot=inputs.current_slot,
                                  planned_end_slot=inputs.current_slot + job.duration_slots,
                                  projected_cost_usd=estimate,
                                  reason_code="CHEAPEST_NOW" if cheapest_now else "FIFO",
                                  explanation="Immediate execution; projected duration cost holds the current price constant."))
    return decisions
