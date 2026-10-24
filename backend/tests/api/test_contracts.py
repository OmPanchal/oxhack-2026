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
