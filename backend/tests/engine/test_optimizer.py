from itertools import product
import random

import pytest

from app.api.schemas import Forecast, Job, MarketSnapshot, OptimizationInput, OptimizerConfig, Reservation
from app.engine.optimizer import ConstrainedPortfolioOptimizer, OptimizationLimitError, RiskPolicy


def job(job_id="a", **changes):
    fields = dict(id=job_id, name=job_id, arrival_slot=0, duration_slots=1,
                  deadline_slot=3, resource_type="GPU", gpu_type="A100",
                  resource_units=1, allowed_regions=["west", "east"], max_budget_usd=None)
    return Job(**{**fields, **changes})


def market(region="west", price=5, capacity=1, **changes):
    fields = dict(slot=0, region=region, resource_type="GPU", gpu_type="A100",
                  price_usd_per_unit_hour=price, available_units=capacity,
                  source="test scenario", data_kind="SIMULATED")
    return MarketSnapshot(**{**fields, **changes})


def forecast(region="west", slot=1, price=1, **changes):
    fields = dict(generated_at_slot=0, target_slot=slot, region=region,
                  resource_type="GPU", gpu_type="A100", predicted_price_usd_per_unit_hour=price,
                  model_version="scenario-test")
    return Forecast(**{**fields, **changes})


def inputs(jobs=None, markets=None, forecasts=None, **changes):
    fields = dict(current_slot=0, pending_jobs=jobs if jobs is not None else [job()],
                  running_jobs=[], market=markets if markets is not None else [market()],
                  forecasts=forecasts or [], reservations=[], execution_mode="PAPER")
    return OptimizationInput(**{**fields, **changes})


def solve(request):
    return ConstrainedPortfolioOptimizer().optimize(request)


def test_wait_for_cheaper_window_and_provide_evidence():
    plan = ConstrainedPortfolioOptimizer().plan(inputs(
        forecasts=[forecast(slot=1, price=2), forecast(slot=2, price=1)]))
    decision = plan.decisions[0]
    assert (decision.action, decision.planned_start_slot, decision.projected_cost_usd) == ("WAIT", 2, 1)
    assert plan.evidence["a"].deadline_slack_slots == 0
    assert plan.evidence["a"].forecasts[0].model_version == "scenario-test"
    assert "projected" in decision.explanation
    assert plan.evidence["a"].interruption_probability is None


def test_route_and_transfer_cost_choose_different_region():
    request = inputs(markets=[market(price=5), market("east", price=1)])
    decision = solve(request)[0]
    assert (decision.action, decision.region, decision.projected_cost_usd) == ("ROUTE", "east", 1)
    request.config.transfer_cost_usd = 10
    assert solve(request)[0].action == "RUN"


def test_portfolio_search_reroutes_flexible_job_to_preserve_feasibility():
    request = inputs(
        jobs=[job("a", deadline_slot=1), job("b", deadline_slot=1, allowed_regions=["west"])],
        markets=[market(price=1), market("east", price=3)],
    )
    decisions = {row.job_id: row for row in solve(request)}
    assert decisions["a"].region == "east"
    assert decisions["b"].region == "west"
    assert sum(row.projected_cost_usd for row in decisions.values()) == 4


def test_three_jobs_cannot_start_on_two_gpus():
    request = inputs(jobs=[job(name, deadline_slot=1) for name in ["c", "b", "a"]],
                     markets=[market(capacity=2)])
    decisions = solve(request)
    assert [(row.job_id, row.action) for row in decisions] == [
        ("a", "RUN"), ("b", "RUN"), ("c", "INFEASIBLE")]


def test_future_arrival_and_nonpreemptive_multihour_cost():
    request = inputs(jobs=[job(arrival_slot=1, duration_slots=2, deadline_slot=3, resource_units=2)],
                     markets=[market(capacity=2)],
                     forecasts=[forecast(slot=1, price=2), forecast(slot=2, price=3)])
    decision = solve(request)[0]
    assert (decision.action, decision.planned_start_slot, decision.planned_end_slot) == ("WAIT", 1, 3)
    assert decision.projected_cost_usd == 10


def test_deadline_boundary_and_safety_buffer():
    request = inputs(jobs=[job(duration_slots=2, deadline_slot=2)], forecasts=[forecast()])
    assert solve(request)[0].planned_end_slot == 2
    request.config.safety_buffer_slots = 1
    assert solve(request)[0].reason_code == "DEADLINE_INFEASIBLE"


def test_budget_includes_overheads_and_respects_zero_budget():
    request = inputs(jobs=[job(deadline_slot=1, max_budget_usd=6)],
                     config=OptimizerConfig(startup_cost_usd=2))
    assert solve(request)[0].reason_code == "BUDGET_EXCEEDED"
    request.pending_jobs[0].max_budget_usd = 7
    assert solve(request)[0].projected_cost_usd == 7
    request.pending_jobs[0].max_budget_usd = 0
    assert solve(request)[0].action == "INFEASIBLE"


def test_hardware_regions_and_missing_forecast_do_not_get_invented():
    request = inputs(jobs=[job(gpu_type="H100")])
    decision = solve(request)[0]
    assert decision.reason_code == "NO_COMPATIBLE_MARKET_DATA"
    assert decision.region is None
    request = inputs(jobs=[job(duration_slots=2)], forecasts=[forecast("east")])
    decision = solve(request)[0]
    assert decision.reason_code == "FORECAST_COVERAGE_MISSING"
    assert decision.action == "WAIT"


def test_zero_capacity_and_priority_order():
    assert solve(inputs(markets=[market(capacity=0)]))[0].reason_code == "CAPACITY_UNAVAILABLE"
    request = inputs(jobs=[job("a", deadline_slot=1), job("z", deadline_slot=1, priority=10)])
    decisions = solve(request)
    assert [(row.job_id, row.action) for row in decisions] == [("z", "RUN"), ("a", "INFEASIBLE")]


def test_running_reservation_is_counted_once_and_adjacent_window_is_free():
    running = job("running", status="RUNNING", duration_slots=2, deadline_slot=3)
    reservation = Reservation(job_id="running", region="west", resource_type="GPU", gpu_type="A100",
                              resource_units=1, start_slot=0, end_slot=2)
    request = inputs(running_jobs=[running], reservations=[reservation],
                     forecasts=[forecast(slot=1), forecast(slot=2)])
    decision = solve(request)[0]
    assert (decision.job_id, decision.planned_start_slot) == ("a", 2)
    request.market[0].available_units = 2
    request.forecasts = []
    assert solve(request)[0].action == "RUN"


def test_global_resource_limit_applies_across_regions():
    request = inputs(jobs=[job("a", deadline_slot=1), job("b", deadline_slot=1)],
                     markets=[market(), market("east", price=6)],
                     config=OptimizerConfig(portfolio_resource_limit=1))
    assert [row.action for row in solve(request)] == ["RUN", "INFEASIBLE"]


def test_optional_carbon_cost_is_secondary_and_requires_data():
    request = inputs(markets=[market(carbon_kg_per_unit_hour=2)],
                     config=OptimizerConfig(carbon_price_usd_per_kg=3))
    assert solve(request)[0].projected_cost_usd == 11
    request.market[0].carbon_kg_per_unit_hour = None
    assert solve(request)[0].reason_code == "CARBON_DATA_UNAVAILABLE"
    request.config.carbon_price_usd_per_kg = 0
    assert solve(request)[0].projected_cost_usd == 5


def test_urgent_fallback_prefers_known_reliability_over_cheaper_risk():
    request = inputs(jobs=[job(deadline_slot=2)], current_slot=1,
                     markets=[market(price=1, slot=1), market("east", price=2, slot=1)],
                     forecasts=[forecast(slot=1, price=999, interruption_probability=.8),
                                forecast("east", slot=1, price=999, interruption_probability=.01)])
    plan = ConstrainedPortfolioOptimizer().plan(request)
    decision = plan.decisions[0]
    assert (decision.action, decision.region) == ("FALLBACK", "east")
    assert decision.projected_cost_usd == pytest.approx(2.02)
    assert plan.evidence["a"].cost_breakdown["expectedRecoveryUsd"] == pytest.approx(.02)
    assert plan.evidence["a"].availability_probability == 1


def test_risk_aggregates_over_occupied_hours_with_explicit_scenario_cost():
    request = inputs(jobs=[job(arrival_slot=1, duration_slots=2, deadline_slot=3)],
                     forecasts=[forecast(slot=1, price=2, availability_probability=.8, interruption_probability=.1),
                                forecast(slot=2, price=2, interruption_probability=.2)])
    plan = ConstrainedPortfolioOptimizer().plan(request)
    assert plan.evidence["a"].interruption_probability == pytest.approx(.28)
    assert plan.decisions[0].projected_cost_usd == pytest.approx(5.12)


@pytest.mark.parametrize("case", ["future_market", "forecast_market", "future_forecast", "duplicate_job",
                                 "running_without_reservation", "wrong_pending_status", "long_horizon",
                                 "conflicting_forecast", "conflicting_market", "mixed_resource_limit"])
def test_invalid_or_leaking_inputs_are_rejected(case):
    request = inputs()
    if case == "future_market":
        request.market[0].slot = 1
    elif case == "forecast_market":
        request.market[0].data_kind = "FORECAST"
    elif case == "future_forecast":
        request.forecasts = [forecast(slot=2, generated_at_slot=1)]
    elif case == "duplicate_job":
        request.pending_jobs.append(job())
    elif case == "running_without_reservation":
        request.running_jobs = [job("r", status="RUNNING")]
    elif case == "wrong_pending_status":
        request.pending_jobs[0].status = "COMPLETED"
    elif case == "long_horizon":
        request.forecasts = [forecast(slot=7)]
    elif case == "conflicting_forecast":
        request.forecasts = [forecast(), forecast(price=99)]
    elif case == "conflicting_market":
        request.market.append(market(price=99))
    else:
        request.pending_jobs.append(job("cpu", resource_type="CPU", gpu_type=None))
        request.config.portfolio_resource_limit = 2
    with pytest.raises(ValueError):
        solve(request)


def test_latest_available_forecast_vintage_and_input_order_are_deterministic():
    request = inputs(jobs=[job("b", deadline_slot=3), job("a", deadline_slot=3)], current_slot=1,
                     markets=[market(price=5, slot=1), market("east", price=5, slot=1)],
                     forecasts=[forecast(slot=2, price=100), forecast(slot=2, price=1, generated_at_slot=1),
                                forecast("east", slot=2, price=3)])
    original = request.model_dump_json()
    expected = solve(request)
    assert request.model_dump_json() == original
    assert sum(row.projected_cost_usd for row in expected) == 4
    request.pending_jobs.reverse()
    request.market.reverse()
    request.forecasts.reverse()
    assert solve(request) == expected


def test_cpu_jobs_and_search_limit_and_empty_portfolio():
    decision = solve(inputs(jobs=[job(resource_type="CPU", gpu_type=None)],
                            markets=[market(resource_type="CPU", gpu_type=None)]))[0]
    assert decision.action == "RUN"
    assert solve(inputs(jobs=[])) == []
    optimizer = ConstrainedPortfolioOptimizer(RiskPolicy(max_search_nodes=1))
    with pytest.raises(OptimizationLimitError):
        optimizer.optimize(inputs())


def test_exact_portfolio_cost_matches_independent_small_exhaustive_oracle():
    rng = random.Random(42)
    for _ in range(12):
        prices = {(region, slot): rng.randint(1, 10) for region in ["west", "east"] for slot in range(3)}
        workloads = [job(name) for name in ["a", "b", "c"]]
        request = inputs(jobs=workloads,
                         markets=[market(region, price=prices[region, 0]) for region in ["west", "east"]],
                         forecasts=[forecast(region, slot=slot, price=prices[region, slot])
                                    for region in ["west", "east"] for slot in [1, 2]])
        options = list(prices)
        oracle = min(sum(prices[choice] for choice in allocation)
                     for allocation in product(options, repeat=3) if len(set(allocation)) == 3)
        decisions = solve(request)
        assert sum(row.projected_cost_usd for row in decisions) == oracle
        assert len({(row.region, row.planned_start_slot) for row in decisions}) == 3
