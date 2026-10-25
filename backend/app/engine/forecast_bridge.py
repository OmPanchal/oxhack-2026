"""Integration-owned provider wiring; Person 1's model modules stay untouched."""
from typing import Literal

from app.api.schemas import Forecast, ForecastRequest
from app.engine.optimizer import resource_key
from app.forecasting.interfaces import ForecastService

ForecastMode = Literal["NAIVE", "ML"]


class EngineUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PersistenceForecastProvider:
    """Temporary adapter until Person 1 supplies their naive ForecastService."""
    def predict(self, request: ForecastRequest) -> list[Forecast]:
        latest = {}
        for row in request.history:
            key = resource_key(row)
            if key not in latest or row.slot > latest[key].slot:
                latest[key] = row
        return [Forecast(
            generated_at_slot=request.current_slot, target_slot=request.current_slot + horizon,
            region=row.region, resource_type=row.resource_type, gpu_type=row.gpu_type,
            predicted_price_usd_per_unit_hour=row.price_usd_per_unit_hour,
            model_version="integration-persistence-v1",
        ) for _, row in sorted(latest.items(), key=lambda item: repr(item[0]))
            for horizon in range(1, request.horizon_slots + 1)]


def predict_checked(provider: ForecastService | None, mode: ForecastMode,
                    request: ForecastRequest, *, origin_utc=None) -> list[Forecast]:
    if provider is None:
        raise EngineUnavailable("FORECAST_PROVIDER_UNAVAILABLE", f"{mode} forecasting is not configured")
    try:
        aligned = getattr(provider, 'predict_at', None)
        result = aligned(request, origin_utc) if aligned and origin_utc is not None else provider.predict(request)
        predictions = [Forecast.model_validate(row.model_dump()) for row in result]
    except Exception as exc:
        raise EngineUnavailable("FORECAST_PROVIDER_FAILED", f"{mode} forecasting failed: {exc}") from exc
    expected = {(resource_key(row), request.current_slot + horizon)
                for row in request.history for horizon in range(1, request.horizon_slots + 1)}
    seen = set()
    for row in predictions:
        key = resource_key(row), row.target_slot
        if (row.generated_at_slot != request.current_slot
                or not request.current_slot < row.target_slot <= request.current_slot + request.horizon_slots
                or key not in expected or key in seen
                or (row.price_lower_bound is not None and row.price_upper_bound is not None
                    and row.price_lower_bound > row.price_upper_bound)):
            raise EngineUnavailable("INVALID_FORECAST_OUTPUT", "Provider returned invalid targets, vintages or duplicate series")
        seen.add(key)
    if seen != expected:
        raise EngineUnavailable("FORECAST_COVERAGE_INCOMPLETE", "Provider did not cover every observed resource and requested hour")
    return predictions
