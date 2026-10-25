from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from app.forecasting.experiment_features import extended_features, feature_profile
from app.forecasting.experiment_bundle import ExperimentBundle
from app.forecasting.experiments import blend_predictions, choose_horizon_weights, walk_forward_folds, run_experiments
from app.forecasting.price_model import LightGBMPriceModel, LightGBMForecastService
from app.forecasting.training_data import PriceDataset, PriceSeries, Partition, build_examples
from app.market.features import SeriesIdentity, InsufficientHistoryError
from app.api.schemas import ForecastRequest, MarketSnapshot

IDENTITY = SeriesIdentity("r1", "z1", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_extended_features_are_causal_and_measure_changes():
    prices = {i: float(i) for i in range(250)}
    features = extended_features(prices, IDENTITY, ORIGIN, 200, 6)
    assert features["lagPrice168h"] == 32
    assert features["rollingMean48h"] == 176.5
    assert features["changeFrequency168h"] == 1
    assert features["meanAbsoluteChange168h"] == 1
    assert features["extendedHoursSinceLastChange"] == 0
    altered = {i: (value if i <= 200 else 1e6) for i, value in prices.items()}
    assert extended_features(altered, IDENTITY, ORIGIN, 200, 6) == features
    assert extended_features({i: v for i, v in prices.items() if i <= 200}, IDENTITY, ORIGIN, 200, 6) == features
    prices[32] = None
    with pytest.raises(InsufficientHistoryError):
        extended_features(prices, IDENTITY, ORIGIN, 200, 6)


def test_feature_profiles_use_identical_eligible_origins():
    dataset = PriceDataset(ORIGIN, 400, [PriceSeries(IDENTITY, {i: 1.0 for i in range(400)})], "test", "SIMULATED")
    cohorts = []
    for profile in ("base24", "extended168"):
        builder, _, _, lookback = feature_profile(profile)
        rows, _ = build_examples(dataset, Partition("train", 0, 300), feature_builder=builder,
                                 feature_lookback=lookback, eligibility_lookback=168)
        cohorts.append([(r.origin_slot, r.target_slot) for r in rows])
    assert cohorts[0] == cohorts[1]
    assert min(origin for origin, _ in cohorts[0]) == 168


def test_walk_forward_folds_do_not_overlap_labels():
    folds = walk_forward_folds(1281, [.4, .6, .8, 1.0])
    assert [(a.end, b.start, b.end) for a, b in folds] == [(512, 512, 768), (768, 768, 1024), (1024, 1024, 1281)]
    with pytest.raises(ValueError):
        walk_forward_folds(100, [.6, .4, 1.0])


def test_weights_select_shrinkage_only_when_multiple_folds_improve():
    from types import SimpleNamespace
    rows = [SimpleNamespace(horizon=h, current_price=1.0, target_price=1.1)
            for _ in range(3) for h in range(1, 7)]
    slices = [(0, 6), (6, 12), (12, 18)]
    raw = [1.4] * len(rows)
    weights = choose_horizon_weights(rows, raw, slices, [0, .25, .5, 1], 2, 1e-12)
    assert set(weights.values()) == {.25}
    assert blend_predictions(rows, raw, weights) == pytest.approx([1.1] * len(rows))
    assert set(choose_horizon_weights(rows, [0.6] * len(rows), slices, [0, .25, 1], 2, 1e-12).values()) == {0}
    # One excellent fold cannot outweigh two folds harmed by the correction.
    assert set(choose_horizon_weights(rows, [1.1] * 6 + [.6] * 12, slices, [0, 1], 2, 1e-12).values()) == {0}


@pytest.mark.parametrize("architecture", ["pooled", "per-horizon"])
def test_bundle_roundtrip_and_shared_inference_service(architecture, tmp_path):
    prices = {i: 1 + ((i // 3) % 5) / 10 for i in range(400)}
    dataset = PriceDataset(ORIGIN, 400, [PriceSeries(IDENTITY, prices)], "test", "SIMULATED")
    builder, schema, digest, lookback = feature_profile("extended168")
    train, _ = build_examples(dataset, Partition("train", 0, 260), feature_builder=builder, feature_lookback=lookback)
    validation, _ = build_examples(dataset, Partition("validation", 260, 300), feature_builder=builder, feature_lookback=lookback)
    keys = ["pooled"] if architecture == "pooled" else list(map(str, range(1, 7)))
    models = {key: LightGBMPriceModel.fit(train if key == "pooled" else [e for e in train if e.horizon == int(key)],
              dict(objective="regression", num_leaves=3, min_data_in_leaf=5, num_boost_round=3),
              feature_schema=schema, feature_code_sha256=digest) for key in keys}
    metadata = dict(originUtc=ORIGIN.isoformat(), seriesIdentities=[IDENTITY.to_dict()], availableFromSlot=260)
    bundle = ExperimentBundle(models, dict(architecture=architecture, featureProfile="extended168"),
                              {str(h): .25 for h in range(1, 7)}, metadata)
    expected = bundle.predict_examples(validation)
    bundle.save(tmp_path/"bundle")
    loaded = ExperimentBundle.load(tmp_path/"bundle")
    assert loaded.predict_examples(validation) == pytest.approx(expected, abs=1e-12)
    history = [MarketSnapshot(slot=i, region="r1", resourceType="GPU", gpuType="TestGPU",
               priceUsdPerUnitHour=prices[i], availableUnits=1, source="synthetic test", dataKind="SIMULATED")
               for i in range(260-168, 261)]
    service = LightGBMForecastService(loaded, pool_selections=[IDENTITY])
    request = ForecastRequest(currentSlot=260, horizonSlots=6, history=history)
    forecasts = service.predict(request)
    assert [r.predicted_price_usd_per_unit_hour for r in forecasts] == pytest.approx(expected[:6])
    request.history = history[-25:]
    assert all(r.model_version.endswith("fallback-insufficient-history") for r in service.predict(request))
    with (tmp_path/"bundle"/keys[0]/"metadata.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        ExperimentBundle.load(tmp_path/"bundle")


def test_runner_never_uses_protected_period_and_is_reproducible(tmp_path, monkeypatch):
    import app.forecasting.experiments as experiment_module
    from app.forecasting.experiments import DEFAULT_DESIGN
    design = json.loads(DEFAULT_DESIGN.read_text())
    design.update(featureProfiles=["base24", "extended168"], architectures=["pooled"], correctionWeights=[0, .5, 1])
    design["regularization"] = {"tiny": dict(objective="regression", num_leaves=3, min_data_in_leaf=5, num_boost_round=3)}
    design_path = tmp_path/"design.json"
    design_path.write_text(json.dumps(design))
    dataset = PriceDataset(ORIGIN, 1000, [PriceSeries(IDENTITY,
        {i: 1 + ((i // 3) % 5) / 10 for i in range(1000)})], "test", "SIMULATED")
    monkeypatch.setattr(experiment_module, "load_prepared_dataset", lambda _: dataset)
    original_builder = experiment_module.build_examples
    def protected_builder(data, partition, **kwargs):
        assert partition.end <= 750
        assert data.end_slot == 750
        assert max(data.series[0].prices) == 749
        return original_builder(data, partition, **kwargs)
    monkeypatch.setattr(experiment_module, "build_examples", protected_builder)
    first = run_experiments(tmp_path, tmp_path/"model1", tmp_path/"report1", design_path=design_path)
    dataset.series[0].prices.update({i: 1000.0 for i in range(750, 1000)})
    second = run_experiments(tmp_path, tmp_path/"model2", tmp_path/"report2", design_path=design_path)
    assert first == second
    assert first["calibration"]["status"] == "RESERVED_NOT_USED"
    assert first["test"]["status"] == "RESERVED_NOT_EVALUATED"
    assert (tmp_path/"report1/selected-confirmation-predictions.jsonl").read_bytes() == (tmp_path/"report2/selected-confirmation-predictions.jsonl").read_bytes()
