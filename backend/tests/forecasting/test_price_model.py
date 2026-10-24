from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from app.api.schemas import ForecastRequest, MarketSnapshot
from app.forecasting.price_model import LightGBMForecastService, LightGBMPriceModel
from app.forecasting.training_data import PriceDataset, PriceSeries, build_examples, chronological_partitions
from app.market.features import SeriesIdentity

IDENTITY = SeriesIdentity("r1", "z1", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
ORIGIN = datetime(2026, 1, 1, tzinfo=timezone.utc)
PARAMETERS = dict(objective="regression", num_leaves=7, max_depth=3, min_data_in_leaf=5,
                  learning_rate=0.05, num_boost_round=12)


def examples():
    dataset = PriceDataset(ORIGIN, 160, [PriceSeries(IDENTITY, {
        slot: 1 + ((slot // 3) % 5) / 10 for slot in range(160)
    })], "test", "SIMULATED")
    partitions = chronological_partitions(160)
    train, _ = build_examples(dataset, partitions["train"])
    validation, _ = build_examples(dataset, partitions["validation"])
    return train, validation


@pytest.fixture(scope="module")
def trained():
    training, validation = examples()
    model = LightGBMPriceModel.fit(training, PARAMETERS)
    model.metadata.update(originUtc=ORIGIN.isoformat(), seriesIdentities=[IDENTITY.to_dict()],
                          availableFromSlot=120, trainingMaxTargetSlot=95,
                          selectedUsingValidationThroughSlot=119, modelVersion="synthetic-test-model")
    return model, training, validation


def request(current=120, *, full_history=True, region="r1"):
    slots = range(current - 24, current + 1) if full_history else (current,)
    rows = [MarketSnapshot(slot=slot, region=region, resourceType="GPU", gpuType="TestGPU",
                           priceUsdPerUnitHour=1 + ((slot // 3) % 5) / 10,
                           availableUnits=2, source="SIMULATED model test", dataKind="SIMULATED")
            for slot in slots]
    return ForecastRequest(currentSlot=current, horizonSlots=6, history=rows)


def test_model_predictions_are_finite_nonnegative_and_deterministic(trained):
    import math
    model, training, validation = trained
    predictions = model.predict_examples(validation)
    assert len(predictions) == len(validation)
    assert all(math.isfinite(value) and value >= 0 for value in predictions)
    duplicate = LightGBMPriceModel.fit(training, PARAMETERS)
    assert duplicate.predict_examples(validation) == pytest.approx(predictions, rel=0, abs=1e-12)


def test_encoder_only_fits_training_categories(trained):
    model, _, validation = trained
    assert "region=r1" in model.vectorizer.vocabulary_
    assert "region=unseen" not in model.vectorizer.vocabulary_
    unseen = deepcopy(validation[0])
    unseen.identity = SeriesIdentity("unseen", "z2", "other.gpu", "Linux/UNIX", "GPU", "OtherGPU")
    unseen.features["region"] = "unseen"
    assert model.predict_examples([unseen]) == [unseen.current_price]


def test_model_reload_and_checksums(trained, tmp_path):
    model, _, validation = trained
    expected = model.predict_examples(validation)
    model.save(tmp_path/"artifact")
    loaded = LightGBMPriceModel.load(tmp_path/"artifact")
    assert loaded.predict_examples(validation) == pytest.approx(expected, rel=0, abs=1e-12)
    before = dict(model.metadata)
    model.save(tmp_path/"same-model")
    assert model.metadata["modelVersion"] == before["modelVersion"]
    with pytest.raises(ValueError):
        model.save(tmp_path/"artifact")
    with (tmp_path/"artifact/encoder.json").open("a") as stream:
        stream.write("tampered")
    with pytest.raises(ValueError, match="checksum"):
        LightGBMPriceModel.load(tmp_path/"artifact")


def test_forecast_service_uses_identical_feature_builder_and_null_risk(trained):
    from app.market.features import build_features
    model, _, _ = trained
    service = LightGBMForecastService(model, pool_selections=[IDENTITY])
    data = request()
    prices = {row.slot: row.price_usd_per_unit_hour for row in data.history}
    expected = model.predict_features([build_features(prices, IDENTITY, ORIGIN, 120, h) for h in range(1, 7)])
    forecasts = service.predict(data)
    assert [row.predicted_price_usd_per_unit_hour for row in forecasts] == expected
    assert all(row.model_version == model.metadata["modelVersion"] for row in forecasts)
    assert all(row.availability_probability is None and row.interruption_probability is None and
               row.price_lower_bound is None and row.price_upper_bound is None for row in forecasts)


def test_fallback_before_selection_cutoff_never_calls_model(trained, monkeypatch):
    model, _, _ = trained
    def forbidden(_):
        raise AssertionError("Future-selected model was used")
    monkeypatch.setattr(model, "predict_features", forbidden)
    service = LightGBMForecastService(model, pool_selections=[IDENTITY])
    forecasts = service.predict(request(current=119))
    assert all(row.model_version == "persistence-v1:fallback-model-not-available" for row in forecasts)


def test_cold_start_unknown_pools_and_stale_requests(trained):
    model, _, _ = trained
    service = LightGBMForecastService(model, pool_selections=[IDENTITY])
    cold = request(full_history=False)
    result = service.predict(cold)
    assert all(row.model_version == "persistence-v1:fallback-insufficient-history" for row in result)
    assert all(row.predicted_price_usd_per_unit_hour == cold.history[-1].price_usd_per_unit_hour for row in result)
    assert all(row.model_version == "persistence-v1:fallback-unmapped-pool"
               for row in service.predict(request(region="unseen")))
    unsupported = SeriesIdentity("r1", "z1", "unknown.gpu", "Linux/UNIX", "GPU", "TestGPU")
    other = LightGBMForecastService(model, pool_selections=[unsupported])
    assert all(row.model_version == "persistence-v1:fallback-unsupported-pool" for row in other.predict(request()))
    stale = request()
    stale.current_slot += 1
    with pytest.raises(ValueError, match="Stale"):
        service.predict(stale)
    assert service.predict(ForecastRequest(currentSlot=120, history=[])) == []


def test_service_refuses_ambiguous_api_pool_selection(trained):
    model, _, _ = trained
    other_zone = SeriesIdentity("r1", "z2", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
    with pytest.raises(ValueError, match="one AZ"):
        LightGBMForecastService(model, pool_selections=[IDENTITY, other_zone])


def test_artifact_rejects_changed_feature_schema(trained, tmp_path):
    model, _, _ = trained
    model.save(tmp_path/"artifact")
    path = tmp_path/"artifact/metadata.json"
    metadata = json.loads(path.read_text())
    metadata["featureSchemaVersion"] = "future-incompatible-version"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Feature builder"):
        LightGBMPriceModel.load(tmp_path/"artifact")
