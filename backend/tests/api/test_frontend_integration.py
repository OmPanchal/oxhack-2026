"""Merged frontend contracts through actual backend services; no cloud/Docker."""
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.api.replay_schemas import ReplayScenario
from app.api.schemas import JobCreate, MarketSnapshot
from app.main import create_app
from app.market.adapter import MemoryMarketSource

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def quote(slot, model, capacity):
    return MarketSnapshot(slot=slot, region="west", resource_type="GPU", gpu_type=model,
        price_usd_per_unit_hour=1, available_units=capacity, source="SIMULATED integration fixture", data_kind="SIMULATED")


def workload():
    return dict(id="alternatives", name="frontend alternatives", arrivalSlot=0, durationSlots=2,
        deadlineSlot=3, resourceType="GPU", gpuType=None, allowedGpuTypes=["A100", "H100"],
        resourceUnits=2, allowedRegions=["west"], maxBudgetUsd=None, dockerTaskId=None)


def test_multi_gpu_job_persistence_scheduling_and_selected_model_reservation(tmp_path):
    path = tmp_path / "integration.sqlite3"
    rows = [quote(slot, model, cap) for slot in range(4) for model, cap in [("A100", 1), ("H100", 2)]]
    source = MemoryMarketSource(rows)
    app = create_app(path, market_source=source, clock=lambda: NOW, tick_interval_seconds=0)
    client = TestClient(app)
    created = client.post("/api/jobs", json=workload())
    assert created.status_code == 201
    assert created.json()["gpuType"] is None
    assert created.json()["allowedGpuTypes"] == ["A100", "H100"]
    assert client.post("/api/optimize", json={"currentSlot": 0, "executionMode": "SIMULATED"}).status_code == 200
    assert client.get("/api/jobs").json()[0]["status"] == "RUNNING"
    with app.state.engine.database.transaction() as connection:
        import json
        reservation = json.loads(connection.execute("SELECT payload FROM reservations").fetchone()[0])
        assert reservation["gpuType"] == "H100"
        assert reservation["resourceUnits"] == 2
    reopened = TestClient(create_app(path, market_source=source, clock=lambda: NOW, tick_interval_seconds=0))
    assert reopened.get("/api/jobs").json()[0]["allowedGpuTypes"] == ["A100", "H100"]
    assert reopened.post("/api/optimize", json={"currentSlot": 1, "executionMode": "SIMULATED"}).status_code == 200
    assert reopened.post("/api/optimize", json={"currentSlot": 2, "executionMode": "SIMULATED"}).status_code == 200
    assert reopened.get("/api/jobs").json()[0]["status"] == "COMPLETED"
    assert reopened.get("/api/engine/state").json()["currentSlot"] == 2
    assert reopened.get("/api/replay/state").json()["currentSlot"] == 0


def test_replay_policies_all_reserve_one_acceptable_gpu_model(tmp_path):
    rows = [quote(slot, model, cap) for slot in range(4) for model, cap in [("A100", 1), ("H100", 2)]]
    scenario = ReplayScenario(id="alternatives", description="SIMULATED integration test", origin_utc=NOW,
        end_slot=4, jobs=[JobCreate.model_validate(workload())], market=rows)
    client = TestClient(create_app(tmp_path / "replay.sqlite3", replay_scenarios={"alternatives": scenario}, clock=lambda: NOW, tick_interval_seconds=0))
    assert client.post("/api/replay/reset", json={"scenarioId": "alternatives", "seed": 42}).status_code == 200
    result = client.post("/api/replay/step", json={"slots": 1})
    assert result.status_code == 200
    for run in result.json()["strategyStates"]:
        if run["status"] == "ACTIVE":
            assert run["jobs"][0]["status"] == "RUNNING", run
            assert run["reservations"][0]["gpuType"] == "H100", run
            assert run["reservations"][0]["resourceUnits"] == 2
    result = client.post("/api/replay/step", json={"slots": 3})
    assert result.status_code == 200
    for run in result.json()["strategyStates"]:
        if run["status"] == "ACTIVE":
            assert run["jobs"][0]["status"] == "COMPLETED", run
