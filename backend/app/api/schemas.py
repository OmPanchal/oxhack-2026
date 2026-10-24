"""Integration owner: Person 2. Coordinate changes with Persons 1 and 3."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

ResourceType = Literal["CPU", "GPU"]
JobStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "INFEASIBLE"]
ExecutionMode = Literal["SIMULATED", "PAPER", "LOCAL"]
Strategy = Literal["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"]

class Contract(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False)

class JobCreate(Contract):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arrival_slot: int = Field(ge=0)
    duration_slots: int = Field(gt=0)
    deadline_slot: int = Field(ge=0)
    resource_type: ResourceType
    resource_units: int = Field(gt=0)
    gpu_type: str | None = None
    allowed_regions: list[str] = Field(min_length=1)
    max_budget_usd: float | None = Field(default=None, ge=0)
    priority: int = 0
    docker_task_id: str | None = None

class Job(JobCreate):
    status: JobStatus = "PENDING"

class MarketSnapshot(Contract):
    slot: int = Field(ge=0)
    region: str
    resource_type: ResourceType
    gpu_type: str | None = None
    price_usd_per_unit_hour: float = Field(ge=0)
    available_units: int | None = Field(default=None, ge=0)
    carbon_kg_per_unit_hour: float | None = Field(default=None, ge=0)
    source: str
    data_kind: Literal["OBSERVED", "FORECAST", "SIMULATED"]

class Forecast(Contract):
    generated_at_slot: int = Field(ge=0)
    target_slot: int = Field(ge=0)
    region: str
    resource_type: ResourceType
    gpu_type: str | None = None
    predicted_price_usd_per_unit_hour: float = Field(ge=0)
    price_lower_bound: float | None = Field(default=None, ge=0)
    price_upper_bound: float | None = Field(default=None, ge=0)
    availability_probability: float | None = Field(default=None, ge=0, le=1)
    interruption_probability: float | None = Field(default=None, ge=0, le=1)
    model_version: str

    @model_validator(mode="after")
    def future_target(self):
        if self.target_slot <= self.generated_at_slot:
            raise ValueError("Forecast targets must follow generation time")
        return self

class Decision(Contract):
    job_id: str
    decided_at_slot: int = Field(ge=0)
    action: Literal["WAIT", "RUN", "ROUTE", "FALLBACK", "INFEASIBLE"]
    region: str | None = None
    planned_start_slot: int | None = None
    planned_end_slot: int | None = None
    projected_cost_usd: float | None = Field(default=None, ge=0)
    reason_code: str
    explanation: str
    execution_mode: ExecutionMode

class Reservation(Contract):
    job_id: str
    region: str
    resource_type: ResourceType
    gpu_type: str | None = None
    resource_units: int = Field(gt=0)
    start_slot: int = Field(ge=0)
    end_slot: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_window(self):
        if self.end_slot <= self.start_slot:
            raise ValueError("Reservations use nonempty half-open intervals")
        return self

class OptimizerConfig(Contract):
    startup_cost_usd: float = Field(default=0, ge=0)
    transfer_cost_usd: float = Field(default=0, ge=0)
    safety_buffer_slots: int = Field(default=0, ge=0)
    carbon_price_usd_per_kg: float = Field(default=0, ge=0)
    portfolio_resource_limit: int | None = Field(default=None, gt=0)

class OptimizeRequest(Contract):
    current_slot: int = Field(ge=0)
    forecast_mode: Literal["NAIVE", "ML"] = "NAIVE"
    execution_mode: ExecutionMode = "PAPER"

class OptimizationInput(Contract):
    current_slot: int = Field(ge=0)
    pending_jobs: list[Job]
    running_jobs: list[Job]
    forecasts: list[Forecast]
    market: list[MarketSnapshot]
    reservations: list[Reservation]
    config: OptimizerConfig = Field(default_factory=OptimizerConfig)
    execution_mode: ExecutionMode = "PAPER"

class ForecastRequest(Contract):
    current_slot: int = Field(ge=0)
    horizon_slots: int = Field(default=6, ge=1, le=6)
    history: list[MarketSnapshot]

    @model_validator(mode="after")
    def no_future_observations(self):
        if any(row.slot > self.current_slot or row.data_kind == "FORECAST" for row in self.history):
            raise ValueError("History must contain only observations available at currentSlot")
        return self

class ReplayResetRequest(Contract):
    seed: int = 42
    scenario_id: str = "demo"

class ReplayStepRequest(Contract):
    slots: int = Field(default=1, ge=1, le=24)

class ShockRequest(Contract):
    kind: Literal["PRICE_SPIKE", "CAPACITY_SHORTAGE", "INTERRUPTION", "DEADLINE_PRESSURE", "JOB_ARRIVAL"]
    slot: int = Field(ge=0)
    region: str | None = None
    magnitude: float = Field(default=1, ge=0)
    data_kind: Literal["SIMULATED"] = "SIMULATED"

class ReplayState(Contract):
    status: Literal["NOT_IMPLEMENTED", "READY", "RUNNING", "COMPLETED"]
    current_slot: int
    seed: int
    strategies: list[Strategy]

class Health(Contract):
    status: Literal["ok"] = "ok"
    stage: Literal["SCAFFOLD"] = "SCAFFOLD"
