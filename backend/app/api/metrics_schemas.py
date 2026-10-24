"""Official accounting responses; projections and realized simulation are separate."""
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.api.schemas import Contract, ExecutionMode, JobStatus, Strategy
from app.api.replay_schemas import ReplayCounters


class ReplayJobMetrics(Contract):
    job_id: str
    status: JobStatus
    resource_units: int
    resource_unit_hours: int
    started_at_slot: int | None
    completed_at_slot: int | None
    deadline_slot: int
    completion_slack_slots: int | None
    missed_deadline: bool
    compute_spend_usd: float
    startup_cost_usd: float
    transfer_cost_usd: float
    carbon_cost_usd: float
    recovery_cost_usd: float = 0
    total_spend_usd: float
    projected_cost_at_start_usd: float | None


class StrategyMetrics(Contract):
    strategy: Strategy
    status: Literal["ACTIVE", "UNAVAILABLE", "ERROR"]
    error: str | None
    model_versions: list[str] = Field(default_factory=list)
    ledger_reconciled: bool = True
    totals: ReplayCounters
    completed_job_ids: list[str]
    failed_job_ids: list[str]
    infeasible_job_ids: list[str]
    unfinished_job_ids: list[str]
    missed_deadline_job_ids: list[str]
    jobs: list[ReplayJobMetrics]


class PolicyComparison(Contract):
    strategy: Strategy
    baseline: Strategy
    comparable: bool
    reason_code: Literal["COMPARABLE", "IN_PROGRESS", "STRATEGY_UNAVAILABLE", "STRATEGY_ERROR",
                         "DIFFERENT_WORKLOADS", "DIFFERENT_OUTCOMES", "UNFINISHED_WORK", "NO_COMPLETED_WORK"]
    explanation: str
    baseline_spend_usd: float | None
    strategy_spend_usd: float | None
    cost_difference_usd: float | None
    savings_usd: float | None
    savings_percent: float | None
    same_completed_jobs: bool
    same_outcomes: bool
    all_jobs_completed: bool


class ReplayMetrics(Contract):
    scope: Literal["REPLAY"] = "REPLAY"
    status: Literal["NOT_INITIALIZED", "IN_PROGRESS", "COMPLETED"]
    execution_mode: Literal["SIMULATED"] = "SIMULATED"
    cost_basis: Literal["SIMULATED_REALIZED"] = "SIMULATED_REALIZED"
    data_kind: Literal["SIMULATED"] = "SIMULATED"
    currency: Literal["USD"] = "USD"
    monetary_precision_usd: float = 1e-9
    scenario_id: str | None = None
    origin_utc: datetime | None = None
    as_of_slot: int = 0
    end_slot: int | None = None
    strategies: list[StrategyMetrics] = Field(default_factory=list)
    comparisons: list[PolicyComparison] = Field(default_factory=list)


class JobProjection(Contract):
    job_id: str
    decided_at_slot: int
    execution_mode: ExecutionMode
    projected_cost_usd: float | None


class LifecycleCounts(Contract):
    pending_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    infeasible_jobs: int
    unfinished_jobs: int
    missed_deadlines: int


class LiveMetrics(Contract):
    scope: Literal["LIVE"] = "LIVE"
    cost_basis: Literal["PROJECTED"] = "PROJECTED"
    currency: Literal["USD"] = "USD"
    monetary_precision_usd: float = 1e-9
    as_of_slot: int
    active_execution_mode: ExecutionMode
    job_counts: LifecycleCounts
    missed_deadline_job_ids: list[str]
    unknown_completion_time_job_ids: list[str]
    known_projected_cost_usd: float
    projected_portfolio_cost_usd: float | None
    unpriced_outstanding_job_ids: list[str]
    projections: list[JobProjection]
    realized_spend_usd: None = None
    realized_savings_usd: None = None


class CalibrationBin(Contract):
    sample_count: int = Field(gt=0)
    mean_predicted_probability: float = Field(ge=0, le=1)
    observed_frequency: float = Field(ge=0, le=1)


class RiskEvaluation(Contract):
    has_historical_labels: Literal[True]
    label_source: str = Field(min_length=1)
    sample_count: int = Field(gt=0)
    brier_score: float = Field(ge=0, le=1)
    calibration_bins: list[CalibrationBin] | None = None
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    classification_threshold: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def risk_metric_context(self):
        if self.calibration_bins is not None and sum(row.sample_count for row in self.calibration_bins) != self.sample_count:
            raise ValueError("Calibration bins must account for all labeled samples")
        if (self.precision is not None or self.recall is not None) and self.classification_threshold is None:
            raise ValueError("Classification metrics require their probability threshold")
        return self


class ModelEvaluation(Contract):
    model_version: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    sample_count: int = Field(gt=0)
    train_start_utc: datetime
    train_end_utc: datetime
    validation_start_utc: datetime
    validation_end_utc: datetime
    test_start_utc: datetime
    test_end_utc: datetime
    evaluated_at_utc: datetime
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)
    persistence_mae: float = Field(ge=0)
    persistence_rmse: float = Field(ge=0)
    risk: RiskEvaluation | None = None

    @model_validator(mode="after")
    def chronological_evaluation(self):
        times = [self.train_start_utc, self.train_end_utc, self.validation_start_utc,
                 self.validation_end_utc, self.test_start_utc, self.test_end_utc, self.evaluated_at_utc]
        if any(time.utcoffset() is None or time.utcoffset().total_seconds() != 0 for time in times):
            raise ValueError("Evaluation timestamps must be aware UTC")
        if not (times[0] < times[1] <= times[2] < times[3] <= times[4] < times[5] <= times[6]):
            raise ValueError("Evaluation requires chronological disjoint train/validation/test periods")
        if self.rmse + 1e-12 < self.mae or self.persistence_rmse + 1e-12 < self.persistence_mae:
            raise ValueError("RMSE cannot be smaller than MAE for the same samples")
        return self


class ModelMetrics(Contract):
    status: Literal["UNAVAILABLE", "EVALUATED"]
    reason: str | None = None
    evaluation: ModelEvaluation | None = None
    mae_improvement: float | None = None
    rmse_improvement: float | None = None
    mae_improvement_percent: float | None = None
    rmse_improvement_percent: float | None = None
