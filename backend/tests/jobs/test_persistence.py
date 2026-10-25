from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import Decision, JobCreate, Reservation
from app.audit.events import EventStore
from app.database import Database
from app.engine.reservations import ReservationStore
from app.jobs.store import DecisionStore, JobStore
from app.main import create_app


@pytest.fixture
def database(tmp_path):
    return Database(tmp_path / "engine.sqlite3")


@pytest.fixture
def payload():
    return JobCreate(id="job", name="Work", arrival_slot=0, duration_slots=2,
                     deadline_slot=4, resource_type="GPU", gpu_type="A100",
                     resource_units=1, allowed_regions=["eu-west-1"], max_budget_usd=10)


@pytest.mark.parametrize('gpu,accepted', [('A100', True), ('H100', True), ('T4', False)])
def test_job_store_preserves_gpu_alternatives_when_recording_a_start(database, gpu, accepted):
    store = JobStore(database)
    job = JobCreate(id='flex', name='Flexible', arrival_slot=0, duration_slots=1,
        deadline_slot=2, resource_type='GPU', resource_units=1,
        allowed_gpu_types=['A100', 'H100'], allowed_regions=['eu-west-1'])
    store.create(job)
    allocation = Reservation(job_id='flex', region='eu-west-1', resource_type='GPU',
        gpu_type=gpu, resource_units=1, start_slot=0, end_slot=1)
    if accepted:
        assert store.start('flex', allocation, 'SIMULATED').status == 'RUNNING'
        assert store.get('flex').allowed_gpu_types == ['A100', 'H100']
    else:
        with pytest.raises(ValueError, match='requirements'):
            store.start('flex', allocation, 'SIMULATED')
        assert store.get('flex').status == 'PENDING'


@pytest.fixture
def reservation():
    return Reservation(job_id="job", region="eu-west-1", resource_type="GPU",
                       gpu_type="A100", resource_units=1, start_slot=0, end_slot=2)


def make_decision():
    return Decision(job_id="job", decided_at_slot=0, action="WAIT",
                    region="eu-west-1", planned_start_slot=1, planned_end_slot=3,
                    projected_cost_usd=2, reason_code="TEST", explanation="Test fixture",
                    execution_mode="SIMULATED")


def test_restart_preserves_all_state(database, payload, reservation):
    store = JobStore(database)
    store.create(payload)
    decision = make_decision()
    DecisionStore(database).record(decision)
    store.start(payload.id, reservation, "SIMULATED")

    # A fresh interpreter proves persistence independent of process memory.
    script = (
        "import json, sys; from app.database import Database; "
        "from app.jobs.store import JobStore, DecisionStore; "
        "from app.engine.reservations import ReservationStore; "
        "from app.audit.events import EventStore; db=Database(sys.argv[1]); "
        "print(json.dumps([JobStore(db).get('job').status, "
        "len(DecisionStore(db).list()), len(ReservationStore(db).list()), "
        "len(EventStore(db).list())]))"
    )
    result = subprocess.run([sys.executable, "-c", script, str(database.path)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ["RUNNING", 1, 1, 3]
    client = TestClient(create_app(database.path))
    assert client.get("/api/jobs").json()[0]["status"] == "RUNNING"
    assert client.get("/api/decisions").json() == [decision.model_dump(mode="json", by_alias=True)]
    events = EventStore(database).list()
    assert events[0].execution_mode is None
    assert events[-1].execution_mode == "SIMULATED"
    assert all(event.occurred_at_utc.utcoffset().total_seconds() == 0 for event in events)


@pytest.mark.parametrize("final_status", ["COMPLETED", "FAILED"])
def test_terminal_transition_releases_capacity(database, payload, reservation, final_status):
    store = JobStore(database)
    store.create(payload)
    store.start(payload.id, reservation, "SIMULATED")
    reservations = ReservationStore(database)
    assert reservations.overlapping(1, 2) == [reservation]
    assert reservations.overlapping(2, 3) == []
    store.transition(payload.id, final_status, reason="Test outcome")
    assert JobStore(Database(database.path)).get(payload.id).status == final_status
    assert reservations.list() == []
    assert EventStore(database).list()[-1].payload["reason"] == "Test outcome"
    with pytest.raises(ValueError):
        store.start(payload.id, reservation, "SIMULATED")


def test_invalid_transitions_and_duplicate_ids_leave_state_intact(database, payload, reservation):
    store = JobStore(database)
    store.create(payload)
    for status in ["RUNNING", "COMPLETED", "FAILED", "PENDING", "INVALID"]:
        with pytest.raises(ValueError):
            store.transition(payload.id, status)
    with pytest.raises(ValueError, match="already exists"):
        store.create(payload)
    with pytest.raises(ValueError):
        store.start(payload.id, reservation, "PAPER")
    assert store.get(payload.id).status == "PENDING"
    assert len(EventStore(database).list()) == 1
    store.transition(payload.id, "INFEASIBLE", reason="Deadline cannot be met")
    with pytest.raises(ValueError):
        store.transition(payload.id, "PENDING")


@pytest.mark.parametrize("changes", [
    {"job_id": "other"}, {"region": "other"}, {"resource_type": "CPU"},
    {"gpu_type": "H100"}, {"resource_units": 2},
    {"start_slot": 0, "end_slot": 1}, {"start_slot": 3, "end_slot": 5},
])
def test_invalid_reservation_cannot_partially_start(database, payload, reservation, changes):
    store = JobStore(database)
    store.create(payload)
    invalid = Reservation.model_validate({**reservation.model_dump(), **changes})
    with pytest.raises(ValueError):
        store.start(payload.id, invalid, "SIMULATED")
    assert store.get(payload.id).status == "PENDING"
    assert ReservationStore(database).list() == []
    assert len(EventStore(database).list()) == 1


@pytest.mark.parametrize("operation", ["create", "decision", "start", "finish"])
def test_audit_failure_rolls_back_entire_mutation(database, payload, reservation, monkeypatch, operation):
    store = JobStore(database)
    if operation != "create":
        store.create(payload)
    if operation == "finish":
        store.start(payload.id, reservation, "SIMULATED")
    before_jobs = store.list()
    before_events = EventStore(database).list()
    before_reservations = ReservationStore(database).list()

    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr("app.jobs.store.append_event", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        if operation == "create":
            store.create(payload)
        elif operation == "decision":
            DecisionStore(database).record(make_decision())
        elif operation == "start":
            store.start(payload.id, reservation, "SIMULATED")
        else:
            store.transition(payload.id, "COMPLETED")
    assert store.list() == before_jobs
    assert EventStore(database).list() == before_events
    assert ReservationStore(database).list() == before_reservations
    assert DecisionStore(database).list() == []


def test_concurrent_starts_only_commit_once(database, payload, reservation):
    JobStore(database).create(payload)

    def start(_):
        try:
            JobStore(Database(database.path)).start(payload.id, reservation, "SIMULATED")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(start, range(2))) == [False, True]
    assert len(ReservationStore(database).list()) == 1
    assert len(EventStore(database).list()) == 2


def test_concurrent_creation_and_missing_references(database, payload):
    def create(_):
        try:
            JobStore(Database(database.path)).create(payload)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create, range(2))) == [False, True]
    with pytest.raises(KeyError):
        JobStore(database).get("unknown")
    missing = make_decision().model_copy(update={"job_id": "unknown"})
    with pytest.raises(KeyError):
        DecisionStore(database).record(missing)
    assert DecisionStore(database).list() == []
    assert len(EventStore(database).list()) == 1
