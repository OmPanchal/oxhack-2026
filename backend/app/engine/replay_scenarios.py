"""Server-side scenario registry; no frontend-supplied file paths."""
from datetime import datetime, timezone
import json
from pathlib import Path

from app.api.replay_schemas import ReplayScenario
from app.api.schemas import JobCreate, MarketSnapshot


def demo_scenario() -> ReplayScenario:
    path = Path(__file__).resolve().parents[3] / "data" / "scenarios" / "demo.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    jobs = [JobCreate.model_validate({key: value for key, value in row.items() if key != "status"})
            for row in fixture["jobs"]]
    end = max([8] + [job.deadline_slot + 2 for job in jobs])
    base = [MarketSnapshot.model_validate(row) for row in fixture["market"]]
    rows = [row.model_copy(update={"slot": slot, "data_kind": "SIMULATED",
                                  "source": "SIMULATED flat carry-forward of illustrative demo fixture"})
            for slot in range(end) for row in base]
    return ReplayScenario(id="demo", description="Illustrative flat-price SIMULATED scenario; not historical benchmark data",
                          origin_utc=datetime(2000, 1, 1, tzinfo=timezone.utc), end_slot=end, jobs=jobs, market=rows)
