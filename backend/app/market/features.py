"""The same causal feature builder is used for offline training and inference."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
from statistics import fmean, pstdev
from typing import Mapping

from app.forecasting.contracts import timestamp_for_slot

FEATURE_SCHEMA_VERSION = "causal-price-v1"
LOOKBACK_SLOTS = 24
MAX_HORIZON = 6
LAGS = (1, 2, 3, 6, 12, 24)
WINDOWS = (3, 6, 12, 24)


class InsufficientHistoryError(ValueError):
    """A required historical slot is absent or explicitly unknown."""


@dataclass(frozen=True, order=True)
class SeriesIdentity:
    region: str
    availability_zone: str
    instance_type: str
    product_description: str
    resource_type: str
    gpu_type: str = ""

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.region, self.availability_zone, self.instance_type, self.product_description
        )):
            raise ValueError("A series requires region, AZ, instance type and product")
        if not isinstance(self.gpu_type, str) or self.resource_type not in ("CPU", "GPU") or (
            self.resource_type == "GPU" and not self.gpu_type.strip()
        ) or (self.resource_type == "CPU" and self.gpu_type):
            raise ValueError("Invalid resource/GPU identity")

    @property
    def api_key(self) -> tuple[str, str, str]:
        return self.region, self.resource_type, self.gpu_type

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> SeriesIdentity:
        return cls(row["region"], row["availabilityZone"], row["instanceType"],
                   row["productDescription"], row["resourceType"], row["gpuType"] or "")


def build_features(prices: Mapping[int, float | None], identity: SeriesIdentity,
                   origin: str | datetime, current_slot: int, horizon: int) -> dict[str, float | str]:
    """Read exactly [currentSlot-24, currentSlot]; ignore all later values.

    No retrospective hourly averages or capacity assumptions enter these inputs.
    Calendar values for the future target are known at decision time.
    """
    if type(horizon) is not int or not 1 <= horizon <= MAX_HORIZON:
        raise ValueError("Forecast horizon must be 1–6 hours")
    current_time = timestamp_for_slot(origin, current_slot)
    target_time = timestamp_for_slot(origin, current_slot + horizon)
    history = []
    for slot in range(current_slot - LOOKBACK_SLOTS, current_slot + 1):
        value = prices.get(slot)
        if value is None:
            raise InsufficientHistoryError("Need 25 consecutive known hourly observations")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Historical prices must be finite and nonnegative")
        history.append(value)
    latest = history[-1]
    features = {
        "region": identity.region, "availabilityZone": identity.availability_zone,
        "instanceType": identity.instance_type, "productDescription": identity.product_description,
        "resourceType": identity.resource_type, "gpuType": identity.gpu_type or "NONE",
        "latestPrice": latest, "horizonHours": float(horizon),
        "lastPriceChange": latest - history[-2],
        "hourSin": math.sin(2 * math.pi * current_time.hour / 24),
        "hourCos": math.cos(2 * math.pi * current_time.hour / 24),
        "weekdaySin": math.sin(2 * math.pi * current_time.weekday() / 7),
        "weekdayCos": math.cos(2 * math.pi * current_time.weekday() / 7),
        "targetHourSin": math.sin(2 * math.pi * target_time.hour / 24),
        "targetHourCos": math.cos(2 * math.pi * target_time.hour / 24),
    }
    for lag in LAGS:
        features[f"lagPrice{lag}h"] = history[-1-lag]
    for window in WINDOWS:
        values = history[-window:]
        features[f"rollingMean{window}h"] = fmean(values)
        features[f"rollingStd{window}h"] = pstdev(values)
    age = next((offset for offset in range(LOOKBACK_SLOTS)
                if history[-1-offset] != history[-2-offset]), LOOKBACK_SLOTS)
    features["hoursSinceLastChange"] = float(age)
    features["priceAgeCapped"] = float(age == LOOKBACK_SLOTS)
    return features
