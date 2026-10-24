"""Person 2: forecasting and execution remain outside the optimizer."""
from typing import Protocol
from app.api.schemas import Decision, OptimizationInput

class PortfolioOptimizer(Protocol):
    def optimize(self, inputs: OptimizationInput) -> list[Decision]:
        """Allocate shared capacity; never duplicate running jobs."""
        ...
