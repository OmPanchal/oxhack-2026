"""Read-only provider catalog and whole-instance Spot quotes."""
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.api.schemas import Contract


class ProviderError(Contract):
    region: str
    code: str
    message: str


class GpuOffering(Contract):
    region: str
    instance_type: str
    gpu_type: str
    gpus_per_instance: int = Field(gt=0)
    gpu_memory_mib: int | None = None
    v_cpu_count: int | None = None
    memory_mib: int | None = None
    cpu_architectures: list[str]
    availability_zones: list[str]
    allocation_unit: Literal["WHOLE_INSTANCE"] = "WHOLE_INSTANCE"


class MarketCapabilities(Contract):
    provider: Literal["AWS", "CONFIGURED_MARKET", "NONE"]
    status: Literal["READY", "PARTIAL", "UNAVAILABLE", "NOT_CONFIGURED"]
    fetched_at_utc: datetime | None = None
    configured_regions: list[str] = Field(default_factory=list)
    allowed_gpu_types: list[str] = Field(default_factory=list)
    allowed_regions: list[str] = Field(default_factory=list)
    offerings: list[GpuOffering] = Field(default_factory=list)
    capacity_status: Literal["UNKNOWN", "SOURCE_DEFINED"] = "UNKNOWN"
    errors: list[ProviderError] = Field(default_factory=list)


class AwsSpotQuote(GpuOffering):
    availability_zone: str
    product_description: str
    price_usd_per_instance_hour: float = Field(ge=0)
    price_usd_per_gpu_hour: float = Field(ge=0)
    effective_at_utc: datetime
    observed_at_utc: datetime
    available_units: None = None
    capacity_status: Literal["UNKNOWN"] = "UNKNOWN"
    data_kind: Literal["OBSERVED"] = "OBSERVED"


class AwsSpotPrices(Contract):
    provider: Literal["AWS"] = "AWS"
    status: Literal["READY", "PARTIAL", "UNAVAILABLE", "NOT_CONFIGURED"]
    fetched_at_utc: datetime | None = None
    quotes: list[AwsSpotQuote] = Field(default_factory=list)
    errors: list[ProviderError] = Field(default_factory=list)
