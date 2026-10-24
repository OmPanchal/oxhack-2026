from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.replay_schemas import ReplayScenario, ReplayShockRequest
from app.api.schemas import JobCreate, MarketSnapshot, OptimizerConfig
from app.database import Database
from app.engine.forecast_bridge import PersistenceForecastProvider
from app.engine.simulator import ReplayService
from app.jobs.store import JobStore


class TestProvider(PersistenceForecastProvider):
    __test__ = False

    def predict(self, request):
        rows = super().predict(request)
        for row in rows:
            row.model_version = "test-provider-not-trained-ml"
        return rows


def job(name="a", **changes):
    return JobCreate(**{**dict(id=name, name=name, arrival_slot=0, duration_slots=1,
        deadline_slot=4, resource_type="CPU", resource_units=1, allowed_regions=["a", "b"]), **changes})


def scenario(jobs=None, prices=None, capacity=1, end=5, interruption=0):
    prices = prices or {"a": [5] * end}
    return ReplayScenario(id="test", description="SIMULATED unit-test scenario",
        origin_utc=datetime(2000, 1, 1, tzinfo=timezone.utc), end_slot=end,
        jobs=jobs if jobs is not None else [job()], interruption_probability=interruption,
        market=[MarketSnapshot(slot=slot, region=region, resource_type="CPU", price_usd_per_unit_hour=price,
            available_units=capacity, carbon_kg_per_unit_hour=.1, source="test scenario", data_kind="SIMULATED")
            for region, values in prices.items() for slot, price in enumerate(values)])


def service(tmp_path, definition=None, ml=True, config=None):
    definition = definition or scenario()
    replay = ReplayService(Database(tmp_path / "replay.sqlite3"), scenarios={"test": definition},
        forecast_services={"ML": TestProvider()} if ml else None, config=config)
    replay.reset("test", seed=42)
    return replay


def test_fifo_and_cheapest_now_use_distinct_stable_region_rules(tmp_path):
    replay = service(tmp_path, scenario(prices={"a": [5] * 5, "b": [1] * 5}))
    state = replay.step()
    fifo, cheapest, naive, ml = state.strategy_states
    assert fifo.decisions[0].region == "a"
    assert cheapest.decisions[0].region == naive.decisions[0].region == ml.decisions[0].region == "b"
    assert fifo.metrics.total_spend_usd == 5
    assert cheapest.metrics.total_spend_usd == 1
    assert all(run.metrics.completed_jobs == 1 for run in state.strategy_states)
    assert all(row.slot == 0 for row in state.observed_market)


def test_four_states_are_independent_and_workload_arrivals_are_identical(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job("future", arrival_slot=2)]))
    early = replay.step(2)
    assert all(run.jobs == [] for run in early.strategy_states)
    state = replay.step()
    assert all([item.id for item in run.jobs] == ["future"] for run in state.strategy_states)
    state.strategy_states[0].jobs[0].name = "tampered-client-copy"
    assert replay.state().strategy_states[0].jobs[0].name == "future"
    assert state.strategy_states[1].jobs[0].name == "future"


def test_all_policies_share_interruptions_and_keep_spend_before_failure(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=3, deadline_slot=5)]))
    replay.shock(ReplayShockRequest(kind="INTERRUPTION", slot=1, region="a", magnitude=1))
    state = replay.step(5)
    for run in state.strategy_states:
        assert run.metrics.failed_jobs == 1
        assert run.metrics.completed_jobs == 0
        assert run.metrics.total_spend_usd == 5
        assert run.metrics.missed_deadlines == 1
        assert run.metrics.recovery_cost_usd == 0
        assert run.outcomes[0].reason == "SIMULATED_INTERRUPTION"
        assert run.reservations == []


def test_capacity_loss_has_stable_survivors_and_no_overbooking(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job("a", duration_slots=3), job("b", duration_slots=3)], capacity=2))
    replay.shock(ReplayShockRequest(kind="CAPACITY_SHORTAGE", slot=1, region="a", magnitude=1))
    state = replay.step(5)
    for run in state.strategy_states:
        assert run.jobs[0].status == "COMPLETED"
        assert run.jobs[1].status == "FAILED"
        assert run.metrics.total_spend_usd == 20
        assert run.outcomes[0].reason == "REALIZED_CAPACITY_LOSS"


def test_realized_budget_spike_never_overspends(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=3, max_budget_usd=4)],
                                      prices={"a": [1, 1, 10, 1, 1]}))
    state = replay.step(5)
    for run in state.strategy_states:
        assert run.metrics.total_spend_usd == 2
        assert run.metrics.failed_jobs == 1
        assert run.outcomes[0].reason == "REALIZED_BUDGET_EXCEEDED"


def test_realized_charges_include_overheads_and_optional_carbon(tmp_path):
    config = OptimizerConfig(startup_cost_usd=2, transfer_cost_usd=1, carbon_price_usd_per_kg=1)
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=2)],
        prices={"a": [3] * 5, "b": [1] * 5}), config=config)
    run = replay.step(5).strategy_states[1]
    assert run.metrics.compute_spend_usd == 2
    assert run.metrics.startup_cost_usd == 2
    assert run.metrics.transfer_cost_usd == 1
    assert run.metrics.carbon_cost_usd == pytest.approx(.2)
    assert run.metrics.total_spend_usd == pytest.approx(5.2)


def test_completion_at_deadline_and_unfinished_work_are_counted(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=2, deadline_slot=2)], end=2))
    assert all(run.metrics.missed_deadlines == 0 for run in replay.step(2).strategy_states)
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=5, deadline_slot=6)], end=2))
    for run in replay.step(2).strategy_states:
        assert run.metrics.running_jobs == run.metrics.unfinished_jobs == 1
        assert run.metrics.completed_jobs == 0
        assert run.metrics.total_spend_usd == 10


def test_job_arrival_and_deadline_pressure_apply_to_every_policy(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=3, deadline_slot=5)]))
    replay.shock(ReplayShockRequest(kind="DEADLINE_PRESSURE", slot=1, job_id="a", magnitude=4))
    replay.shock(ReplayShockRequest(kind="JOB_ARRIVAL", slot=2, job=job("new", arrival_slot=2, deadline_slot=4)))
    state = replay.step(5)
    for run in state.strategy_states:
        assert [(item.id, item.status) for item in run.jobs] == [("a", "FAILED"), ("new", "COMPLETED")]
        assert run.metrics.missed_deadlines == 1


def test_price_shocks_are_simulated_and_visible_only_when_reached(tmp_path):
    replay = service(tmp_path, scenario(jobs=[]))
    replay.shock(ReplayShockRequest(kind="PRICE_SPIKE", slot=1, region="a", magnitude=3, duration_slots=2))
    state = replay.step()
    assert [row.price_usd_per_unit_hour for row in state.observed_market] == [5]
    state = replay.step(3)
    assert [row.price_usd_per_unit_hour for row in state.observed_market] == [5, 15, 15, 5]
    assert all(row.data_kind == "SIMULATED" for row in state.observed_market)


def test_reset_batch_steps_restart_and_seed_are_reproducible(tmp_path):
    definition = scenario(jobs=[job(duration_slots=3)], interruption=.25)
    replay = service(tmp_path, definition)
    replay.shock(ReplayShockRequest(kind="PRICE_SPIKE", slot=2, magnitude=2))
    expected = replay.step(5).model_dump(mode="json")
    replay.reset("test", 42)
    replay.shock(ReplayShockRequest(kind="PRICE_SPIKE", slot=2, magnitude=2))
    replay.step()
    restarted = ReplayService(replay.database, scenarios={"test": definition}, forecast_services={"ML": TestProvider()})
    for _ in range(4):
        actual = restarted.step()
    assert actual.model_dump(mode="json") == expected
    assert restarted.step().model_dump(mode="json") == expected


def test_seeded_world_does_not_depend_on_policy_or_forecast_calls(tmp_path):
    replay = service(tmp_path, scenario(jobs=[], end=12, interruption=.5))
    first = replay.step(12).observed_market
    replay.reset("test", seed=7)
    second = replay.step(12).observed_market
    assert [row.available_units for row in first] != [row.available_units for row in second]


def test_missing_ml_is_disclosed_and_does_not_fake_a_fourth_result(tmp_path):
    replay = service(tmp_path, ml=False)
    state = replay.step(5)
    assert all(run.metrics.completed_jobs == 1 for run in state.strategy_states[:3])
    ml = state.strategy_states[-1]
    assert ml.status == "UNAVAILABLE"
    assert ml.decisions == ml.forecasts == []
    assert ml.metrics.completed_jobs == 0
    assert ml.metrics.infeasible_jobs == ml.metrics.missed_deadlines == 1


def test_policy_inputs_never_contain_future_observations(tmp_path):
    class RecordingProvider(TestProvider):
        requests = []
        def predict(self, request):
            self.requests.append(request.model_copy(deep=True))
            return super().predict(request)
    definition = scenario(jobs=[], prices={"a": [1, 2, 999, 4, 5]})
    replay = ReplayService(Database(tmp_path / "history.sqlite3"), scenarios={"test": definition},
        forecast_services={"NAIVE": RecordingProvider(), "ML": RecordingProvider()})
    replay.reset("test")
    replay.step(2)
    for provider in replay.providers.values():
        for request in provider.requests:
            assert all(row.slot <= request.current_slot for row in request.history)
            assert all(row.price_usd_per_unit_hour != 999 for row in request.history)


def test_provider_failure_is_explicit_without_hiding_running_work(tmp_path):
    class BrokenAfterStart(TestProvider):
        def predict(self, request):
            if request.current_slot:
                raise RuntimeError("Provider offline")
            return super().predict(request)
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=3)]))
    replay.providers["ML"] = BrokenAfterStart()
    run = replay.step(5).strategy_states[-1]
    assert run.status == "ERROR"
    assert "Provider offline" in run.error
    assert run.metrics.completed_jobs == 1
    assert run.metrics.total_spend_usd == 15


def test_replay_never_mutates_live_jobs_or_decisions(tmp_path):
    replay = service(tmp_path)
    JobStore(replay.database).create(job("live"))
    replay.step(5)
    assert JobStore(replay.database).get("live").status == "PENDING"
    with replay.database.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0


def test_step_failure_rolls_back_the_whole_requested_batch(tmp_path, monkeypatch):
    replay = service(tmp_path)
    original = replay._interval
    before = replay.state()
    def fail_second(session):
        if session.current_slot == 1:
            raise RuntimeError("Injected interval failure")
        original(session)
    monkeypatch.setattr(replay, "_interval", fail_second)
    with pytest.raises(RuntimeError):
        replay.step(2)
    assert replay.state() == before


@pytest.mark.parametrize("payload", [
    dict(kind="INTERRUPTION", slot=0, magnitude=2),
    dict(kind="CAPACITY_SHORTAGE", slot=0, magnitude=.5),
    dict(kind="DEADLINE_PRESSURE", slot=0),
    dict(kind="JOB_ARRIVAL", slot=0),
    dict(kind="PRICE_SPIKE", slot=0, job_id="a"),
])
def test_invalid_shock_payloads_rejected(payload):
    with pytest.raises(ValidationError):
        ReplayShockRequest(**payload)


def test_shock_references_and_retroactive_events_are_rejected(tmp_path):
    replay = service(tmp_path)
    for payload in [ReplayShockRequest(kind="PRICE_SPIKE", slot=0, region="missing"),
                    ReplayShockRequest(kind="DEADLINE_PRESSURE", slot=0, job_id="missing"),
                    ReplayShockRequest(kind="JOB_ARRIVAL", slot=0, job=job()),
                    ReplayShockRequest(kind="PRICE_SPIKE", slot=4, duration_slots=2)]:
        with pytest.raises(ValueError):
            replay.shock(payload)
    replay.step()
    with pytest.raises(ValueError):
        replay.shock(ReplayShockRequest(kind="PRICE_SPIKE", slot=0))
    assert replay.state().events == []


def test_dense_realized_market_and_utc_origin_required():
    valid = scenario()
    with pytest.raises(ValidationError):
        ReplayScenario.model_validate({**valid.model_dump(), "market": valid.market[:-1]})
    with pytest.raises(ValidationError):
        ReplayScenario.model_validate({**valid.model_dump(), "origin_utc": datetime(2000, 1, 1)})
    valid.market[0].available_units = None
    with pytest.raises(ValidationError):
        ReplayScenario.model_validate(valid.model_dump())


def test_changed_policy_configuration_requires_reset(tmp_path):
    replay = service(tmp_path)
    replay.step()
    changed = ReplayService(replay.database, scenarios={"test": scenario()},
                            config=OptimizerConfig(startup_cost_usd=10))
    before = replay.state()
    with pytest.raises(ValueError, match="configuration changed"):
        changed.step()
    assert replay.state() == before


def test_model_version_change_disables_comparison_instead_of_silently_mixing_models(tmp_path):
    class ChangingVersion(TestProvider):
        def predict(self, request):
            rows = super().predict(request)
            for row in rows:
                row.model_version = f"test-version-{request.current_slot}"
            return rows
    replay = service(tmp_path, scenario(jobs=[]))
    replay.providers["ML"] = ChangingVersion()
    run = replay.step(2).strategy_states[-1]
    assert run.status == "ERROR"
    assert "versions changed" in run.error


@pytest.mark.parametrize("edit", ["shock", "reset"])
def test_replay_does_not_lock_live_database_or_overwrite_concurrent_edit(tmp_path, edit):
    replay = service(tmp_path)
    other = ReplayService(replay.database, scenarios={"test": scenario()}, forecast_services={"ML": TestProvider()})
    class ConcurrentEdit(TestProvider):
        def predict(self, request):
            if edit == "shock":
                other.shock(ReplayShockRequest(kind="PRICE_SPIKE", slot=0, magnitude=2))
            else:
                other.reset("test", 42)
            return super().predict(request)
    replay.providers["ML"] = ConcurrentEdit()
    with pytest.raises(ValueError, match="changed while stepping"):
        replay.step()
    state = replay.state()
    assert state.current_slot == 0
    assert len(state.events) == (1 if edit == "shock" else 0)
    assert all(run.charges == [] for run in state.strategy_states)


def test_fractional_hourly_cost_does_not_falsely_exceed_exact_budget(tmp_path):
    replay = service(tmp_path, scenario(jobs=[job(duration_slots=3, deadline_slot=3, max_budget_usd=.3)],
                                      prices={"a": [.1] * 5}))
    for run in replay.step(3).strategy_states:
        assert run.metrics.completed_jobs == 1
        assert run.metrics.total_spend_usd == pytest.approx(.3)
