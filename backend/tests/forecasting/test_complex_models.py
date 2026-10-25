"""Synthetic correctness checks; real protected evaluation periods are never scored."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from app.forecasting.complex_models import ComplexPriceModel
from app.forecasting.compare_complex_models import DEFAULT_DESIGN, run_comparison, select_variant, variant_predictions
from app.forecasting.experiment_features import extended_features
from app.forecasting.training_data import Partition, PriceDataset, PriceSeries, build_examples
from app.market.features import SeriesIdentity

IDENTITY = SeriesIdentity("r", "z", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
TREE = dict(num_leaves=3, max_depth=2, min_data_in_leaf=5, num_boost_round=3)
PARAMETERS = {"lightgbm-reference": TREE, "deep-lightgbm": TREE,
              "random-forest": dict(n_estimators=5, max_depth=3, min_samples_leaf=5),
              "rbf-svr": dict(C=1, epsilon=.1),
              "mlp": dict(hidden_layer_sizes=[8, 4], max_iter=3, alpha=1, batch_size=32)}


def dataset(end=400):
    return PriceDataset(datetime(2026, 1, 1, tzinfo=timezone.utc), end,
        [PriceSeries(IDENTITY, {i: 1 + ((i // 3) % 5) / 10 for i in range(end)})], "test", "SIMULATED")


def samples(data, start, end):
    return build_examples(data, Partition("synthetic", start, end), feature_builder=extended_features,
                          feature_lookback=168)[0]


def assert_same_numerics(first, second):
    """Allow platform BLAS rounding only; structure/identity/counts stay exact."""
    if isinstance(first, dict):
        assert first.keys() == second.keys()
        for key in first:
            assert_same_numerics(first[key], second[key])
    elif isinstance(first, list):
        assert len(first) == len(second)
        for left, right in zip(first, second):
            assert_same_numerics(left, right)
    elif isinstance(first, float):
        assert first == pytest.approx(second, rel=0, abs=1e-12)
    else:
        assert first == second


@pytest.mark.parametrize("family", list(PARAMETERS))
def test_models_reproduce_ignore_prediction_labels_and_fallback_for_unseen_pools(family):
    data = dataset()
    training, validation = samples(data, 0, 260), samples(data, 260, 300)
    model = ComplexPriceModel(family, PARAMETERS[family]).fit(training)
    prediction = model.predict_deltas(validation)
    duplicate = ComplexPriceModel(family, PARAMETERS[family]).fit(training)
    assert duplicate.predict_deltas(validation) == pytest.approx(prediction, abs=1e-12)
    assert model.training_max_target_slot < min(e.origin_slot for e in validation)
    changed = deepcopy(validation)
    for e in changed:
        e.target_price = float("nan")
    assert model.predict_deltas(changed) == pytest.approx(prediction, rel=0, abs=1e-12)
    changed[0].identity = SeriesIdentity("unseen", "z", "other", "Linux/UNIX", "GPU", "Other")
    assert model.predict_deltas(changed[:1]) == [0.0]
    assert model.predict_deltas([]) == []
    if family in {"mlp", "rbf-svr"}:
        assert model.scaler.n_samples_seen_ == len(training)
        assert model.target_scalers[1].n_samples_seen_ == len(training) // 6
        assert model.target_scalers[1].mean_[0] == pytest.approx(
            sum(e.target_price-e.current_price for e in training if e.horizon == 1) / (len(training)//6))
        assert "region=unseen" not in model.encoder.vocabulary_
    if family == "mlp":
        assert model.fit_warnings  # Deliberately tiny iteration budget is disclosed.
        assert not model.models[1].early_stopping
        assert not model.models[1].shuffle


def test_fixed_ensemble_and_shrinkage_are_exact():
    from types import SimpleNamespace
    examples = [SimpleNamespace(current_price=1)] * 2
    design = dict(models={"lightgbm-reference": {}, "rbf-svr": {}}, correctionWeights=[.25, 1],
                  ensembles={"blend": ["lightgbm-reference", "rbf-svr"]}, ensembleCorrectionWeight=.5)
    result = variant_predictions(examples, {"lightgbm-reference": [.4, -.4], "rbf-svr": [.8, -4]}, design)
    assert result["lightgbm-reference-weight-0.5"] == pytest.approx([1.2, .8])
    assert result["rbf-svr-weight-0.25"] == pytest.approx([1.2, 0])
    assert result["blend"] == pytest.approx([1.3, 0])


def test_selection_cannot_follow_later_scores():
    variants = [dict(id="a", eligibleToReplaceIncumbent=True, earlier={"overall":{"ml":{"mae":.1}}}, later=100),
                dict(id="b", eligibleToReplaceIncumbent=True, earlier={"overall":{"ml":{"mae":.2}}}, later=0)]
    assert select_variant(variants, "incumbent") == "a"
    for v in variants:
        v["eligibleToReplaceIncumbent"] = False
    assert select_variant(variants, "incumbent") == "incumbent"


def test_runner_excludes_protected_rows_and_reproduces(tmp_path, monkeypatch):
    import app.forecasting.compare_complex_models as module
    design = json.loads(DEFAULT_DESIGN.read_text())
    design["models"] = {name: PARAMETERS[name] for name in ("lightgbm-reference", "rbf-svr")}
    design["ensembles"] = {"blend": list(design["models"])}
    design["correctionWeights"] = [.5]
    design_path = tmp_path / "design.json"
    design_path.write_text(json.dumps(design))
    data = dataset(1000)
    monkeypatch.setattr(module, "load_prepared_dataset", lambda _: data)
    original = module.build_examples

    def bounded_builder(development, partition, **kwargs):
        assert development.end_slot == 750
        assert max(development.series[0].prices) == 749
        assert partition.end <= 750
        return original(development, partition, **kwargs)

    monkeypatch.setattr(module, "build_examples", bounded_builder)
    first = run_comparison(tmp_path, tmp_path / "first", design_path=design_path)
    data.series[0].prices.update({i: 9999.0 for i in range(750, 1000)})
    second = run_comparison(tmp_path, tmp_path / "second", design_path=design_path)
    assert_same_numerics(first, second)
    assert first["calibration"]["status"] == "RESERVED_NOT_USED"
    assert first["test"]["status"] == "RESERVED_NOT_EVALUATED"
    for name in ("earlier-predictions.jsonl", "later-predictions.jsonl"):
        left = [json.loads(line) for line in (tmp_path / "first" / name).read_text().splitlines()]
        right = [json.loads(line) for line in (tmp_path / "second" / name).read_text().splitlines()]
        assert_same_numerics(left, right)
    with pytest.raises(ValueError, match="fresh"):
        run_comparison(tmp_path, tmp_path / "first", design_path=design_path)
