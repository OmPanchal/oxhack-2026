"""Person 1 owns implementations; Person 2 consumes this protocol."""
from typing import Protocol
from app.api.schemas import Forecast, ForecastRequest

class ForecastService(Protocol):
    def predict(self, request: ForecastRequest) -> list[Forecast]:
        """Use only request.history; return 1–6 hour targets with model provenance.

        Targets represent prices effective at future hourly boundaries. Return
        one target per horizon per current compatible pool. Empty history yields
        no forecasts; stale/conflicting input must be surfaced, not fabricated.
        Unknown uncertainty and risk remain null. See data/forecasting-contract.md
        and forecasting.contracts for the Person 1 integration defaults.
        """
        ...
