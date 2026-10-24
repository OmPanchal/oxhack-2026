"""Server-owned observation sources; never expose unseen future rows."""
import json
from pathlib import Path
from typing import Protocol

from app.api.schemas import MarketSnapshot


class MarketSource(Protocol):
    def poll(self, current_slot: int) -> list[MarketSnapshot]:
        """Return the latest known rows through this slot, without consuming them."""
        ...


class MemoryMarketSource:
    """An explicit integration/test source, not a live cloud feed."""
    def __init__(self, observations: list[MarketSnapshot] | None = None):
        self.observations = list(observations or [])

    def poll(self, current_slot: int) -> list[MarketSnapshot]:
        return [row.model_copy(deep=True) for row in self.observations if row.slot <= current_slot]


class JsonMarketSource:
    """Read a server-configured file; its source and dataKind are preserved."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def poll(self, current_slot: int) -> list[MarketSnapshot]:
        content = json.loads(self.path.read_text(encoding="utf-8"))
        rows = content["market"] if isinstance(content, dict) else content
        observations = [MarketSnapshot.model_validate(row) for row in rows]
        return [row for row in observations if row.slot <= current_slot]
