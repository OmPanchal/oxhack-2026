from datetime import datetime, timedelta, timezone
import time

from fastapi.testclient import TestClient
import pytest

from app.api.schemas import MarketSnapshot
from app.engine.forecast_bridge import PersistenceForecastProvider
from app.main import create_app
from app.market.adapter import MemoryMarketSource


NOW = datetime(2026, 10, 24, 9, tzinfo=timezone.utc)


def observation(slot=0, price=10, capacity=1):
    return MarketSnapshot(slot=slot, region="west", resource_type="CPU",
                          price_usd_per_unit_hour=price, available_units=capacity,
                          source="test scenario only", data_kind="SIMULATED")


def workload(job_id="a", **changes):
    return {"id": job_id, "name": job_id, "arrivalSlot": 0, "durationSlots": 1,
            "deadlineSlot": 3, "resourceType": "CPU", "resourceUnits": 1,
            "allowedRegions": ["west"], "maxBudgetUsd": None, **changes}


class SpyProvider(PersistenceForecastProvider):
    def __init__(self, cheap_future=False):
        self.requests = []
        self.cheap_future = cheap_future

    def predict(self, request):
        self.requests.append(request.model_copy(deep=True))
        rows = super().predict(request)
        if self.cheap_future:
            for row in rows:
                row.predicted_price_usd_per_unit_hour = 1
                row.model_version = "injected-test-provider-not-trained-ml"
        return rows


def test_api_naive_and_injected_ml_use_only_available_history(tmp_path):
    source = MemoryMarketSource([observation(), observation(1, 2), observation(5, 999)])
    naive, ml = SpyProvider(), SpyProvider(cheap_future=True)
    app = create_app(tmp_path / "api.sqlite3", market_source=source, clock=lambda: NOW,
                     forecast_services={"NAIVE": naive, "ML": ml})
    client = TestClient(app)
    assert client.post("/api/jobs", json=workload()).status_code == 201
    response = client.post("/api/optimize", json={"currentSlot": 0})
    assert response.status_code == 200
    assert response.json()[0]["action"] == "RUN"
    response = client.post("/api/optimize", json={"currentSlot": 0, "forecastMode": "ML"})
    assert response.status_code == 200
    assert response.json()[0]["action"] == "WAIT"
    assert response.json()[0]["projectedCostUsd"] == 1
    assert [row["slot"] for row in client.get("/api/market").json()] == [0]
    for provider in [naive, ml]:
        assert all(row.slot <= request.current_slot for request in provider.requests for row in request.history)
        assert provider.requests[0].history[0].price_usd_per_unit_hour == 10
    predictions = client.get("/api/forecasts").json()
    assert len(predictions) == 6
    assert all(row["generatedAtSlot"] == 0 for row in predictions)
    assert len(client.get("/api/forecasts?forecastMode=NAIVE").json()) == 6
    assert len(client.get("/api/decisions").json()) == 2
    detail = client.get("/api/decisions/details").json()[-1]
    assert detail["forecastMode"] == "ML"
    assert detail["deadlineSlackSlots"] == 1
    assert detail["costBreakdown"]["computeUsd"] == 1
    assert detail["dataKind"] == "SIMULATED"
    assert detail["forecastsUsed"][0]["modelVersion"] == "injected-test-provider-not-trained-ml"
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"
    restarted = TestClient(create_app(tmp_path / "api.sqlite3", clock=lambda: NOW))
    assert restarted.get("/api/decisions/details").json()[-1] == detail
    assert restarted.get("/api/forecasts").json() == predictions


def test_missing_ml_is_explicit_and_never_falls_back(tmp_path):
    app = create_app(tmp_path / "missing.sqlite3", market_source=MemoryMarketSource([observation()]), clock=lambda: NOW)
    client = TestClient(app)
    client.post("/api/jobs", json=workload())
    response = client.post("/api/optimize", json={"currentSlot": 0, "forecastMode": "ML"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "FORECAST_PROVIDER_UNAVAILABLE"
    state = client.get("/api/engine/state").json()
    assert state["mlConfigured"] is False
    assert state["lastError"]["code"] == "FORECAST_PROVIDER_UNAVAILABLE"
    assert client.get("/api/forecasts?forecastMode=ML").json() == []
    assert client.get("/api/decisions").json() == []


@pytest.mark.parametrize("problem, code", [
    ("missing", "FORECAST_COVERAGE_INCOMPLETE"), ("future", "INVALID_FORECAST_OUTPUT"),
    ("duplicate", "INVALID_FORECAST_OUTPUT"), ("error", "FORECAST_PROVIDER_FAILED"),
    ("wrong_series", "INVALID_FORECAST_OUTPUT"), ("past_target", "FORECAST_PROVIDER_FAILED"),
])
def test_bad_forecast_provider_does_not_commit_a_plan(tmp_path, problem, code):
    class BadProvider(PersistenceForecastProvider):
        def predict(self, request):
            rows = super().predict(request)
            if problem == "missing":
                return rows[:-1]
            if problem == "future":
                rows[0].generated_at_slot = request.current_slot + 1
                rows[0].target_slot = request.current_slot + 2
            elif problem == "duplicate":
                rows.append(rows[0])
            elif problem == "error":
                raise RuntimeError("Test provider failure")
            elif problem == "wrong_series":
                rows[0].region = "unknown"
            else:
                rows[0].target_slot = request.current_slot
            return rows

    client = TestClient(create_app(tmp_path / "bad.sqlite3", clock=lambda: NOW,
                                  market_source=MemoryMarketSource([observation()]),
                                  forecast_services={"ML": BadProvider()}))
    client.post("/api/jobs", json=workload())
    response = client.post("/api/optimize", json={"currentSlot": 0, "forecastMode": "ML", "executionMode": "SIMULATED"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == code
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"
    assert client.get("/api/decisions/details").json() == []
    assert client.get("/api/forecasts?forecastMode=ML").json() == []


def test_time_reversal_local_dispatch_and_extra_authoritative_fields_rejected(tmp_path):
    client = TestClient(create_app(tmp_path / "time.sqlite3", clock=lambda: NOW,
                                  market_source=MemoryMarketSource([observation()])))
    assert client.post("/api/optimize", json={"currentSlot": 2}).status_code == 200
    assert client.post("/api/optimize", json={"currentSlot": 1}).status_code == 409
    assert client.post("/api/optimize", json={"currentSlot": 2, "executionMode": "LOCAL"}).status_code == 503
    assert client.post("/api/optimize", json={"currentSlot": 2, "forecasts": []}).status_code == 422


def test_background_loop_replans_after_job_arrival_and_capacity_change(tmp_path):
    source = MemoryMarketSource([observation()])
    provider = SpyProvider()
    app = create_app(tmp_path / "background.sqlite3", market_source=source, clock=lambda: NOW,
                     forecast_services={"NAIVE": provider}, tick_interval_seconds=.02)

    def wait_for(client, predicate):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            rows = client.get("/api/decisions").json()
            if predicate(rows):
                return rows
            time.sleep(.02)
        pytest.fail("Background scheduler did not produce the expected decision")

    with TestClient(app) as client:
        client.post("/api/jobs", json=workload())
        wait_for(client, lambda rows: rows and rows[-1]["action"] == "RUN")
        source.observations = [observation(capacity=0)]
        wait_for(client, lambda rows: rows and rows[-1]["reasonCode"] == "CAPACITY_UNAVAILABLE")
        assert len(provider.requests) >= 2
        assert client.get("/api/engine/state").json()["autoTickEnabled"] is True
        assert client.get("/api/jobs").json()[0]["status"] == "PENDING"


def test_server_configured_json_source_preserves_simulated_label(tmp_path, monkeypatch):
    import json
    path = tmp_path / "market.json"
    path.write_text(json.dumps({"market": [observation().model_dump(mode="json", by_alias=True),
                                            observation(4).model_dump(mode="json", by_alias=True)]}))
    monkeypatch.setenv("COMPUTE_MARKET_FILE", str(path))
    client = TestClient(create_app(tmp_path / "file.sqlite3", clock=lambda: NOW))
    assert client.post("/api/optimize", json={"currentSlot": 0}).status_code == 200
    assert len(client.get("/api/market").json()) == 1
    assert client.get("/api/engine/state").json()["dataKind"] == "SIMULATED"


def test_broken_source_and_monitor_return_explicit_unavailable(tmp_path):
    class BrokenSource:
        def poll(self, slot):
            raise OSError("Test source offline")

    class BrokenMonitor:
        def poll(self, slot):
            raise OSError("Test monitor offline")

    for source, monitor, code in [
        (BrokenSource(), None, "MARKET_SOURCE_FAILED"),
        (MemoryMarketSource([observation()]), BrokenMonitor(), "EXECUTION_MONITOR_FAILED"),
    ]:
        client = TestClient(create_app(tmp_path / f"{code}.sqlite3", clock=lambda: NOW,
                                      market_source=source, monitor=monitor))
        response = client.post("/api/optimize", json={"currentSlot": 0})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == code


def test_explicit_origin_controls_wall_clock_slot_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPUTE_ORIGIN_UTC", "2026-10-24T07:00:00+00:00")
    app = create_app(tmp_path / "origin.sqlite3", clock=lambda: NOW,
                     market_source=MemoryMarketSource([observation()]))
    app.state.engine.tick()
    assert app.state.engine.state().current_slot == 2


def test_current_wall_clock_is_exposed_even_when_market_polling_fails(tmp_path):
    now = [NOW]
    class Offline:
        def poll(self, slot):
            raise OSError('offline fixture')
    client = TestClient(create_app(tmp_path / 'clock.sqlite3', clock=lambda: now[0],
                                  market_source=Offline(), tick_interval_seconds=0))
    initial = client.get('/api/engine/state').json()
    assert initial['wallClockSlot'] == initial['currentSlot'] == 0
    now[0] += timedelta(hours=2)
    assert client.post('/api/optimize', json={'currentSlot': 2}).status_code == 503
    state = client.get('/api/engine/state').json()
    assert state['wallClockSlot'] == 2
    assert state['lastError']['code'] == 'MARKET_SOURCE_FAILED'
