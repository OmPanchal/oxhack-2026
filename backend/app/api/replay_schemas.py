"""Typed replay scenarios and additive API responses; all execution is simulated."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.api.schemas import (Contract, Decision, Forecast, Job, JobCreate, MarketSnapshot,
                             OptimizerConfig, ReplayState, Reservation, ResourceType, ShockRequest, Strategy)

STRATEGIES: list[Strategy] = ["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"]


class ReplayScenario(Contract):
    id: str
    description: str
    origin_utc: datetime
    end_slot: int = Field(gt=0, le=8760)
    jobs: list[JobCreate]
    market: list[MarketSnapshot]
    interruption_probability: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def valid_scenario(self):
        if self.origin_utc.utcoffset() is None or self.origin_utc.utcoffset().total_seconds() != 0:
            raise ValueError("Replay origin must be aware UTC")
        if len({job.id for job in self.jobs}) != len(self.jobs):
            raise ValueError("Scenario jobs must have unique IDs")
        if any(job.arrival_slot >= self.end_slot for job in self.jobs):
            raise ValueError("Every scenario job must arrive before replay ends")
        keys = set()
        series = set()
        for row in self.market:
            key = row.region, row.resource_type, row.gpu_type
            if row.available_units is None or row.data_kind == "FORECAST" or row.slot >= self.end_slot or (key, row.slot) in keys:
                raise ValueError("Scenario market requires unique realized rows inside the horizon")
            keys.add((key, row.slot))
            series.add(key)
        if not series or len(keys) != len(series) * self.end_slot:
            raise ValueError("Every resource series needs a realized row for every replay hour")
        return self


class ReplayShockRequest(ShockRequest):
    duration_slots: int = Field(default=1, ge=1, le=8760)
    resource_type: ResourceType | None = None
    gpu_type: str | None = None
    job_id: str | None = None
    job: JobCreate | None = None

    @model_validator(mode="after")
    def meaningful_payload(self):
        if self.kind == "JOB_ARRIVAL":
            if self.job is None or self.job.arrival_slot != self.slot:
                raise ValueError("JOB_ARRIVAL requires a job arriving at the shock slot")
        elif self.job is not None:
            raise ValueError("Only JOB_ARRIVAL accepts a job payload")
        if self.kind == "DEADLINE_PRESSURE" and self.job_id is None:
            raise ValueError("DEADLINE_PRESSURE requires jobId")
        if self.kind != "DEADLINE_PRESSURE" and self.job_id is not None:
            raise ValueError("Only DEADLINE_PRESSURE accepts jobId")
        if self.kind in {"CAPACITY_SHORTAGE", "DEADLINE_PRESSURE"} and self.magnitude != int(self.magnitude):
            raise ValueError("Capacity and deadline magnitudes must be whole units/hours")
        if self.kind == "INTERRUPTION" and self.magnitude > 1:
            raise ValueError("Interruption magnitude is a probability from zero to one")
        if self.kind in {"JOB_ARRIVAL", "DEADLINE_PRESSURE"}:
            if self.duration_slots != 1 or self.region is not None or self.resource_type is not None or self.gpu_type is not None:
                raise ValueError("Job/deadline events do not accept regional filters or durations")
        return self


class ReplayShock(ReplayShockRequest):
    event_id: str


class ReplayCharge(Contract):
    slot: int
    job_id: str
    compute_usd: float = 0
    startup_usd: float = 0
    transfer_usd: float = 0
    carbon_usd: float = 0


class ReplayOutcome(Contract):
    job_id: str
    slot: int
    status: Literal["COMPLETED", "FAILED", "INFEASIBLE"]
    reason: str


class StrategyRun(Contract):
    strategy: Strategy
    status: Literal["ACTIVE", "UNAVAILABLE", "ERROR"] = "ACTIVE"
    error: str | None = None
    jobs: list[Job] = Field(default_factory=list)
    reservations: list[Reservation] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    forecasts: list[Forecast] = Field(default_factory=list)
    charges: list[ReplayCharge] = Field(default_factory=list)
    outcomes: list[ReplayOutcome] = Field(default_factory=list)
    missed_deadline_ids: list[str] = Field(default_factory=list)


class ReplayCounters(Contract):
    compute_spend_usd: float
    startup_cost_usd: float
    transfer_cost_usd: float
    carbon_cost_usd: float
    recovery_cost_usd: float = 0
    total_spend_usd: float
    completed_jobs: int
    failed_jobs: int
    infeasible_jobs: int
    pending_jobs: int
    running_jobs: int
    unfinished_jobs: int
    missed_deadlines: int


class ReplayStrategyView(StrategyRun):
    metrics: ReplayCounters


class ReplayView(ReplayState):
    initialized: bool = False
    scenario_id: str | None = None
    description: str | None = None
    origin_utc: datetime | None = None
    end_slot: int | None = None
    execution_mode: Literal["SIMULATED"] = "SIMULATED"
    data_kind: Literal["SIMULATED"] = "SIMULATED"
    strategy_states: list[ReplayStrategyView] = Field(default_factory=list)
    events: list[ReplayShock] = Field(default_factory=list)
    observed_market: list[MarketSnapshot] = Field(default_factory=list)


class ReplaySession(Contract):
    # Concurrency identity only; excluded from ReplayView and all world draws.
    generation: str = Field(default_factory=lambda: uuid4().hex)
    scenario: ReplayScenario
    seed: int
    current_slot: int = 0
    runs: list[StrategyRun]
    config: OptimizerConfig = Field(default_factory=OptimizerConfig)
    events: list[ReplayShock] = Field(default_factory=list)
    history: list[MarketSnapshot] = Field(default_factory=list)
