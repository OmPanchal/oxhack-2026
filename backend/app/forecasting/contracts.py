"""Executable Person 1 forecasting conventions on top of the shared API schema."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from app.api.schemas import Forecast, ForecastRequest, MarketSnapshot
from app.forecasting.collect_spot import utc

PoolKey = tuple[str, str, str]


def timestamp_for_slot(origin: str | datetime, slot: int) -> datetime:
    origin = utc(origin)
    if origin.minute or origin.second or origin.microsecond:
        raise ValueError("UTC origin must be an exact hour")
    if type(slot) is not int or slot < 0:
        raise ValueError("Slot must be a nonnegative integer")
    return origin + timedelta(hours=slot)


def slot_for_timestamp(origin: str | datetime, timestamp: str | datetime) -> int:
    origin = timestamp_for_slot(origin, 0)
    offset = utc(timestamp) - origin
    if offset < timedelta(0) or offset % timedelta(hours=1):
        raise ValueError("Timestamp must be an hourly boundary at or after origin")
    return offset // timedelta(hours=1)


def pool_key(row: MarketSnapshot | Forecast) -> PoolKey:
    if not row.region.strip():
        raise ValueError("Region must be nonempty")
    if row.resource_type == "GPU" and not (row.gpu_type and row.gpu_type.strip()):
        raise ValueError("GPU observations require a specific gpuType")
    if row.resource_type == "CPU" and row.gpu_type is not None:
        raise ValueError("CPU observations require null gpuType")
    return row.region, row.resource_type, row.gpu_type or ""


def current_observations(request: ForecastRequest) -> list[MarketSnapshot]:
    """Require a current observation per represented pool; old price events are fine.

    An unchanged price reconstructed at the current boundary is a current
    observation. A snapshot from a prior scheduling slot is stale. Do not use
    this helper to merge distinct instance types/AZs into one API pool key.
    """
    request = ForecastRequest.model_validate(request.model_dump())
    by_slot = {}
    latest = {}
    for row in request.history:
        key = pool_key(row)
        observation_key = (*key, row.slot)
        if observation_key in by_slot and by_slot[observation_key] != row:
            raise ValueError("Conflicting snapshots for the same pool and slot")
        by_slot[observation_key] = row
        if key not in latest or row.slot > latest[key].slot:
            latest[key] = row
    if any(row.slot != request.current_slot for row in latest.values()):
        raise ValueError("Stale pool snapshot: a current-slot observation is required")
    return [latest[key] for key in sorted(latest)]


def validate_forecasts(request: ForecastRequest, forecasts: list[Forecast]) -> list[Forecast]:
    """Enforce one future forecast per current pool/target with honest intervals."""
    pools = {pool_key(row) for row in current_observations(request)}
    expected = {(key, request.current_slot + horizon) for key in pools
                for horizon in range(1, request.horizon_slots + 1)}
    seen = set()
    validated = []
    for candidate in forecasts:
        row = Forecast.model_validate(candidate.model_dump())
        key = (pool_key(row), row.target_slot)
        if row.generated_at_slot != request.current_slot or key not in expected or key in seen:
            raise ValueError("Unexpected, duplicate or incorrectly timestamped forecast")
        if not row.model_version.strip():
            raise ValueError("Forecast requires model provenance")
        if (row.price_lower_bound is None) != (row.price_upper_bound is None):
            raise ValueError("Provide both uncertainty bounds or leave both unknown")
        if row.price_lower_bound is not None and not (
            row.price_lower_bound <= row.predicted_price_usd_per_unit_hour <= row.price_upper_bound
        ):
            raise ValueError("Forecast interval must contain its predicted price")
        seen.add(key)
        validated.append(row)
    if seen != expected:
        raise ValueError("Missing forecast pool/target combinations")
    return sorted(validated, key=lambda row: (pool_key(row), row.target_slot))


class FixtureForecastService:
    """Contract demonstration only: returns hand-authored, explicitly fixture predictions.

    Only the exact fixture request is supported. This is not the persistence
    baseline, trained ML, or a general-purpose forecasting implementation.
    """

    def __init__(self, fixture_path: Path):
        fixture = json.loads(fixture_path.read_text())
        if fixture.get("schemaVersion") != "forecast-contract-fixture-v1" or fixture.get("dataKind") != "SIMULATED":
            raise ValueError("Only the labeled forecasting contract fixture is supported")
        timestamp_for_slot(fixture["originUtc"], 0)
        self._request = ForecastRequest.model_validate(fixture["request"])
        forecasts = [Forecast.model_validate(row) for row in fixture["forecasts"]]
        if any(not row.model_version.startswith("contract-fixture-") for row in forecasts):
            raise ValueError("Fixture predictions require explicit fixture model versions")
        self._forecasts = validate_forecasts(self._request, forecasts)

    def predict(self, request: ForecastRequest) -> list[Forecast]:
        if request != self._request:
            raise ValueError("Fixture service supports only its exact demonstration request")
        return validate_forecasts(request, self._forecasts)
