from datetime import datetime, timedelta, timezone

import pytest

from app.api.schemas import JobCreate, MarketSnapshot, Reservation
from app.audit.events import EventStore
from app.database import Database
from app.engine.forecast_bridge import EngineUnavailable, PersistenceForecastProvider
from app.engine.reservations import ReservationStore
from app.engine.runtime import ExecutionOutcome, RollingScheduler
from app.jobs.store import DecisionStore, JobStore
from app.market.adapter import MemoryMarketSource


NOW = datetime(2026, 10, 24, 9, tzinfo=timezone.utc)


def add_job(database, name="a", duration=1, deadline=3):
    return JobStore(database).create(JobCreate(id=name, name=name, arrival_slot=0,
        duration_slots=duration, deadline_slot=deadline, resource_type="CPU",
        resource_units=1, allowed_regions=["west"]))


class SpyProvider(PersistenceForecastProvider):
    def __init__(self):
        self.requests = []

    def predict(self, request):
        self.requests.append(request.model_copy(deep=True))
        return super().predict(request)


class Monitor:
    outcomes = []

    def poll(self, slot):
        return list(self.outcomes)


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "runtime.sqlite3")
    source = MemoryMarketSource([MarketSnapshot(slot=0, region="west", resource_type="CPU",
        price_usd_per_unit_hour=5, available_units=1, source="test scenario", data_kind="SIMULATED")])
    provider = SpyProvider()
    engine = RollingScheduler(database, market_source=source, forecast_services={"NAIVE": provider}, clock=lambda: NOW)
    return database, source, provider, engine


def test_unchanged_ticks_do_not_repeat_predictions_or_starts(setup):
    database, _, provider, engine = setup
    add_job(database)
    engine.tick(0, execution_mode="SIMULATED")
    before = len(EventStore(database).list())
    assert engine.tick(0) is None
    assert len(provider.requests) == 1
    assert len(EventStore(database).list()) == before
    assert len(ReservationStore(database).list()) == 1


def test_failure_frees_capacity_and_replans_pending_job_in_same_slot(setup):
    database, _, provider, engine = setup
    monitor = Monitor()
    engine.monitor = monitor
    add_job(database, "a", duration=2)
    add_job(database, "b")
    plan = engine.tick(0, execution_mode="SIMULATED")
    assert [row.action for row in plan.decisions] == ["RUN", "WAIT"]
    monitor.outcomes = [ExecutionOutcome("a", "FAILED", "SIMULATED", 0, "Scenario interruption")]
    plan = engine.tick(0)
    assert plan.decisions[0].job_id == "b"
    assert plan.decisions[0].action == "RUN"
    assert [job.status for job in JobStore(database).list()] == ["FAILED", "RUNNING"]
    assert engine.tick(0) is None
    assert len(provider.requests) == 2
    assert len(ReservationStore(database).list()) == 1


def test_restart_settles_only_simulated_duration_and_does_not_duplicate(setup):
    database, source, _, engine = setup
    add_job(database)
    engine.tick(0, execution_mode="SIMULATED")
    origin = engine.state().origin_utc
    restarted = RollingScheduler(Database(database.path), market_source=source,
                                 clock=lambda: NOW + timedelta(hours=1))
    restarted.tick()
    assert restarted.state().current_slot == 1
    assert restarted.state().origin_utc == origin
    assert JobStore(database).get("a").status == "COMPLETED"
    assert ReservationStore(database).list() == []
    assert len([event for event in EventStore(database).list() if event.event_type == "JOB_STARTED"]) == 1


@pytest.mark.parametrize("outage, code", [("forecast", "FORECAST_PROVIDER_UNAVAILABLE"), ("market", "MARKET_SOURCE_FAILED")])
def test_monitoring_completion_survives_other_service_outages(setup, outage, code):
    database, _, _, engine = setup
    add_job(database)
    engine.tick(0, execution_mode="SIMULATED")
    if outage == "market":
        def offline(slot):
            raise OSError("Market feed offline")
        engine.market_source.poll = offline
    with pytest.raises(EngineUnavailable):
        engine.tick(1, forecast_mode="ML" if outage == "forecast" else "NAIVE")
    assert JobStore(database).get("a").status == "COMPLETED"
    assert ReservationStore(database).list() == []
    assert engine.state().current_slot == 1
    assert engine.state().last_error["code"] == code


def test_local_completion_is_never_inferred_from_elapsed_slots(setup):
    database, _, _, engine = setup
    add_job(database)
    reservation = Reservation(job_id="a", region="west", resource_type="CPU", resource_units=1,
                              start_slot=0, end_slot=1)
    # This constructs store state only; no actual local container runs in this test.
    JobStore(database).start("a", reservation, "LOCAL")
    with pytest.raises(ValueError, match="active reservations"):
        engine.tick(1)
    assert JobStore(database).get("a").status == "RUNNING"
    monitor = Monitor()
    monitor.outcomes = [ExecutionOutcome("a", "COMPLETED", "LOCAL", 1, "Injected monitor outcome")]
    engine.monitor = monitor
    engine.tick(1)
    assert JobStore(database).get("a").status == "COMPLETED"


def test_clock_advance_refreshes_forecast_and_deadline_pressure(setup):
    database, _, provider, engine = setup
    now = [NOW]
    engine.clock = lambda: now[0]
    add_job(database, deadline=1)
    engine.tick()
    assert engine.state().execution_mode == "PAPER"
    now[0] += timedelta(hours=1)
    plan = engine.tick()
    assert plan.decisions[0].action == "INFEASIBLE"
    assert provider.requests[-1].current_slot == 1
    assert len(provider.requests) == 2


def test_new_job_and_price_observation_trigger_forecast_refresh(setup):
    database, source, provider, engine = setup
    engine.tick(0)
    assert engine.tick(0) is None
    add_job(database)
    assert engine.tick(0).decisions
    source.observations[0].price_usd_per_unit_hour = 9
    assert engine.tick(0).decisions[0].projected_cost_usd == 9
    assert len(provider.requests) == 3
    assert provider.requests[-1].history[0].price_usd_per_unit_hour == 9


def test_observation_changes_do_not_migrate_running_jobs(setup):
    database, source, _, engine = setup
    add_job(database, duration=2)
    engine.tick(0, execution_mode="SIMULATED")
    original = ReservationStore(database).list()
    source.observations[0].available_units = 0
    assert engine.tick(0).decisions == []
    assert ReservationStore(database).list() == original
    assert JobStore(database).get("a").status == "RUNNING"


def test_bad_monitor_outcome_and_future_observation_do_not_corrupt_state(setup):
    database, source, _, engine = setup
    add_job(database)
    engine.tick(0, execution_mode="SIMULATED")
    monitor = Monitor()
    monitor.outcomes = [ExecutionOutcome("a", "COMPLETED", "SIMULATED", 2)]
    engine.monitor = monitor
    with pytest.raises(ValueError, match="invalid slot"):
        engine.tick(0)
    assert JobStore(database).get("a").status == "RUNNING"
    monitor.outcomes = []
    source.poll = lambda slot: [source.observations[0].model_copy(update={"slot": 10})]
    with pytest.raises(ValueError, match="future data"):
        engine.tick(0)
    assert len(ReservationStore(database).list()) == 1


def test_background_error_is_visible_and_provider_can_recover(setup):
    database, _, provider, engine = setup
    add_job(database)
    class Broken:
        def predict(self, request):
            raise RuntimeError("Temporary failure")
    engine.providers["NAIVE"] = Broken()
    assert engine.poll() is None
    assert engine.state().last_error["code"] == "FORECAST_PROVIDER_FAILED"
    assert DecisionStore(database).list() == []
    engine.providers["NAIVE"] = provider
    assert engine.poll().decisions
    assert engine.state().last_error is None


def test_prior_forecast_supplies_current_risk_without_replacing_observed_price(setup):
    database, source, _, engine = setup
    source.observations[0].price_usd_per_unit_hour = 1
    source.observations.append(source.observations[0].model_copy(update={"region": "east", "price_usd_per_unit_hour": 2}))
    JobStore(database).create(JobCreate(id="risk", name="risk", arrival_slot=1, duration_slots=1,
        deadline_slot=2, resource_type="CPU", resource_units=1, allowed_regions=["west", "east"]))

    class RiskProvider(PersistenceForecastProvider):
        def predict(self, request):
            rows = super().predict(request)
            for row in rows:
                row.interruption_probability = .8 if row.region == "west" else .01
                row.availability_probability = 1
                row.model_version = "scenario-risk-test"
            return rows

    engine.providers["ML"] = RiskProvider()
    engine.tick(0, forecast_mode="ML")
    plan = engine.tick(1)
    assert plan.decisions[0].action == "FALLBACK"
    assert plan.decisions[0].region == "east"
    assert plan.decisions[0].projected_cost_usd == pytest.approx(2.02)
    assert plan.evidence["risk"].forecasts[0].generated_at_slot == 0


@pytest.mark.parametrize("stage", ["market", "monitor", "forecast"])
def test_external_calls_do_not_hold_writer_lock_and_new_jobs_are_planned(setup, stage):
    import sqlite3
    database, source, _, engine = setup
    add_job(database)

    def external_work():
        # Fail promptly if a scheduler writer lock is held, then exercise the
        # actual store path while this external call is still in progress.
        with sqlite3.connect(database.path, timeout=.05) as connection:
            connection.execute("BEGIN IMMEDIATE")
        add_job(database, "late")

    if stage == "market":
        original = source.poll
        def poll(slot):
            external_work()
            return original(slot)
        source.poll = poll
    elif stage == "monitor":
        class CallbackMonitor:
            def poll(self, slot):
                external_work()
                return []
        engine.monitor = CallbackMonitor()
    else:
        class CallbackProvider(PersistenceForecastProvider):
            def predict(self, request):
                external_work()
                return super().predict(request)
        engine.providers["NAIVE"] = CallbackProvider()
    assert {row.job_id for row in engine.tick(0).decisions} == {"a", "late"}


def test_changed_market_during_inference_cannot_commit_stale_plan(setup):
    database, _, _, engine = setup
    add_job(database)
    class RevisedMarket(PersistenceForecastProvider):
        def predict(self, request):
            with database.transaction() as connection:
                row = connection.execute("SELECT series_key, payload FROM market_observations").fetchone()
                revised = MarketSnapshot.model_validate_json(row["payload"])
                revised.price_usd_per_unit_hour = 99
                connection.execute("UPDATE market_observations SET payload = ? WHERE series_key = ?",
                                   (revised.model_dump_json(by_alias=True), row["series_key"]))
            return super().predict(request)
    engine.providers["NAIVE"] = RevisedMarket()
    with pytest.raises(ValueError, match="changed during forecasting"):
        engine.tick(0, execution_mode="SIMULATED")
    assert DecisionStore(database).list() == []
    assert JobStore(database).get("a").status == "PENDING"
