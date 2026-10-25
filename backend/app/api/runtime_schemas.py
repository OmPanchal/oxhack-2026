"""Additive monitoring/detail endpoints; existing domain schemas are unchanged."""
from datetime import datetime
from typing import Literal
from pydantic import Field

from app.api.schemas import Contract, ExecutionMode, Forecast


class DispatchState(Contract):
    paused: bool = False
    revision: int = 0
    changed_at_utc: datetime | None = None
    last_resumed_at_utc: datetime | None = None
    last_resume_error: dict[str, str] | None = None
    automatic_local_dispatch_enabled: bool = False


class EngineState(Contract):
    current_slot: int
    wall_clock_slot: int = Field(ge=0)
    origin_utc: datetime
    forecast_mode: Literal["NAIVE", "ML"]
    execution_mode: ExecutionMode
    last_tick_at_utc: datetime | None = None
    last_error: dict[str, str] | None = None
    auto_tick_enabled: bool = False
    ml_configured: bool = False
    data_kind: Literal["OBSERVED", "SIMULATED", "MIXED"] | None = None
    dispatch: DispatchState = Field(default_factory=DispatchState)
    acquisition_mode: Literal['DISABLED', 'SIMULATED'] = 'DISABLED'
    simulation_slot_seconds: float | None = None


class DecisionDetail(Contract):
    decision_id: int
    job_id: str
    decided_at_slot: int
    forecast_mode: Literal["NAIVE", "ML"] | None = None
    execution_mode: ExecutionMode
    deadline_slack_slots: int | None
    forecasts_used: list[Forecast]
    cost_breakdown: dict[str, float] | None
    availability_probability: float | None
    interruption_probability: float | None
    data_kind: Literal["OBSERVED", "SIMULATED", "MIXED"] | None
    market_sources: list[str]
    pricing_assumption: str | None = None
    dispatch_blocked: bool = False
    dispatch_block_reason: str | None = None
