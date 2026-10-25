from copy import deepcopy

import pytest

from app.engine.forecast_benchmark import Allocation, Workload, exact_plan, replay


def job(name="a", *, duration=1, deadline=2, arrival=0):
    return Workload(name, arrival, duration, deadline, ("pool",), 1)


def test_exact_plan_shares_capacity_and_allows_completion_at_deadline():
    quotes = {("pool", 0): 2., ("pool", 1): 1.}
    plans = exact_plan([job("a"), job("b")], [], quotes, {"pool": 1}, 0)
    assert len(plans) == 2
    assert sorted(p.start for p in plans) == [0, 1]
    assert sum(p.projected_cost for p in plans) == 3
    assert all(p.end <= 2 for p in plans)
    assert exact_plan([job("a"), job("b")], [], quotes, {"pool": 1}, 0) == plans
    together = exact_plan([job("a"), job("b")], [], quotes, {"pool": 2}, 0)
    assert [p.start for p in together] == [1, 1]


def test_running_capacity_cannot_be_duplicated_or_migrated():
    running = [Allocation("running", "pool", 0, 1, 1, 2.)]
    plans = exact_plan([job()], running, {("pool", 0): 2., ("pool", 1): 1.}, {"pool": 1}, 0)
    assert plans[0].start == 1
    with pytest.raises(ValueError, match="distinct"):
        exact_plan([job("running")], running, {}, {"pool": 1}, 0)
    with pytest.raises(ValueError, match="future"):
        exact_plan([job(arrival=1)], [], {}, {"pool": 1}, 0)


def test_waiting_uses_quotes_only_and_never_extends_missing_coverage():
    quotes = {("pool", 0): 3., ("pool", 1): 2., ("pool", 2): 1.}
    assert exact_plan([job(deadline=3)], [], quotes, {"pool": 1}, 0)[0].start == 2
    del quotes["pool", 2]
    assert exact_plan([job(deadline=3)], [], quotes, {"pool": 1}, 0)[0].start == 1
    assert exact_plan([job(duration=2)], [], {("pool", 0): 1.}, {"pool": 1}, 0) == []


def test_identical_forecast_inputs_produce_identical_independent_policy_outcomes():
    jobs = [job("a", deadline=4), job("b", duration=2, deadline=4)]
    prices = {t: 1.+t/10 for t in range(6)}
    observed_calls = []

    def observed(t):
        observed_calls.append(t)
        return {"pool": prices[t]}

    def predicted(t):
        return {("pool", target): prices[t] for target in range(t+1, t+7)}

    first = replay(jobs, ["pool"], {"pool": 1}, observed, predicted, 0, 6, "OPTIMIZER_WITH_NAIVE_FORECAST")
    assert observed_calls == list(range(6))
    observed_calls.clear()
    second = replay(jobs, ["pool"], {"pool": 1}, observed, predicted, 0, 6, "OPTIMIZER_WITH_ML")
    a, b = deepcopy(first), deepcopy(second)
    del a["strategy"], b["strategy"]
    assert a == b
    assert first["completedJobs"] == 2
    assert first["missedDeadlines"] == first["unfinishedJobs"] == 0
    assert len(first["executions"]) == 2


@pytest.mark.parametrize("strategy", ["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"])
def test_failed_admission_is_counted_and_not_hidden_as_zero_cost_success(strategy):
    result = replay([job(duration=2, deadline=2)], ["pool"], {"pool": 0},
        lambda t: {"pool": 1.}, lambda t: {("pool", s): 1. for s in range(t+1, t+7)}, 0, 3, strategy)
    assert result["completedJobs"] == 0
    assert result["missedDeadlines"] == 1
    assert result["jobs"][0]["status"] == "MISSED"
    assert result["unfinishedJobs"] == 0


def test_running_at_end_is_reported_unfinished_and_billed_only_for_observed_slots():
    result = replay([job(duration=3, deadline=4)], ["pool"], {"pool": 1},
                    lambda t: {"pool": 2.}, lambda t: {}, 0, 1, "FIFO")
    assert result["unfinishedJobs"] == 1
    assert result["completedJobs"] == result["missedDeadlines"] == 0
    assert result["totalSpendUsd"] == 2.
