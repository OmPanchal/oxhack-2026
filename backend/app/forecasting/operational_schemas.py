"""Versioned import records for optional operational evidence, not public API types."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StrictBool,
    field_validator, model_validator,
)
from pydantic.alias_generators import to_camel

from app.forecasting.collect_spot import utc

Text = Annotated[str, Field(min_length=1, strict=True)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
NonnegativeInt = Annotated[int, Field(ge=0, strict=True)]


class ImportModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              extra="forbid", frozen=True, str_strip_whitespace=True,
                              allow_inf_nan=False)

    @field_validator("retrieved_at", "recorded_at", "observed_until", "requested_at",
                     "started_at", "interrupted_at", mode="before", check_fields=False)
    @classmethod
    def normalize_timestamp(cls, value):
        if value is None:
            return None
        if not isinstance(value, (str, datetime)):
            raise ValueError("Use an ISO timestamp with an explicit timezone")
        return utc(value)


class LabelDefinitions(ImportModel):
    fulfillment: Text
    interruption: Text
    censoring: Text


class Provenance(ImportModel):
    source: Text
    retrieved_at: AwareDatetime
    data_kind: Literal["OBSERVED", "SIMULATED"]
    collection_conditions: Text
    label_definitions: LabelDefinitions
    authorized_for_use: StrictBool

    @model_validator(mode="after")
    def require_authorization(self) -> Self:
        if not self.authorized_for_use:
            raise ValueError("Only authorized operational exports may be imported")
        return self


class ResourceObservation(ImportModel):
    id: Text
    region: Text
    availability_zone: Text | None = None
    instance_type: Text
    resource_type: Literal["CPU", "GPU"]
    gpu_type: Text | None = None
    recorded_at: AwareDatetime
    observed_until: AwareDatetime

    @model_validator(mode="after")
    def validate_resource_and_record_time(self) -> Self:
        if (self.resource_type == "GPU") != (self.gpu_type is not None):
            raise ValueError("GPU observations require gpuType; CPU observations require null")
        if self.recorded_at < self.observed_until:
            raise ValueError("recordedAt must be at or after observedUntil")
        return self


class FulfillmentObservation(ResourceObservation):
    requested_at: AwareDatetime
    requested_units: PositiveInt
    fulfilled_units: NonnegativeInt
    outcome: Literal["FULFILLED", "PARTIAL", "UNAVAILABLE", "ERROR", "CENSORED"]

    @model_validator(mode="after")
    def validate_fulfillment(self) -> Self:
        if self.observed_until < self.requested_at:
            raise ValueError("observedUntil precedes requestedAt")
        if self.fulfilled_units > self.requested_units:
            raise ValueError("fulfilledUnits exceeds requestedUnits")
        if self.outcome == "FULFILLED" and self.fulfilled_units != self.requested_units:
            raise ValueError("FULFILLED requires every requested unit")
        if self.outcome == "PARTIAL" and not 0 < self.fulfilled_units < self.requested_units:
            raise ValueError("PARTIAL requires a nonzero, incomplete fulfillment")
        if self.outcome in ("UNAVAILABLE", "ERROR") and self.fulfilled_units != 0:
            raise ValueError("UNAVAILABLE and ERROR must have zero fulfilled units")
        if self.outcome == "CENSORED" and self.fulfilled_units == self.requested_units:
            raise ValueError("Fully fulfilled requests cannot be censored")
        return self


class ExecutionObservation(ResourceObservation):
    started_at: AwareDatetime
    resource_units: PositiveInt
    outcome: Literal["COMPLETED", "INTERRUPTED", "FAILED", "CENSORED"]
    interrupted_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_execution(self) -> Self:
        if self.observed_until <= self.started_at:
            raise ValueError("Execution exposure must have positive duration")
        if self.outcome == "INTERRUPTED":
            if self.interrupted_at != self.observed_until:
                raise ValueError("INTERRUPTED requires interruptedAt equal to observedUntil")
        elif self.interrupted_at is not None:
            raise ValueError("Only INTERRUPTED records may contain interruptedAt")
        return self


class OperationalDataset(ImportModel):
    schema_version: Literal["operational-observations-v1"]
    provenance: Provenance
    fulfillment_observations: list[FulfillmentObservation]
    execution_observations: list[ExecutionObservation]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        for records in (self.fulfillment_observations, self.execution_observations):
            ids = set()
            for record in records:
                if record.id in ids:
                    raise ValueError("Duplicate observation ID within the same record category")
                ids.add(record.id)
                if record.recorded_at > self.provenance.retrieved_at:
                    raise ValueError("recordedAt is after the export retrieval time")
        return self
