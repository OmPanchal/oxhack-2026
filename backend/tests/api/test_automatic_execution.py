"""Only scheduler-approved, fresh, compatible local work reaches Docker."""
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from app.api.schemas import MarketSnapshot
from app.engine.forecast_bridge import PersistenceForecastProvider
from app.main import create_app
from app.market.adapter import MemoryMarketSource
from test_execution import NOW, setup


def source(capacity=1):
    return MemoryMarketSource([MarketSnapshot(slot=0, region="local", resource_type="CPU",
        price_usd_per_unit_hour=5, available_units=capacity, source="automatic test fixture", data_kind="SIMULATED")])


def local(client):
    return client.post("/api/optimize", json={"currentSlot": 0, "executionMode": "LOCAL"})


def test_requires_opt_in_and_paper_never_launches(tmp_path):
    adapter, _, app, client, _ = setup(tmp_path, market_source=source())
    assert local(client).status_code == 503
    app.state.engine.local_dispatcher = app.state.executions
    assert client.get("/api/engine/state").json()["dispatch"]["automaticLocalDispatchEnabled"]
    assert client.get("/api/execution/tasks").json()["automaticDispatchEnabled"]
    assert client.post("/api/optimize", json={"currentSlot": 0}).status_code == 200
    assert adapter.launches == 0
    assert client.post("/api/optimize", json={"currentSlot": 1, "executionMode": "LOCAL"}).status_code == 409


def test_wait_then_run_restart_and_opt_out_keep_outcomes_honest(tmp_path):
    market = source()
    adapter, path, app, client, _ = setup(tmp_path, market_source=market, allow_local_dispatch=True)
    class CheapFuture(PersistenceForecastProvider):
        def predict(self, request):
            return [row.model_copy(update={"predicted_price_usd_per_unit_hour": 1}) for row in super().predict(request)]
    app.state.engine.providers["NAIVE"] = CheapFuture()
    assert local(client).json()[0]["action"] == "WAIT"
    assert adapter.launches == 0
    app.state.engine.providers["NAIVE"] = PersistenceForecastProvider()
    assert local(client).json()[0]["action"] == "RUN"
    assert adapter.launches == 1
    restarted = create_app(path, clock=lambda: NOW, market_source=market, execution_adapter=adapter, allow_local_dispatch=True)
    restarted.state.engine.poll()
    assert adapter.launches == 1
    adapter.observed.update(state="exited", completed_at_utc=NOW + timedelta(seconds=1))
    disabled = create_app(path, clock=lambda: NOW, market_source=market, execution_adapter=adapter, allow_local_dispatch=False)
    disabled.state.engine.poll()
    assert disabled.state.engine.state().execution_mode == "PAPER"
    assert TestClient(disabled).get("/api/jobs").json()[0]["status"] == "COMPLETED"
    assert adapter.launches == 1


def test_paused_local_mode_resumes_with_fresh_plan_then_dispatches_next_tick(tmp_path):
    market = source()
    adapter, _, app, client, _ = setup(tmp_path, market_source=market, allow_local_dispatch=True)
    client.post("/api/engine/pause")
    assert local(client).json()[0]["action"] == "RUN"
    assert adapter.launches == 0
    assert client.post("/api/engine/resume").status_code == 200
    assert adapter.launches == 0
    # Resume's plan must not be blindly reused; capacity has disappeared.
    market.observations[0].available_units = 0
    app.state.engine.poll()
    assert adapter.launches == 0
    market.observations[0].available_units = 1
    app.state.engine.poll()
    assert adapter.launches == 1


@pytest.mark.parametrize("change", ["arrival", "hour", "pause"])
def test_plan_is_rechecked_after_image_preparation(tmp_path, change):
    adapter, _, app, client, job = setup(tmp_path, market_source=source(), allow_local_dispatch=True)
    original = adapter.prepare
    def changed_while_preparing():
        if change == "arrival":
            client.post("/api/jobs", json={**job, "id": "urgent", "deadlineSlot": 1})
        elif change == "hour":
            app.state.engine.clock = lambda: NOW + timedelta(hours=1)
        else:
            client.post("/api/engine/pause")
        return original()
    adapter.prepare = changed_while_preparing
    assert local(client).status_code == 200
    assert adapter.launches == 0 and app.state.executions.list() == []
    if change == "arrival":
        adapter.prepare = original
        app.state.engine.poll()
        assert adapter.launches == 1
        assert app.state.executions.list()[0].job_id == "urgent"


def test_single_local_slot_unsupported_tasks_and_unknown_capacity(tmp_path):
    market = source(capacity=None)
    adapter, _, app, client, job = setup(tmp_path, market_source=market, allow_local_dispatch=True)
    client.post("/api/jobs", json={**job, "id": "cloud", "allowedRegions": ["Frankfurt"]})
    client.post("/api/jobs", json={**job, "id": "gpu", "resourceType": "GPU", "gpuType": "A100"})
    client.post("/api/jobs", json={**job, "id": "second"})
    assert local(client).status_code == 200 and adapter.launches == 0
    assert {row["jobId"] for row in client.get("/api/decisions").json() if row["reasonCode"] == "LOCAL_TASK_UNSUPPORTED"} == {"cloud", "gpu"}
    market.observations[0].available_units = 10
    assert local(client).status_code == 200
    assert adapter.launches == 1
    assert len(app.state.executions.list()) == 1
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"  # cloud job is never routed to laptop


def test_local_mode_never_uses_a_cheaper_remote_quote(tmp_path):
    market = source()
    market.observations.append(market.observations[0].model_copy(update={"region": "Frankfurt", "price_usd_per_unit_hour": 0}))
    adapter, _, app, client, job = setup(tmp_path, market_source=market, allow_local_dispatch=True)
    # The urgent job allows both regions, with Frankfurt as its preferred origin.
    client.post("/api/jobs", json={**job, "id": "route", "deadlineSlot": 1, "allowedRegions": ["Frankfurt", "local"]})
    decisions = local(client).json()
    decision = next(row for row in decisions if row["jobId"] == "route")
    assert decision["action"] == "ROUTE" and decision["region"] == "local"
    assert adapter.launches == 1 and app.state.executions.list()[0].job_id == "route"
