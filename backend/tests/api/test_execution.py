"""Focused dispatch/lifecycle integration tests; no Docker daemon required."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.engine.forecast_bridge import EngineUnavailable

NOW = datetime(2026, 10, 24, 10, 5, tzinfo=timezone.utc)


class FakeDocker:
    def __init__(self):
        self.launches = 0
        self.observed = None
        self.fail_launch = False
        self.down = False

    def prepare(self):
        if self.down:
            raise EngineUnavailable("DOCKER_UNAVAILABLE", "offline")
        return "sha256:fixed-image"

    def launch(self, execution):
        self.launches += 1
        self.observed = dict(container_id="container-1", state="running", started_at_utc=NOW,
            completed_at_utc=None, exit_code=0, stdout="work", stderr="", stdout_truncated=False,
            stderr_truncated=False, oom=False, error=None)
        if self.fail_launch:
            raise OSError("response lost")

    def inspect(self, execution):
        if self.down:
            raise OSError("daemon offline")
        return self.observed

    def kill(self, execution):
        self.observed.update(state="exited", exit_code=137, completed_at_utc=NOW + timedelta(seconds=31))


def setup(tmp_path, **kwargs):
    adapter = FakeDocker()
    path = tmp_path / "execution.sqlite3"
    app = create_app(path, clock=lambda: NOW, execution_adapter=adapter, **kwargs)
    client = TestClient(app)
    job = dict(id="local-job", name="local", arrivalSlot=0, durationSlots=1, deadlineSlot=2,
               resourceType="CPU", resourceUnits=1, allowedRegions=["local"], dockerTaskId="cpu-hash-v1")
    assert client.post("/api/jobs", json=job).status_code == 201
    return adapter, path, app, client, job


def test_allowlist_constraints_and_preflight_do_not_mutate_job(tmp_path):
    adapter, _, _, client, job = setup(tmp_path)
    assert client.post("/api/execute/local-job", json={"command": "anything"}).status_code == 422
    for changes in [dict(dockerTaskId="arbitrary"), dict(resourceType="GPU", gpuType="A100"),
                    dict(allowedRegions=["Frankfurt"]), dict(arrivalSlot=1), dict(deadlineSlot=0)]:
        payload = {**job, **changes, "id": str(changes)}
        client.post("/api/jobs", json=payload)
        from urllib.parse import quote
        assert client.post("/api/execute/" + quote(payload["id"], safe="")).status_code == 409
    adapter.down = True
    assert client.post("/api/execute/local-job", json={}).status_code == 503
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"
    assert adapter.launches == 0


@pytest.mark.parametrize("exit_code", [0, 1])
def test_idempotent_start_terminal_accounting_and_restart(tmp_path, exit_code):
    adapter, path, app, client, _ = setup(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: client.post("/api/execute/local-job").json(), range(2)))
    assert adapter.launches == 1
    assert results[0]["id"] == results[1]["id"]
    # A second app recovers container association and logs using saved state.
    restarted = TestClient(create_app(path, clock=lambda: NOW, execution_adapter=adapter))
    adapter.observed.update(state="exited", exit_code=exit_code, completed_at_utc=NOW + timedelta(seconds=1),
                            stdout="result", stderr="failure" if exit_code else "")
    record = restarted.get("/api/executions/" + results[0]["id"]).json()
    status = "FAILED" if exit_code else "COMPLETED"
    assert record["status"] == status
    assert record["stdout"] == "result" and record["exitCode"] == exit_code
    assert restarted.get("/api/jobs").json()[0]["status"] == status
    assert restarted.post("/api/execute/local-job").json() == record
    with app.state.executions.database.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='JOB_STARTED'").fetchone()[0] == 1
    assert adapter.launches == 1


def test_uncertain_start_daemon_outage_and_capacity_preserve_claim(tmp_path):
    adapter, _, app, client, job = setup(tmp_path)
    adapter.fail_launch = True
    record = client.post("/api/execute/local-job").json()
    assert record["status"] == "RUNNING"  # start succeeded despite lost response
    client.post("/api/jobs", json={**job, "id": "second"})
    assert client.post("/api/execute/second").status_code == 409
    adapter.down = True
    record = client.get("/api/executions/" + record["id"]).json()
    assert record["status"] == "RUNNING" and record["lastMonitorError"]
    adapter.down = False
    adapter.observed = None
    record = client.get("/api/executions/" + record["id"]).json()
    assert record["status"] == "FAILED" and "missing" in record["failureReason"]
    assert adapter.launches == 1


def test_timeout_monitor_settles_even_when_scheduling_is_rejected(tmp_path):
    adapter, _, app, client, _ = setup(tmp_path)
    record = client.post("/api/execute/local-job").json()
    app.state.engine.clock = lambda: NOW + timedelta(seconds=31)
    def reject_slot(slot, origin):
        raise EngineUnavailable("TEST_SLOT_REJECTED", "Scheduling is unavailable")
    app.state.engine.market_source.validate_slot = reject_slot
    app.state.engine.poll()
    # Read stored state first: GET /executions itself monitors and could hide
    # a broken background monitor behind a passing assertion.
    assert app.state.executions.get(record["id"]).status == "FAILED"
    record = client.get("/api/executions/" + record["id"]).json()
    assert record["status"] == "FAILED" and record["timeoutRequested"]
    assert record["exitCode"] == 137
    assert client.get("/api/jobs").json()[0]["status"] == "FAILED"


def test_unconfirmed_start_is_not_retried_and_late_completion_is_counted(tmp_path):
    adapter, path, app, client, _ = setup(tmp_path)
    original = adapter.launch
    def lost_before_create(record):
        adapter.launches += 1
        raise OSError("connection lost before confirmation")
    adapter.launch = lost_before_create
    record = client.post("/api/execute/local-job").json()
    assert record["status"] == "STARTING" and record["lastMonitorError"]
    restarted = TestClient(create_app(path, clock=lambda: NOW, execution_adapter=adapter))
    assert restarted.post("/api/execute/local-job").json()["id"] == record["id"]
    assert adapter.launches == 1
    # Model a delayed observation of a container that did in fact run.
    original(None)
    adapter.observed.update(state="exited", completed_at_utc=NOW.replace(hour=12, minute=0) + timedelta(seconds=1))
    restarted.get("/api/executions/" + record["id"])
    assert restarted.get("/api/metrics?scope=LIVE").json()["missedDeadlineJobIds"] == ["local-job"]


def test_log_read_failure_does_not_hide_confirmed_exit_or_hold_capacity(tmp_path, monkeypatch):
    pytest.importorskip("docker")
    from types import SimpleNamespace
    from app.execution.docker import DockerAdapter
    _, _, app, client, _ = setup(tmp_path)
    record = client.post("/api/execute/local-job").json()
    def unavailable_logs(**kwargs):
        raise OSError("log endpoint unavailable")
    container = SimpleNamespace(id=record["containerId"], logs=unavailable_logs, attrs={
        "Config": {"Labels": {"compute.execution": record["id"]}},
        "State": {"Status": "exited", "ExitCode": 0, "StartedAt": NOW.isoformat(),
                  "FinishedAt": (NOW + timedelta(seconds=1)).isoformat()}})
    adapter = DockerAdapter()
    monkeypatch.setattr(adapter, "client", lambda: SimpleNamespace(
        containers=SimpleNamespace(get=lambda name: container), close=lambda: None))
    app.state.executions.adapter = adapter
    app.state.engine.poll()
    stored = app.state.executions.get(record["id"])
    assert stored.status == "COMPLETED" and stored.exit_code == 0
    assert stored.last_monitor_error and stored.stdout == "work"
    with app.state.executions.database.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
