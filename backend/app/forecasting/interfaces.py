"""Person 1 owns implementations; Person 2 consumes this protocol."""
from typing import Protocol
from app.api.schemas import Forecast, ForecastRequest

class ForecastService(Protocol):
    def predict(self, request: ForecastRequest) -> list[Forecast]:
        """Use only request.history; return 1–6 hour targets with model provenance."""
        ...
