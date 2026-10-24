from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api.schemas import JobCreate, MarketSnapshot
from app.audit.events import EventStore
from app.database import Database
from app.engine.optimizer import ConstrainedPortfolioOptimizer, OptimizationLimitError, RiskPolicy
from app.engine.reservations import ReservationStore
from app.engine.scheduling import SchedulingService
from app.jobs.store import DecisionStore, JobStore


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "schedule.sqlite3")
    for name in ["a", "b"]:
        JobStore(database).create(JobCreate(
            id=name, name=name, arrival_slot=0, duration_slots=1, deadline_slot=1,
            resource_type="GPU", gpu_type="A100", resource_units=1, allowed_regions=["west"]))
    return database


def run(database, mode="SIMULATED", optimizer=None):
    market = MarketSnapshot(slot=0, region="west", resource_type="GPU", gpu_type="A100",
                            price_usd_per_unit_hour=1, available_units=1,
                            source="test scenario", data_kind="SIMULATED")
    return SchedulingService(database, optimizer).run(current_slot=0, market=[market],
                                                      forecasts=[], execution_mode=mode)


def test_paper_persists_decisions_without_starting_jobs(database):
    plan = run(database, "PAPER")
    assert DecisionStore(Database(database.path)).list() == plan.decisions
    assert [job.status for job in JobStore(database).list()] == ["PENDING", "PENDING"]
    assert ReservationStore(database).list() == []


def test_concurrent_scheduling_uses_fresh_state_and_never_overbooks(database):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run(database), range(2)))
    assert [job.status for job in JobStore(database).list()] == ["RUNNING", "INFEASIBLE"]
    assert len(ReservationStore(database).list()) == 1
    starts = [event for event in EventStore(database).list() if event.event_type == "JOB_STARTED"]
    assert len(starts) == 1
    assert starts[0].execution_mode == "SIMULATED"


def test_mid_commit_failure_rolls_back_whole_plan(database, monkeypatch):
    from app.engine import scheduling
    original = scheduling.append_event

    def fail_second_job(connection, event_type, job_id, *args):
        if job_id == "b":
            raise RuntimeError("Injected persistence failure")
        return original(connection, event_type, job_id, *args)

    monkeypatch.setattr(scheduling, "append_event", fail_second_job)
    with pytest.raises(RuntimeError):
        run(database)
    assert [job.status for job in JobStore(database).list()] == ["PENDING", "PENDING"]
    assert DecisionStore(database).list() == []
    assert ReservationStore(database).list() == []
    assert len(EventStore(database).list()) == 2


def test_search_limit_and_local_mode_do_not_mutate_state(database):
    with pytest.raises(ValueError, match="execution adapter"):
        run(database, "LOCAL")
    optimizer = ConstrainedPortfolioOptimizer(RiskPolicy(max_search_nodes=1))
    with pytest.raises(OptimizationLimitError):
        run(database, optimizer=optimizer)
    assert DecisionStore(database).list() == []
    assert ReservationStore(database).list() == []


def test_future_wait_plans_remain_tentative(database):
    from app.api.schemas import Forecast
    # Give both jobs enough deadline slack for a future slot, then make it cheap.
    other = Database(database.path.parent / "wait.sqlite3")
    JobStore(other).create(JobCreate(id="future", name="future", arrival_slot=0,
                                    duration_slots=1, deadline_slot=2, resource_type="CPU",
                                    resource_units=1, allowed_regions=["west"]))
    plan = SchedulingService(other).run(current_slot=0, market=[MarketSnapshot(
        slot=0, region="west", resource_type="CPU", price_usd_per_unit_hour=10,
        available_units=1, source="test scenario", data_kind="SIMULATED")], forecasts=[Forecast(
            generated_at_slot=0, target_slot=1, region="west", resource_type="CPU",
            predicted_price_usd_per_unit_hour=1, model_version="scenario-test")], execution_mode="SIMULATED")
    assert plan.decisions[0].action == "WAIT"
    assert JobStore(other).get("future").status == "PENDING"
    assert ReservationStore(other).list() == []
