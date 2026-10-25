from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from app.api.schemas import ForecastRequest, MarketSnapshot
from app.forecasting.alternative_models import AlternativePriceModel, gated_predictions
from app.forecasting.compare_models import DEFAULT_DESIGN, choose_variant, run_comparison
from app.forecasting.experiment_features import extended_features
from app.forecasting.price_model import LightGBMForecastService
from app.forecasting.training_data import Partition, PriceDataset, PriceSeries, build_examples
from app.market.features import SeriesIdentity

ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)
IDENTITY = SeriesIdentity("r", "z", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
TREE = dict(num_leaves=3, max_depth=2, min_data_in_leaf=5, num_boost_round=3)
PARAMETERS = {"ridge": {"alpha": 10},
    "extra-trees": dict(n_estimators=5, max_depth=3, min_samples_leaf=5),
    "hist-gradient": dict(loss="absolute_error", max_iter=3, max_leaf_nodes=3,
                          min_samples_leaf=5, early_stopping=False),
    "two-stage": TREE, "lightgbm-reference": TREE}


def dataset(end=400, constant=False):
    return PriceDataset(ORIGIN, end, [PriceSeries(IDENTITY,
        {i: 1.0 if constant else 1 + ((i // 3) % 5)/10 for i in range(end)})], "test", "SIMULATED")


def samples(data, name, start, end):
    return build_examples(data, Partition(name, start, end), feature_builder=extended_features,
                          feature_lookback=168)[0]


@pytest.mark.parametrize("family", list(PARAMETERS))
def test_models_are_reproducible_finite_and_use_training_encoder_only(family):
    import math
    data = dataset()
    training, validation = samples(data, "train", 0, 260), samples(data, "val", 260, 300)
    model = AlternativePriceModel(family, PARAMETERS[family]).fit(training)
    expected = model.predict_examples(validation)
    repeated = AlternativePriceModel(family, PARAMETERS[family]).fit(training)
    assert repeated.predict_examples(validation) == pytest.approx(expected, abs=1e-12)
    assert len(expected) == len(validation)
    assert all(math.isfinite(x) and x >= 0 for x in expected)
    assert model.metadata["trainingMaxTargetSlot"] == 259
    unseen = deepcopy(validation[0])
    unseen.identity = SeriesIdentity("unseen", "z", "other.gpu", "Linux/UNIX", "GPU", "OtherGPU")
    unseen.features["region"] = "unseen"
    assert model.predict_examples([unseen]) == [unseen.current_price]
    assert "region=unseen" not in model.encoder.vocabulary_
    with pytest.raises(ValueError, match="horizon"):
        model.components([dict(validation[0].features, horizonHours=1.5)])


def test_two_stage_handles_no_change_labels_without_fabricated_probabilities():
    data = dataset(constant=True)
    model = AlternativePriceModel("two-stage", TREE).fit(samples(data, "train", 0, 260))
    validation = samples(data, "val", 260, 300)
    deltas, probabilities = model.components([e.features for e in validation])
    assert list(deltas) == [0] * len(validation)
    assert list(probabilities) == [0] * len(validation)
    assert model.predict_examples(validation) == [1] * len(validation)


def test_gate_and_weight_have_exact_defined_behavior():
    from types import SimpleNamespace
    rows = [SimpleNamespace(current_price=1.0)] * 3
    assert gated_predictions(rows, [.4, .4, -.4], [.49, .5, .9], weight=.5, threshold=.5) == pytest.approx([1, 1.2, .8])
    assert gated_predictions(rows, [.4]*3, [1]*3, weight=0, threshold=0) == [1]*3
    with pytest.raises(ValueError):
        gated_predictions(rows, [1], [1], weight=1, threshold=.5)
    with pytest.raises(ValueError):
        gated_predictions(rows, [1]*3, [float("nan")]*3, weight=1, threshold=.5)
    with pytest.raises(ValueError):
        gated_predictions(rows, [1]*3, [1.1]*3, weight=1, threshold=.5)


def test_alternative_supports_existing_forecast_interface_and_cold_start_fallback():
    data = dataset()
    model = AlternativePriceModel("two-stage", TREE).fit(samples(data, "train", 0, 260))
    model.metadata.update(originUtc=ORIGIN.isoformat(), availableFromSlot=260,
                          modelVersion="synthetic-alternative", correctionWeight=.5, changeThreshold=.7)
    history = [MarketSnapshot(slot=i, region="r", resourceType="GPU", gpuType="TestGPU",
        priceUsdPerUnitHour=data.series[0].prices[i], availableUnits=1, source="synthetic test", dataKind="SIMULATED")
        for i in range(260-168, 261)]
    request = ForecastRequest(currentSlot=260, horizonSlots=6, history=history)
    service = LightGBMForecastService(model, pool_selections=[IDENTITY])
    forecasts = service.predict(request)
    validation = samples(data, "val", 260, 300)
    assert [f.predicted_price_usd_per_unit_hour for f in forecasts] == pytest.approx(model.predict_examples(validation[:6]))
    request.history = history[-25:]
    assert all(f.model_version.endswith("fallback-insufficient-history") for f in service.predict(request))
    request.current_slot = 259
    request.history = history[:-1]
    assert all(f.model_version.endswith("fallback-model-not-available") for f in service.predict(request))


def test_selection_ignores_later_scores():
    variants = [dict(id="a", eligibleForSelection=True, earlier={"overall":{"ml":{"mae":.1}}}, laterDevelopment={"mae":100}),
                dict(id="b", eligibleForSelection=True, earlier={"overall":{"ml":{"mae":.2}}}, laterDevelopment={"mae":0})]
    assert choose_variant(variants)["id"] == "a"
    for v in variants:
        v["eligibleForSelection"] = False
    assert choose_variant(variants) is None


def test_comparison_does_not_use_protected_labels_and_reproduces(tmp_path, monkeypatch):
    import app.forecasting.compare_models as module
    design = json.loads(DEFAULT_DESIGN.read_text())
    design["models"] = {name: PARAMETERS[name] for name in ("ridge", "two-stage")}
    path = tmp_path/"design.json"
    path.write_text(json.dumps(design))
    data = dataset(1000)
    monkeypatch.setattr(module, "load_prepared_dataset", lambda _:data)
    original = module.build_examples
    def protected_builder(development, partition, **kwargs):
        assert development.end_slot == 750
        assert max(development.series[0].prices) == 749
        assert partition.end <= 750
        return original(development, partition, **kwargs)
    monkeypatch.setattr(module, "build_examples", protected_builder)
    first = run_comparison(tmp_path, tmp_path/"run1", design_path=path)
    data.series[0].prices.update({i:10000.0 for i in range(750,1000)})
    second = run_comparison(tmp_path, tmp_path/"run2", design_path=path)
    assert first == second
    assert first["calibration"]["status"] == "RESERVED_NOT_USED"
    assert first["test"]["status"] == "RESERVED_NOT_EVALUATED"
    assert len(first["variants"]) == 8
    assert (tmp_path/"run1/later-predictions.jsonl").read_bytes() == (tmp_path/"run2/later-predictions.jsonl").read_bytes()
