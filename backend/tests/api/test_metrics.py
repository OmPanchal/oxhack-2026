from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.api.metrics_schemas import ModelEvaluation
from app.api.replay_schemas import ReplayScenario, ReplayShockRequest
from app.api.schemas import JobCreate, MarketSnapshot, OptimizerConfig
from app.engine.forecast_bridge import PersistenceForecastProvider
from app.engine.runtime import ExecutionOutcome
from app.main import create_app
from app.market.adapter import MemoryMarketSource

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


class ScenarioProvider(PersistenceForecastProvider):
    def __init__(self, cheap_future=False):
        self.cheap_future = cheap_future

    def predict(self, request):
        rows = super().predict(request)
        for row in rows:
            row.model_version = "test-provider-not-trained-ml"
            if self.cheap_future:
                row.predicted_price_usd_per_unit_hour = .1
        return rows


def job(name="a", **changes):
    return JobCreate(**{**dict(id=name, name=name, arrival_slot=0, duration_slots=1,
        deadline_slot=3, resource_type="CPU", resource_units=1, allowed_regions=["a", "b"]), **changes})


def app_with_replay(tmp_path, *, jobs=None, prices=None, config=None, provider=True, end=3):
    prices = prices or {"a": [5] * end}
    scenario = ReplayScenario(id="test", description="SIMULATED accounting checks", origin_utc=NOW,
        end_slot=end, jobs=jobs if jobs is not None else [job()],
        market=[MarketSnapshot(slot=slot, region=region, resource_type="CPU", available_units=3,
            price_usd_per_unit_hour=price, carbon_kg_per_unit_hour=.1,
            source="unit-test scenario", data_kind="SIMULATED")
            for region, values in prices.items() for slot, price in enumerate(values)])
    model = ScenarioProvider() if provider is True else provider
    app = create_app(tmp_path / "metrics.sqlite3", replay_scenarios={"test": scenario}, clock=lambda: NOW,
        optimizer_config=config, forecast_services={"ML": model} if model else None)
    app.state.replay.reset("test")
    return app, TestClient(app)


def comparison(body, strategy="OPTIMIZER_WITH_ML", baseline="FIFO"):
    return next(row for row in body["comparisons"] if row["strategy"] == strategy and row["baseline"] == baseline)


def test_uninitialized_and_unavailable_metrics_do_not_fabricate_results(tmp_path):
    client = TestClient(create_app(tmp_path / "empty.sqlite3"))
    response = client.post("/api/optimize", json={"currentSlot": 0})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "MARKET_DATA_UNAVAILABLE"
    assert client.post("/api/execute/unknown").status_code == 404
    assert client.get("/api/replay/state").json()["initialized"] is False
    body = client.get("/api/metrics").json()
    assert body["status"] == "NOT_INITIALIZED"
    assert body["strategies"] == body["comparisons"] == []
    report = client.get("/api/models/metrics").json()
    assert report["status"] == "UNAVAILABLE"
    assert report["evaluation"] is report["maeImprovementPercent"] is None
    live = client.get("/api/metrics?scope=LIVE").json()
    assert live["costBasis"] == "PROJECTED"
    assert live["realizedSpendUsd"] is live["realizedSavingsUsd"] is None


def test_known_ledger_costs_and_policy_savings_match_hand_calculation(tmp_path):
    app, client = app_with_replay(tmp_path, jobs=[job(duration_slots=2, resource_units=2)],
        prices={"a": [3] * 3, "b": [1] * 3},
        config=OptimizerConfig(startup_cost_usd=.25, transfer_cost_usd=.5, carbon_price_usd_per_kg=2))
    app.state.replay.step(3)
    response = client.get("/api/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["costBasis"] == "SIMULATED_REALIZED"
    assert body["executionMode"] == "SIMULATED"
    assert body["status"] == "COMPLETED"
    fifo, cheapest, naive, ml = body["strategies"]
    assert fifo["totals"]["totalSpendUsd"] == 13.05
    assert cheapest["totals"]["totalSpendUsd"] == 5.55
    assert cheapest["totals"]["computeSpendUsd"] == 4
    assert cheapest["totals"]["startupCostUsd"] == .25
    assert cheapest["totals"]["transferCostUsd"] == .5
    assert cheapest["totals"]["carbonCostUsd"] == .8
    assert cheapest["jobs"][0]["resourceUnitHours"] == 4
    assert cheapest["jobs"][0]["completionSlackSlots"] == 1
    assert naive["completedJobIds"] == ml["completedJobIds"] == ["a"]
    assert ml["modelVersions"] == ["test-provider-not-trained-ml"]
    assert all(row["ledgerReconciled"] for row in body["strategies"])
    result = comparison(body)
    assert result["comparable"] is True
    assert result["savingsUsd"] == 7.5
    assert result["savingsPercent"] == 57.471264
    assert len(body["comparisons"]) == 6
    # The important ML-versus-naive ablation uses the same optimizer.
    assert comparison(body, baseline="OPTIMIZER_WITH_NAIVE_FORECAST")["savingsUsd"] == 0


def test_equal_completion_counts_with_different_job_ids_are_not_savings(tmp_path):
    app, client = app_with_replay(tmp_path, end=1, jobs=[job("a", deadline_slot=1, resource_units=3),
        job("b", deadline_slot=1, resource_units=3, priority=10)])
    app.state.replay.step()
    body = client.get("/api/metrics").json()
    result = comparison(body, strategy="OPTIMIZER_WITH_NAIVE_FORECAST")
    assert body["strategies"][0]["totals"]["completedJobs"] == 1
    assert body["strategies"][2]["totals"]["completedJobs"] == 1
    assert result["reasonCode"] == "DIFFERENT_WORKLOADS"
    assert result["sameCompletedJobs"] is False
    assert result["savingsUsd"] is result["savingsPercent"] is None


def test_matching_completed_work_with_different_failure_outcomes_is_disclosed(tmp_path):
    app, client = app_with_replay(tmp_path, end=2, provider=ScenarioProvider(cheap_future=True),
        jobs=[job("a", deadline_slot=1, allowed_regions=["a"]),
              job("b", duration_slots=3, deadline_slot=4, allowed_regions=["b"])],
        prices={"a": [1, 1], "b": [10, 1]})
    app.state.replay.shock(ReplayShockRequest(kind="INTERRUPTION", slot=1, region="b", magnitude=1))
    app.state.replay.step(2)
    body = client.get("/api/metrics").json()
    result = comparison(body)
    assert result["sameCompletedJobs"] is True
    assert result["sameOutcomes"] is False
    assert result["reasonCode"] == "DIFFERENT_OUTCOMES"
    assert result["costDifferenceUsd"] == 10
    assert result["savingsUsd"] is None
    assert body["strategies"][0]["failedJobIds"] == ["b"]
    assert body["strategies"][-1]["infeasibleJobIds"] == ["b"]


@pytest.mark.parametrize("failed", [False, True])
def test_in_progress_and_invalid_strategies_have_no_savings_claim(tmp_path, failed):
    class BrokenProvider:
        def predict(self, request):
            raise RuntimeError("Test evaluation provider failed")
    app, client = app_with_replay(tmp_path, provider=BrokenProvider() if failed else False,
                                 jobs=[job(duration_slots=3, deadline_slot=5)])
    app.state.replay.step()
    body = client.get("/api/metrics").json()
    assert comparison(body)["reasonCode"] == ("STRATEGY_ERROR" if failed else "STRATEGY_UNAVAILABLE")
    assert comparison(body)["costDifferenceUsd"] is None
    interim = comparison(body, strategy="CHEAPEST_NOW")
    assert interim["reasonCode"] == "IN_PROGRESS"
    assert interim["savingsUsd"] is None
    assert body["strategies"][0]["totals"]["unfinishedJobs"] == 1


@pytest.mark.parametrize("empty", [False, True])
def test_zero_baselines_never_produce_infinite_percentages(tmp_path, empty):
    app, client = app_with_replay(tmp_path, jobs=[] if empty else [job()], prices={"a": [0] * 3})
    app.state.replay.step(3)
    result = comparison(client.get("/api/metrics").json())
    assert result["savingsPercent"] is None
    assert result["reasonCode"] == ("NO_COMPLETED_WORK" if empty else "COMPARABLE")
    assert result["savingsUsd"] == (None if empty else 0)


def test_bad_forecast_loss_is_reported_as_negative_savings(tmp_path):
    app, client = app_with_replay(tmp_path, end=2, jobs=[job(deadline_slot=2)],
        prices={"a": [5, 9]}, provider=ScenarioProvider(cheap_future=True))
    app.state.replay.step(2)
    result = comparison(client.get("/api/metrics").json())
    assert result["comparable"] is True
    assert result["savingsUsd"] == -4
    assert result["savingsPercent"] == -80
    ml = app.state.replay.state().strategy_states[-1]
    assert ml.decisions[0].action == "WAIT" and ml.decisions[0].projected_cost_usd == .1
    assert ml.metrics.completed_jobs == 1 and ml.metrics.total_spend_usd == 9
    assert ml.charges[0].compute_usd == 9  # realized observation, never the .1 forecast


@pytest.mark.parametrize("corruption", ["price", "duplicate"])
def test_unreconciled_ledger_is_rejected_instead_of_returning_official_metrics(tmp_path, corruption):
    app, client = app_with_replay(tmp_path)
    replay = app.state.replay
    replay.step(3)
    with replay.database.transaction() as connection:
        session = replay._load(connection)
        if corruption == "price":
            session.runs[0].charges[0].compute_usd = 99
        else:
            session.runs[0].charges.append(session.runs[0].charges[0].model_copy())
        replay._save(connection, session)
    response = client.get("/api/metrics")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "METRICS_LEDGER_MISMATCH"


def test_live_projection_uses_latest_plan_once_and_never_becomes_realized_spend(tmp_path):
    row = MarketSnapshot(slot=0, region="a", resource_type="CPU", price_usd_per_unit_hour=2,
        available_units=1, source="test scenario", data_kind="SIMULATED")
    app = create_app(tmp_path / "live.sqlite3", market_source=MemoryMarketSource([row]), clock=lambda: NOW)
    client = TestClient(app)
    client.post("/api/jobs", json=job().model_dump(mode="json", by_alias=True))
    assert client.get("/api/metrics?scope=LIVE").json()["projectedPortfolioCostUsd"] is None
    for _ in range(2):
        assert client.post("/api/optimize", json={"currentSlot": 0}).status_code == 200
    live = client.get("/api/metrics?scope=LIVE").json()
    assert live["knownProjectedCostUsd"] == live["projectedPortfolioCostUsd"] == 2
    assert len(live["projections"]) == 1
    client.post("/api/jobs", json=job("unplanned").model_dump(mode="json", by_alias=True))
    live = client.get("/api/metrics?scope=LIVE").json()
    assert live["knownProjectedCostUsd"] == 2
    assert live["projectedPortfolioCostUsd"] is None
    assert live["unpricedOutstandingJobIds"] == ["unplanned"]
    assert live["realizedSpendUsd"] is live["realizedSavingsUsd"] is None


def test_live_completed_jobs_are_not_assumed_to_have_met_the_deadline(tmp_path):
    class Monitor:
        outcomes = []
        def poll(self, slot):
            return self.outcomes
    monitor = Monitor()
    row = MarketSnapshot(slot=0, region="a", resource_type="CPU", price_usd_per_unit_hour=2,
        available_units=1, source="test scenario", data_kind="SIMULATED")
    app = create_app(tmp_path / "late.sqlite3", market_source=MemoryMarketSource([row]), monitor=monitor, clock=lambda: NOW)
    client = TestClient(app)
    client.post("/api/jobs", json=job(deadline_slot=1).model_dump(mode="json", by_alias=True))
    app.state.engine.tick(0, execution_mode="SIMULATED")
    monitor.outcomes = [ExecutionOutcome("a", "COMPLETED", "SIMULATED", 2, "Injected late result")]
    app.state.engine.tick(2)
    live = client.get("/api/metrics?scope=LIVE").json()
    assert live["jobCounts"]["completedJobs"] == 1
    assert live["missedDeadlineJobIds"] == ["a"]
    assert live["realizedSpendUsd"] is None


def evaluation(**changes):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fields = dict(model_version="test-evaluated-provider", data_source="declared test evaluation",
        sample_count=10, train_start_utc=base, train_end_utc=base + timedelta(days=1),
        validation_start_utc=base + timedelta(days=1), validation_end_utc=base + timedelta(days=2),
        test_start_utc=base + timedelta(days=2), test_end_utc=base + timedelta(days=3),
        evaluated_at_utc=base + timedelta(days=4), mae=1, rmse=1.2, persistence_mae=2, persistence_rmse=2.4)
    return {**fields, **changes}


def test_model_evaluation_adapter_reports_declared_metrics_and_backend_improvements(tmp_path):
    client = TestClient(create_app(tmp_path / "model.sqlite3", clock=lambda: NOW,
        model_metrics_provider=lambda: ModelEvaluation(**evaluation())))
    body = client.get("/api/models/metrics").json()
    assert body["status"] == "EVALUATED"
    assert body["maeImprovement"] == 1
    assert body["maeImprovementPercent"] == body["rmseImprovementPercent"] == 50
    assert body["evaluation"]["sampleCount"] == 10
    assert body["evaluation"]["risk"] is None


@pytest.mark.parametrize("problem", ["overlap", "future", "unlabeled_risk"])
def test_invalid_evaluation_provenance_is_not_published(tmp_path, problem):
    report = evaluation()
    if problem == "overlap":
        report["test_start_utc"] = report["train_start_utc"]
    elif problem == "future":
        report["evaluated_at_utc"] = NOW + timedelta(days=1)
    else:
        report["risk"] = {"hasHistoricalLabels": False, "labelSource": "scenario", "sampleCount": 10, "brierScore": .1}
    client = TestClient(create_app(tmp_path / "invalid.sqlite3", clock=lambda: NOW, model_metrics_provider=lambda: report))
    response = client.get("/api/models/metrics")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MODEL_METRICS_INVALID"


@pytest.mark.parametrize("worse", [False, True])
def test_zero_or_worse_model_baseline_is_reported_honestly(tmp_path, worse):
    report = evaluation(mae=2 if worse else 0, rmse=2 if worse else 0,
                        persistence_mae=1 if worse else 0, persistence_rmse=1 if worse else 0)
    client = TestClient(create_app(tmp_path / "baseline.sqlite3", clock=lambda: NOW, model_metrics_provider=lambda: report))
    body = client.get("/api/models/metrics").json()
    assert body["maeImprovementPercent"] == (-100 if worse else None)


def test_declared_labeled_risk_metrics_retain_calibration_context(tmp_path):
    report = evaluation(risk={"hasHistoricalLabels": True, "labelSource": "test labeled evaluation",
        "sampleCount": 10, "brierScore": .01, "precision": 1, "recall": 1, "classificationThreshold": .5,
        "calibrationBins": [{"sampleCount": 5, "meanPredictedProbability": .1, "observedFrequency": 0},
                            {"sampleCount": 5, "meanPredictedProbability": .9, "observedFrequency": 1}]})
    client = TestClient(create_app(tmp_path / "risk.sqlite3", clock=lambda: NOW, model_metrics_provider=lambda: report))
    risk = client.get("/api/models/metrics").json()["evaluation"]["risk"]
    assert risk["labelSource"] == "test labeled evaluation"
    assert sum(row["sampleCount"] for row in risk["calibrationBins"]) == 10
    assert risk["classificationThreshold"] == .5


def test_hourly_components_use_declared_half_even_precision(tmp_path):
    app, client = app_with_replay(tmp_path, end=2, jobs=[job(duration_slots=2, deadline_slot=2)],
        prices={"a": [.1000000005] * 2}, config=OptimizerConfig(startup_cost_usd=.0000000015))
    app.state.replay.step(2)
    body = client.get("/api/metrics").json()
    assert body["monetaryPrecisionUsd"] == 1e-9
    for row in body["strategies"]:
        assert row["totals"]["computeSpendUsd"] == .2
        assert row["totals"]["startupCostUsd"] == .000000002
        assert row["totals"]["totalSpendUsd"] == .200000002


def test_matching_statuses_with_different_unfinished_progress_are_not_savings(tmp_path):
    class InitiallyCheap(ScenarioProvider):
        def predict(self, request):
            self.cheap_future = request.current_slot == 0
            return super().predict(request)
    app, client = app_with_replay(tmp_path, end=2, provider=InitiallyCheap(),
        jobs=[job("a", deadline_slot=1, allowed_regions=["a"]),
              job("b", duration_slots=3, deadline_slot=5, allowed_regions=["b"])],
        prices={"a": [1, 1], "b": [10, 1]})
    app.state.replay.step(2)
    body = client.get("/api/metrics").json()
    result = comparison(body)
    assert result["sameCompletedJobs"] is result["sameOutcomes"] is True
    assert result["costDifferenceUsd"] == 10
    assert result["reasonCode"] == "UNFINISHED_WORK"
    assert result["savingsUsd"] is result["savingsPercent"] is None
