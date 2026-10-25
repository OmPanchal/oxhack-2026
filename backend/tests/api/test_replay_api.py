from fastapi.testclient import TestClient

from app.main import create_app


def test_replay_routes_reset_step_state_shock_and_errors(tmp_path):
    client = TestClient(create_app(tmp_path / "api.sqlite3"))
    assert client.get("/api/replay/state").json()["initialized"] is False
    assert client.post("/api/replay/step", json={}).status_code == 409
    assert client.post("/api/replay/reset", json={"scenarioId": "../../missing"}).status_code == 404
    response = client.post("/api/replay/reset", json={"seed": 123})
    assert response.status_code == 200
    state = response.json()
    assert state["initialized"] is True
    assert state["currentSlot"] == 0
    assert state["executionMode"] == state["dataKind"] == "SIMULATED"
    assert len(state["strategyStates"]) == 4
    assert state["strategyStates"][-1]["status"] == "UNAVAILABLE"
    shock = client.post("/api/replay/shock", json={"kind": "PRICE_SPIKE", "slot": 0, "magnitude": 2})
    assert shock.status_code == 200
    assert shock.json()["eventId"] == "shock-0001"
    assert shock.json()["dataKind"] == "SIMULATED"
    response = client.post("/api/replay/step", json={"slots": 24})
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert client.get("/api/replay/state").json() == response.json()
    assert client.get("/api/jobs").json() == []
    assert client.get("/api/decisions").json() == []
    assert client.post("/api/replay/shock", json={"kind": "PRICE_SPIKE", "slot": 0}).status_code == 409
    assert client.post("/api/replay/step", json={"slots": 25}).status_code == 422
    assert client.post("/api/replay/shock", json={"kind": "JOB_ARRIVAL", "slot": 0}).status_code == 422
