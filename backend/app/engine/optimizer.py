"""Deterministic portfolio search, independent of forecasting, storage and execution."""
from dataclasses import dataclass
from math import prod

from app.api.schemas import Decision, Forecast, OptimizationInput, Reservation

Key = tuple[str, str, str | None]


def resource_key(row) -> Key:
    return row.region, row.resource_type, row.gpu_type


class OptimizationLimitError(RuntimeError):
    """No result is published when the exact-search safety limit is reached."""


@dataclass(frozen=True)
class RiskPolicy:
    # Scenario assumption until the ML owner supplies documented risk semantics.
    # Probabilities describe each occupied hour; recovery is one full restart.
    recovery_cost_multiplier: float = 1.0
    critical_slack_slots: int = 0
    max_search_nodes: int = 250_000

    def __post_init__(self):
        from math import isfinite
        if (not isfinite(self.recovery_cost_multiplier) or self.recovery_cost_multiplier < 0
                or self.critical_slack_slots < 0 or self.max_search_nodes < 1):
            raise ValueError("Invalid optimizer policy")


@dataclass(frozen=True)
class Candidate:
    region: str
    start: int
    end: int
    compute: float
    startup: float
    transfer: float
    recovery: float
    carbon: float
    availability: float | None
    interruption: float | None
    forecasts: tuple[Forecast, ...]

    @property
    def cost(self):
        return self.compute + self.startup + self.transfer + self.recovery + self.carbon

    @property
    def reliability_penalty(self):
        # Unknown is explicitly ranked conservatively; it is not a calibrated 1.
        if self.availability is None or self.interruption is None:
            return 1.0
        return 1 - self.availability * (1 - self.interruption)


@dataclass(frozen=True)
class DecisionEvidence:
    deadline_slack_slots: int | None
    forecasts: tuple[Forecast, ...]
    cost_breakdown: dict[str, float] | None
    availability_probability: float | None
    interruption_probability: float | None


@dataclass
class OptimizationPlan:
    decisions: list[Decision]
    evidence: dict[str, DecisionEvidence]
    search_nodes: int


class ConstrainedPortfolioOptimizer:
    def __init__(self, policy: RiskPolicy | None = None):
        self.policy = policy or RiskPolicy()

    def optimize(self, inputs: OptimizationInput) -> list[Decision]:
        return self.plan(inputs).decisions

    def plan(self, inputs: OptimizationInput) -> OptimizationPlan:
        market, forecasts = self._validate_and_index(inputs)
        jobs = sorted(inputs.pending_jobs, key=lambda job: (
            job.deadline_slot - max(inputs.current_slot, job.arrival_slot)
            - job.duration_slots - inputs.config.safety_buffer_slots,
            -job.priority, job.id,
        ))
        options = {job.id: self._candidates(job, inputs, market, forecasts) for job in jobs}
        choices = {job_id: rows for job_id, (rows, _) in options.items()}
        occupied = {}
        total = {}
        for reservation in inputs.reservations:
            self._occupy(occupied, total, reservation, 1)

        best_score = None
        best = None
        nodes = 0

        def search(index, selected, missing, risk, cost):
            nonlocal best_score, best, nodes
            nodes += 1
            if nodes > self.policy.max_search_nodes:
                raise OptimizationLimitError("Portfolio search limit reached; no plan committed")
            # Optimistic admission bound: no later job needs to be dropped.
            lower_missing = tuple(missing + [0] * (len(jobs) - index))
            if best_score is not None and lower_missing > best_score[0]:
                return
            if best_score is not None and lower_missing == best_score[0]:
                lower_risk = tuple(risk + [0] * (len(jobs) - index))
                lower_cost = cost + sum(min((row.cost for row in choices[job.id]), default=0)
                                        for job in jobs[index:])
                if lower_risk > best_score[1] or (lower_risk == best_score[1] and lower_cost > best_score[2]):
                    return
            if index == len(jobs):
                tie = tuple((row.start, row.region) if row else (10**30, "") for row in selected)
                score = (tuple(missing), tuple(risk), cost, tie)
                if best_score is None or score < best_score:
                    best_score, best = score, selected.copy()
                return
            job = jobs[index]
            urgent = self._latest_start(job, inputs) - inputs.current_slot <= self.policy.critical_slack_slots
            for candidate in choices[job.id]:
                reservation = self._reservation(job, candidate)
                if not self._fits(reservation, inputs, market, occupied, total):
                    continue
                self._occupy(occupied, total, reservation, 1)
                search(index + 1, selected + [candidate], missing + [0],
                       risk + [candidate.reliability_penalty if urgent else 0], cost + candidate.cost)
                self._occupy(occupied, total, reservation, -1)
            search(index + 1, selected + [None], missing + [1], risk + [0], cost)

        search(0, [], [], [], 0.0)
        decisions, evidence = [], {}
        for job, candidate in zip(jobs, best):
            decision, detail = self._decision(job, candidate, choices[job.id], options[job.id][1], inputs)
            decisions.append(decision)
            evidence[job.id] = detail
        return OptimizationPlan(decisions, evidence, nodes)

    @staticmethod
    def _latest_start(job, inputs):
        return job.deadline_slot - job.duration_slots - inputs.config.safety_buffer_slots

    def _validate_and_index(self, inputs):
        pending_ids = [job.id for job in inputs.pending_jobs]
        running_ids = [job.id for job in inputs.running_jobs]
        if len(set(pending_ids + running_ids)) != len(pending_ids + running_ids):
            raise ValueError("Jobs must have unique IDs across pending and running lists")
        if any(job.status != "PENDING" for job in inputs.pending_jobs):
            raise ValueError("pendingJobs must contain only PENDING jobs")
        if any(job.status != "RUNNING" for job in inputs.running_jobs):
            raise ValueError("runningJobs must contain only RUNNING jobs")
        reservations = {row.job_id: row for row in inputs.reservations}
        if len(reservations) != len(inputs.reservations) or set(pending_ids) & reservations.keys():
            raise ValueError("Duplicate reservations or a pending job already reserved")
        for job in inputs.running_jobs:
            row = reservations.get(job.id)
            if (row is None or not row.start_slot <= inputs.current_slot < row.end_slot
                    or row.region not in job.allowed_regions
                    or row.resource_type != job.resource_type or row.gpu_type != job.gpu_type
                    or row.resource_units != job.resource_units
                    or row.end_slot - row.start_slot != job.duration_slots):
                raise ValueError("Running jobs require matching active reservations")
        if inputs.config.portfolio_resource_limit is not None:
            types = {row.resource_type for row in inputs.pending_jobs + inputs.running_jobs + inputs.reservations}
            if len(types) > 1:
                raise ValueError("A scalar portfolio limit requires homogeneous CPU/GPU resources")
        market = {}
        observed_vintages = {}
        for row in inputs.market:
            if row.slot > inputs.current_slot or row.data_kind == "FORECAST":
                raise ValueError("Market input must contain only available observations")
            key = resource_key(row)
            vintage = (key, row.slot)
            if vintage in observed_vintages and observed_vintages[vintage] != row:
                raise ValueError("Conflicting observations at the same slot")
            observed_vintages[vintage] = row
            previous = market.get(key)
            if previous is None or previous.slot < row.slot:
                market[key] = row
        forecasts = {}
        forecast_vintages = {}
        for row in inputs.forecasts:
            if row.generated_at_slot > inputs.current_slot or row.target_slot - row.generated_at_slot > 6:
                raise ValueError("Forecast unavailable at decision time or beyond six-hour horizon")
            if (row.price_lower_bound is not None and row.price_upper_bound is not None
                    and row.price_lower_bound > row.price_upper_bound):
                raise ValueError("Invalid forecast uncertainty interval")
            key = (resource_key(row), row.target_slot)
            vintage = (key, row.generated_at_slot)
            if vintage in forecast_vintages and forecast_vintages[vintage] != row:
                raise ValueError("Conflicting forecast vintages")
            forecast_vintages[vintage] = row
            previous = forecasts.get(key)
            if previous is None or previous.generated_at_slot < row.generated_at_slot:
                forecasts[key] = row
        return market, forecasts

    def _candidates(self, job, inputs, market, forecasts):
        candidates = []
        matched_hardware = False
        enough_units = False
        priced_window = False
        carbon_missing = False
        last_known_slot = max([inputs.current_slot] + [slot for _, slot in forecasts])
        latest = min(self._latest_start(job, inputs), last_known_slot + 1 - job.duration_slots)
        for region in sorted(set(job.allowed_regions)):
            key = (region, job.resource_type, job.gpu_type)
            observed = market.get(key)
            if observed is None:
                continue
            matched_hardware = True
            if observed.available_units < job.resource_units:
                continue
            enough_units = True
            if inputs.config.carbon_price_usd_per_kg and observed.carbon_kg_per_unit_hour is None:
                carbon_missing = True
                continue
            for start in range(max(inputs.current_slot, job.arrival_slot), latest + 1):
                end = start + job.duration_slots
                rows = [forecasts.get((key, slot)) for slot in range(start, end)]
                if any(row is None and slot != inputs.current_slot
                       for slot, row in zip(range(start, end), rows)):
                    continue
                priced_window = True
                compute = sum(observed.price_usd_per_unit_hour if slot == inputs.current_slot
                              else row.predicted_price_usd_per_unit_hour
                              for slot, row in zip(range(start, end), rows)) * job.resource_units
                interruption = None if any(row is None or row.interruption_probability is None for row in rows) else (
                    1 - prod(1 - row.interruption_probability for row in rows))
                availability = 1.0 if start == inputs.current_slot else rows[0].availability_probability
                recovery = (interruption or 0) * compute * self.policy.recovery_cost_multiplier
                candidate = Candidate(
                    region, start, end, compute, inputs.config.startup_cost_usd,
                    inputs.config.transfer_cost_usd if region != job.allowed_regions[0] else 0,
                    recovery, (observed.carbon_kg_per_unit_hour or 0) * job.resource_units
                    * job.duration_slots * inputs.config.carbon_price_usd_per_kg,
                    availability, interruption, tuple(row for row in rows if row is not None),
                )
                if job.max_budget_usd is None or candidate.cost <= job.max_budget_usd:
                    candidates.append(candidate)
        urgent = self._latest_start(job, inputs) - inputs.current_slot <= self.policy.critical_slack_slots
        issue = ("NO_COMPATIBLE_MARKET_DATA" if not matched_hardware else
                 "CAPACITY_UNAVAILABLE" if not enough_units else
                 "CARBON_DATA_UNAVAILABLE" if carbon_missing and not priced_window else
                 "FORECAST_COVERAGE_MISSING" if not priced_window else "BUDGET_EXCEEDED")
        return sorted(candidates, key=lambda row: (
            row.reliability_penalty if urgent else 0, row.cost, row.start, row.region)), issue

    @staticmethod
    def _reservation(job, candidate):
        return Reservation(job_id=job.id, region=candidate.region, resource_type=job.resource_type,
                           gpu_type=job.gpu_type, resource_units=job.resource_units,
                           start_slot=candidate.start, end_slot=candidate.end)

    @staticmethod
    def _occupy(occupied, total, reservation, sign):
        for slot in range(reservation.start_slot, reservation.end_slot):
            key = (resource_key(reservation), slot)
            occupied[key] = occupied.get(key, 0) + sign * reservation.resource_units
            total[slot] = total.get(slot, 0) + sign * reservation.resource_units

    @staticmethod
    def _fits(reservation, inputs, market, occupied, total):
        for slot in range(reservation.start_slot, reservation.end_slot):
            used = occupied.get((resource_key(reservation), slot), 0)
            if used + reservation.resource_units > market[resource_key(reservation)].available_units:
                return False
            limit = inputs.config.portfolio_resource_limit
            if limit is not None and total.get(slot, 0) + reservation.resource_units > limit:
                return False
        return True

    def _decision(self, job, candidate, choices, issue, inputs):
        latest = self._latest_start(job, inputs)
        base = dict(job_id=job.id, decided_at_slot=inputs.current_slot, execution_mode=inputs.execution_mode)
        if candidate is None:
            slack = latest - max(inputs.current_slot, job.arrival_slot)
            if slack < 0:
                action, reason = "INFEASIBLE", "DEADLINE_INFEASIBLE"
            elif not choices:
                action = ("INFEASIBLE" if latest <= inputs.current_slot
                          and issue in {"BUDGET_EXCEEDED", "CAPACITY_UNAVAILABLE"} else "WAIT")
                reason = issue
            elif latest <= inputs.current_slot:
                action, reason = "INFEASIBLE", "CAPACITY_CONFLICT_AT_DEADLINE"
            else:
                action, reason = "WAIT", "PORTFOLIO_CAPACITY_CONFLICT"
            explanation = (f"No allocation: {reason}. Latest-start slack {slack} hour(s). "
                           "Missing market/forecast coverage or an unaffordable window is not proof of permanent infeasibility.")
            return Decision(**base, action=action, reason_code=reason, explanation=explanation), DecisionEvidence(
                slack, (), None, None, None)
        slack = job.deadline_slot - candidate.end - inputs.config.safety_buffer_slots
        urgent = latest - inputs.current_slot <= self.policy.critical_slack_slots
        cheapest = min(choices, key=lambda row: (row.cost, row.start, row.region))
        fallback = urgent and candidate.reliability_penalty < cheapest.reliability_penalty
        action = ("WAIT" if candidate.start > inputs.current_slot else
                  "FALLBACK" if fallback else "ROUTE" if candidate.region != job.allowed_regions[0] else "RUN")
        reason = ("LOWER_RISK_AT_DEADLINE" if fallback else "LOWEST_COST_FEASIBLE_PORTFOLIO")
        versions = sorted({row.model_version for row in candidate.forecasts})
        breakdown = dict(computeUsd=candidate.compute, startupUsd=candidate.startup,
                         transferUsd=candidate.transfer, expectedRecoveryUsd=candidate.recovery,
                         carbonUsd=candidate.carbon)
        explanation = (
            f"{action}: {candidate.region}, slots [{candidate.start}, {candidate.end}); "
            f"projected total ${candidate.cost:.4f}; deadline slack {slack} hour(s). "
            f"Forecast models: {', '.join(versions) or 'current observed price only'}. "
            f"Availability: {candidate.availability}; interruption: {candidate.interruption}. "
            "Future capacity carries forward the latest observed pool, less reservations. "
            "Unknown risk is unpriced; known hourly interruption risk uses a one-restart cost scenario."
        )
        return Decision(**base, action=action, region=candidate.region, planned_start_slot=candidate.start,
                        planned_end_slot=candidate.end, projected_cost_usd=candidate.cost,
                        reason_code=reason, explanation=explanation), DecisionEvidence(
                            slack, candidate.forecasts, breakdown, candidate.availability, candidate.interruption)
