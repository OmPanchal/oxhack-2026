import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.api.schemas import ForecastRequest, Job, MarketSnapshot
from app.main import create_app

FIXTURE = Path(__file__).resolve().parents[3] / "data/scenarios/demo.json"


def test_shared_fixture_and_job_api(tmp_path):
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
    assert TestClient(create_app()).get("/api/jobs").json() == [response.json()]
    assert TestClient(create_app(tmp_path / "other.sqlite3")).get("/api/jobs").json() == []
    # Impossible jobs must reach the optimizer; client-supplied lifecycle cannot.
    payload.update(id="impossible", deadlineSlot=0)
    assert client.post("/api/jobs", json=payload).status_code == 201
    assert client.post("/api/jobs", json={**payload, "status": "RUNNING"}).status_code == 422


@pytest.mark.parametrize("violation", ["future", "prediction"])
def test_forecaster_input_cannot_contain_unavailable_history(violation):
    fixture = json.loads(FIXTURE.read_text())
    if violation == "future":
        fixture["market"][0]["slot"] = 1
    else:
        fixture["market"][0]["dataKind"] = "FORECAST"
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


def test_multiple_gpu_alternatives_round_trip_as_one_job():
    payload = json.loads(FIXTURE.read_text())["jobs"][0]
    payload.pop("status")
    payload["gpuType"] = None
    payload["allowedGpuTypes"] = ["A100", "H100", "A100"]
    client = TestClient(create_app())
    result = client.post("/api/jobs", json=payload)
    assert result.status_code == 201
    assert result.json()["gpuType"] is None
    assert result.json()["allowedGpuTypes"] == ["A100", "H100"]
    assert result.json()["resourceUnits"] == payload["resourceUnits"]
    assert len(client.get("/api/jobs").json()) == 1


def test_legacy_single_gpu_and_invalid_alternatives():
    payload = json.loads(FIXTURE.read_text())["jobs"][0]
    payload.pop("status")
    client = TestClient(create_app())
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 201
    assert response.json()["allowedGpuTypes"] == [payload["gpuType"]]
    payload["id"] = "another-job"
    payload["allowedGpuTypes"] = ["H100"]
    assert client.post("/api/jobs", json=payload).status_code == 422
    payload["gpuType"] = None
    payload["allowedGpuTypes"] = [" "]
    assert client.post("/api/jobs", json=payload).status_code == 422
    payload["resourceType"] = "CPU"
    payload["allowedGpuTypes"] = ["A100"]
    assert client.post("/api/jobs", json=payload).status_code == 422
    payload["allowedGpuTypes"] = []
    assert client.post("/api/jobs", json=payload).status_code == 201
