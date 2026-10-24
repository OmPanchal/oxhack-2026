import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.api.schemas import ForecastRequest, Job, MarketSnapshot
from app.main import create_app

FIXTURE = Path(__file__).resolve().parents[3] / "data/scenarios/demo.json"


def test_shared_fixture_and_job_api():
    fixture = json.loads(FIXTURE.read_text())
    job = Job.model_validate(fixture["jobs"][0])
    for row in fixture["market"]:
        assert MarketSnapshot.model_validate(row).data_kind == "SIMULATED"
    client = TestClient(create_app())
    assert client.get("/api/health").json()["stage"] == "SCAFFOLD"
    payload = job.model_dump(by_alias=True, exclude={"status"})
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 201
    assert response.json()["durationSlots"] == 2
    assert "duration_slots" not in response.json()
    assert client.post("/api/jobs", json=payload).status_code == 409
    assert len(client.get("/api/jobs").json()) == 1
    assert TestClient(create_app()).get("/api/jobs").json() == []


def test_no_fake_optimization_or_execution():
    client = TestClient(create_app())
    assert client.post("/api/optimize", json={"currentSlot": 0}).status_code == 501
    assert client.post("/api/execute/demo-job-1").status_code == 501
    assert client.get("/api/metrics").status_code == 501
    assert client.get("/api/replay/state").json()["status"] == "NOT_IMPLEMENTED"


def test_forecaster_input_cannot_contain_future_observations():
    fixture = json.loads(FIXTURE.read_text())
    fixture["market"][0]["slot"] = 1
    with pytest.raises(ValidationError):
        ForecastRequest(current_slot=0, history=fixture["market"])


def test_all_required_routes_exist():
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    expected = {
        "/api/health": ["get"], "/api/jobs": ["get", "post"],
        "/api/market": ["get"], "/api/forecasts": ["get"],
        "/api/optimize": ["post"], "/api/decisions": ["get"],
        "/api/replay/reset": ["post"], "/api/replay/step": ["post"],
        "/api/replay/state": ["get"], "/api/replay/shock": ["post"],
        "/api/metrics": ["get"], "/api/models/metrics": ["get"],
        "/api/execute/{jobId}": ["post"],
    }
    for path, methods in expected.items():
        assert all(method in paths[path] for method in methods)
