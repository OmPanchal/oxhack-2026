"""Synthetic mixed hardware; no real protected-period labels are scored."""
from datetime import datetime, timedelta, timezone
import json

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from app.forecasting.evaluate_expanded import DEFAULT_DESIGN, cached_feature_builder, evaluate_period, grouped_report, run_evaluation
from app.forecasting.training_data import Example, Partition, PriceDataset, PriceSeries, build_examples
from app.forecasting.experiment_features import feature_profile
from app.forecasting.complex_models import ComplexPriceModel
from app.market.features import SeriesIdentity

ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("profile", ["base24", "extended168"])
def test_cached_features_exactly_match_original_builders_and_ignore_future(profile):
    identity = SeriesIdentity("r", "z", "gpu", "Linux/UNIX", "GPU", "TestGPU")
    prices = {slot: 1+((slot//3)%5)/10 for slot in range(300)}
    raw, _, _, _ = feature_profile(profile)
    calls = []

    def counted(*args):
        calls.append(args[-2])
        return raw(*args)

    cached = cached_feature_builder(counted)
    for current in (200, 201, 199):
        for horizon in range(1, 7):
            expected = raw(prices, identity, ORIGIN, current, horizon)
            assert cached(prices, identity, ORIGIN, current, horizon) == expected
    assert calls == [200, 201, 199]
    changed = {slot: value if slot <= 200 else float("nan") for slot, value in prices.items()}
    assert cached(changed, identity, ORIGIN, 200, 6) == raw(prices, identity, ORIGIN, 200, 6)
    with pytest.raises(ValueError):
        cached(prices, identity, ORIGIN, 200, 7)


def test_memory_optimized_evaluation_matches_original_fitting_predictions():
    identities = [SeriesIdentity("r", "z", "cpu", "Linux/UNIX", "CPU"),
                  SeriesIdentity("r", "z", "gpu", "Linux/UNIX", "GPU", "TestGPU")]
    data = PriceDataset(ORIGIN, 400, [PriceSeries(identity, {i: 1+((i//3)%5)/10 for i in range(400)})
                                    for identity in identities], "synthetic", "SIMULATED")
    design = json.loads(DEFAULT_DESIGN.read_text())
    design["parameters"] = dict(num_leaves=3, max_depth=2, min_data_in_leaf=5, num_boost_round=3)
    train_part, score_part = Partition("train", 0, 260), Partition("score", 260, 300)
    raw, _, _, lookback = feature_profile("extended168")
    training, _ = build_examples(data, train_part, feature_builder=raw, feature_lookback=lookback)
    scoring, _ = build_examples(data, score_part, feature_builder=raw, feature_lookback=lookback)
    expected = {}
    for resource in ("CPU", "GPU"):
        train = [e for e in training if e.identity.resource_type == resource]
        rows = [e for e in scoring if e.identity.resource_type == resource]
        model = ComplexPriceModel("lightgbm-reference", design["parameters"], seed=42).fit(train)
        for e, delta in zip(rows, model.predict_deltas(rows)):
            expected[e.identity, e.origin_slot, e.horizon] = max(0, e.current_price + .5*delta)
    report, rows, predictions = evaluate_period(data, train_part, score_part, design)
    assert len(rows) == len(expected)
    assert all(not e.features for e in rows)
    for e, prediction in zip(rows, predictions):
        assert prediction == expected[e.identity, e.origin_slot, e.horizon]
    assert report["training"]["sampleCount"] == len(training)
    assert report["scoring"]["sampleCount"] == len(scoring)


def test_metrics_keep_resource_units_separate_and_disclose_zero_baseline_pools():
    cpu = SeriesIdentity("r", "z", "cpu", "Linux/UNIX", "CPU")
    gpu = SeriesIdentity("r", "z", "gpu", "Linux/UNIX", "GPU", "TestGPU")
    examples = [Example(cpu, 100, 101, 1, .01, .01, {}),
                Example(gpu, 100, 101, 1, 1, 2, {})]
    report = grouped_report(examples, [.02, 1.5])
    assert set(report) == {"CPU", "GPU"}
    assert report["CPU"]["unit"] == "USD/vCPU-hour"
    assert report["GPU"]["unit"] == "USD/GPU-hour"
    assert report["GPU"]["overall"]["maeImprovementPct"] == 50
    assert report["CPU"]["poolSummary"]["macroMaeImprovementPct"] is None
    assert report["CPU"]["poolSummary"]["undefinedRelativeImprovementPoolCount"] == 1
    assert set(report["GPU"]["byInstanceType"]) == {"gpu"}


def test_fixed_windows_protected_rows_and_resource_specific_fits(tmp_path, monkeypatch):
    import app.forecasting.evaluate_expanded as module
    cpu = SeriesIdentity("r", "z", "cpu", "Linux/UNIX", "CPU")
    gpu = SeriesIdentity("r", "z", "gpu", "Linux/UNIX", "GPU", "TestGPU")
    data = PriceDataset(ORIGIN, 1000, [PriceSeries(identity, {i: scale * (1+((i//3)%5)/10)
                       for i in range(1000)}) for identity, scale in [(cpu, .01), (gpu, 1)]], "synthetic", "SIMULATED")
    design = json.loads(DEFAULT_DESIGN.read_text())
    stamp = lambda slot: (ORIGIN+timedelta(hours=slot)).isoformat()
    design.update(earlierBoundariesUtc=[stamp(i) for i in (300, 400, 500, 600)], laterEndUtcExclusive=stamp(700))
    design["parameters"] = dict(num_leaves=3, max_depth=2, min_data_in_leaf=5, num_boost_round=3)
    path = tmp_path / "design.json"
    path.write_text(json.dumps(design))
    monkeypatch.setattr(module, "load_prepared_dataset", lambda _: data)
    original = module.build_examples

    def guarded_builder(development, partition, **kwargs):
        assert development.end_slot == 700
        assert partition.end <= 700
        assert all(max(s.prices) == 699 for s in development.series)
        return original(development, partition, **kwargs)

    monkeypatch.setattr(module, "build_examples", guarded_builder)
    original_fit = module.ComplexPriceModel.fit
    fitted = []

    def checked_fit(self, rows):
        resources = {e.identity.resource_type for e in rows}
        assert len(resources) == 1
        fitted.append(resources.pop())
        return original_fit(self, rows)

    monkeypatch.setattr(module.ComplexPriceModel, "fit", checked_fit)
    first = run_evaluation(tmp_path, tmp_path / "first", design_path=path)
    for series in data.series:
        series.prices.update({slot: 9999. for slot in range(700, 1000)})
    second = run_evaluation(tmp_path, tmp_path / "second", design_path=path)
    assert first == second
    assert set(fitted) == {"CPU", "GPU"}
    assert first["protectedFromSlot"] == 700
    assert first["test"]["status"] == "RESERVED_NOT_EVALUATED"
    assert first["calibration"]["status"] == "RESERVED_NOT_USED"
    assert set(first["earlierAggregate"]) == {"CPU", "GPU"}
    for name in first["periods"]:
        rows = [json.loads(line) for line in (tmp_path / "first" / f"{name}-predictions.jsonl").read_text().splitlines()]
        assert all(row["originSlot"] < row["targetSlot"] < 700 for row in rows)
        assert (tmp_path / "first" / f"{name}-predictions.jsonl").read_bytes() == (tmp_path / "second" / f"{name}-predictions.jsonl").read_bytes()
    with pytest.raises(ValueError, match="fresh"):
        run_evaluation(tmp_path, tmp_path / "first", design_path=path)


def test_rejects_design_that_crosses_original_protected_cutoff(tmp_path):
    design = json.loads(DEFAULT_DESIGN.read_text())
    design["laterEndUtcExclusive"] = "2026-10-02T00:00:00Z"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(design))
    with pytest.raises(ValueError, match="protected"):
        run_evaluation(tmp_path, tmp_path / "output", design_path=path)
    assert not (tmp_path / "output").exists()
