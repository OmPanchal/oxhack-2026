"""Naive forecasts using only the latest available current-slot observations."""
from app.api.schemas import Forecast, ForecastRequest, MarketSnapshot
from app.forecasting.contracts import current_observations, validate_forecasts


def persistence_forecasts(row: MarketSnapshot, request: ForecastRequest,
                          reason: str | None = None) -> list[Forecast]:
    version = "persistence-v1" + (f":fallback-{reason}" if reason else "")
    return [Forecast(generated_at_slot=request.current_slot,
                     target_slot=request.current_slot + horizon,
                     region=row.region, resource_type=row.resource_type, gpu_type=row.gpu_type,
                     predicted_price_usd_per_unit_hour=row.price_usd_per_unit_hour,
                     price_lower_bound=None, price_upper_bound=None,
                     availability_probability=None, interruption_probability=None,
                     model_version=version)
            for horizon in range(1, request.horizon_slots + 1)]


class PersistenceForecastService:
    """Forecast that each pool's price stays at its current observed value."""

    def predict(self, request: ForecastRequest) -> list[Forecast]:
        rows = current_observations(request)
        return validate_forecasts(request, [forecast for row in rows
                                            for forecast in persistence_forecasts(row, request)])
