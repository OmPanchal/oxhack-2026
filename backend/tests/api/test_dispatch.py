"""Pause/resume behavior, fresh planning and races at real start boundaries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient
from app.api.schemas import MarketSnapshot
from app.engine.forecast_bridge import PersistenceForecastProvider
from app.main import create_app
from app.market.adapter import MemoryMarketSource
from test_execution import NOW, setup


def market():
    return MemoryMarketSource([MarketSnapshot(slot=0, region="local", resource_type="CPU",
        price_usd_per_unit_hour=5, available_units=1, source="pause test scenario", data_kind="SIMULATED")])


def test_pause_survives_restart_keeps_monitoring_plans_and_replay_independent(tmp_path):
    source = market()
    adapter, path, app, client, job = setup(tmp_path, market_source=source)
    first = client.post("/api/execute/local-job").json()
    client.post("/api/jobs", json={**job, "id": "second"})
    assert client.post("/api/engine/pause", json={}).json()["dispatch"]["paused"]
    restarted_app = create_app(path, clock=lambda: NOW, execution_adapter=adapter, market_source=source)
    restarted = TestClient(restarted_app)
    assert restarted.get("/api/engine/state").json()["dispatch"]["paused"]
    assert restarted.post("/api/execute/second").json()["detail"]["code"] == "DISPATCH_PAUSED"
    adapter.observed.update(state="exited", completed_at_utc=NOW + timedelta(seconds=1), stdout="done")
    source.observations[0].price_usd_per_unit_hour = 7
    restarted_app.state.engine.poll()
    assert restarted.get("/api/executions/" + first["id"]).json()["status"] == "COMPLETED"
    response = restarted.post("/api/optimize", json={"currentSlot": 0, "executionMode": "SIMULATED"})
    assert response.json()[0]["action"] == "RUN"
    assert restarted.get("/api/jobs").json()[1]["status"] == "PENDING"
    assert restarted.get("/api/decisions/details").json()[-1]["dispatchBlockReason"] == "DISPATCH_PAUSED"
    assert restarted.get("/api/forecasts").json()[0]["predictedPriceUsdPerUnitHour"] == 7
    assert restarted.post("/api/execute/local-job").json()["id"] == first["id"]
    assert adapter.launches == 1
    restarted.post("/api/replay/reset", json={})
    assert restarted.post("/api/replay/step", json={"slots": 1}).json()["currentSlot"] == 1
    assert restarted.get("/api/engine/state").json()["dispatch"]["paused"]


def test_resume_replans_using_changed_capacity_before_allowing_starts(tmp_path):
    source = market()
    _, _, app, client, _ = setup(tmp_path, market_source=source)
    client.post("/api/engine/pause")
    assert client.post("/api/optimize", json={"currentSlot": 0, "executionMode": "SIMULATED"}).json()[0]["action"] == "RUN"
    source.observations[0].available_units = 0
    response = client.post("/api/engine/resume")
    assert response.status_code == 200 and response.json()["dispatch"]["paused"] is False
    assert response.json()["dispatch"]["lastResumedAtUtc"]
    assert client.get("/api/decisions").json()[-1]["action"] == "WAIT"
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"
    source.observations[0].available_units = 1
    app.state.engine.poll()
    assert client.get("/api/jobs").json()[0]["status"] == "RUNNING"


@pytest.mark.parametrize("outage", ["market", "forecast"])
def test_failed_resume_remains_paused_across_restart(tmp_path, outage):
    source = market()
    adapter, path, _, client, _ = setup(tmp_path, market_source=source)
    client.post("/api/engine/pause")
    if outage == "market":
        source.poll = lambda slot: (_ for _ in ()).throw(OSError("offline"))
    else:
        # Resume cannot open the gate without its selected forecast provider.
        client.app.state.engine.providers["NAIVE"] = None
    response = client.post("/api/engine/resume")
    assert response.status_code == 503
    restarted = TestClient(create_app(path, clock=lambda: NOW, execution_adapter=adapter, market_source=source))
    dispatch = restarted.get("/api/engine/state").json()["dispatch"]
    assert dispatch["paused"] and dispatch["lastResumeError"]
    assert restarted.post("/api/execute/local-job").json()["detail"]["code"] == "DISPATCH_PAUSED"
    assert adapter.launches == 0


def test_pause_during_image_preparation_wins_before_claim_and_launch(tmp_path):
    adapter, path, app, client, _ = setup(tmp_path)
    other = TestClient(create_app(path, clock=lambda: NOW, execution_adapter=adapter))
    prepare = adapter.prepare
    def pause_before_prepared():
        assert other.post("/api/engine/pause").status_code == 200
        return prepare()
    adapter.prepare = pause_before_prepared
    response = client.post("/api/execute/local-job")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "DISPATCH_PAUSED"
    assert app.state.executions.list() == [] and adapter.launches == 0
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"


def test_new_pause_cancels_resume_that_is_still_forecasting(tmp_path):
    source = market()
    _, path, app, client, _ = setup(tmp_path, market_source=source)
    other = TestClient(create_app(path, clock=lambda: NOW, market_source=source))
    client.post("/api/engine/pause")
    class PauseDuringPrediction(PersistenceForecastProvider):
        def predict(self, request):
            assert other.post("/api/engine/pause").status_code == 200
            return super().predict(request)
    app.state.engine.providers["NAIVE"] = PauseDuringPrediction()
    response = client.post("/api/engine/resume")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESUME_SUPERSEDED"
    assert client.get("/api/engine/state").json()["dispatch"]["paused"]
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"


def test_pause_acknowledges_only_after_an_admitted_start_submission_finishes(tmp_path):
    adapter, path, _, client, _ = setup(tmp_path)
    other = TestClient(create_app(path, clock=lambda: NOW, execution_adapter=adapter))
    entered, release, pause_requested = Event(), Event(), Event()
    launch = adapter.launch
    def slow_launch(record):
        entered.set()
        assert release.wait(5)
        launch(record)
    adapter.launch = slow_launch
    def pause():
        pause_requested.set()
        return other.post("/api/engine/pause")
    with ThreadPoolExecutor(2) as pool:
        start = pool.submit(client.post, "/api/execute/local-job")
        try:
            assert entered.wait(5)
            paused = pool.submit(pause)
            assert pause_requested.wait(5)
            assert not paused.done()
        finally:
            release.set()
        assert start.result().status_code == 200
        assert paused.result().json()["dispatch"]["paused"]
    assert adapter.launches == 1
