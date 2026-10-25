import math

import pytest

from app.market.features import InsufficientHistoryError, SeriesIdentity, build_features

IDENTITY = SeriesIdentity("test-region", "test-zone", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
ORIGIN = "2026-01-01T00:00:00Z"


def test_hand_calculated_lags_means_and_volatility():
    history = {slot: 1 + slot / 100 for slot in range(60)}
    features = build_features(history, IDENTITY, ORIGIN, 24, 3)
    assert features["latestPrice"] == 1.24
    assert features["lagPrice1h"] == 1.23
    assert features["lagPrice24h"] == 1
    assert features["rollingMean3h"] == pytest.approx(1.23)
    assert features["rollingStd3h"] == pytest.approx(math.sqrt(2 / 3) * 0.01)
    assert features["hoursSinceLastChange"] == 0
    assert features["lastPriceChange"] == pytest.approx(0.01)
    assert features["targetHourSin"] == pytest.approx(math.sin(2 * math.pi * 3 / 24))


def test_features_identical_with_truncated_history_and_arbitrary_future_values():
    history = {slot: float(slot + 1) for slot in range(60)}
    expected = build_features(history, IDENTITY, ORIGIN, 30, 6)
    assert build_features({k: v for k, v in history.items() if k <= 30}, IDENTITY, ORIGIN, 30, 6) == expected
    history.update({slot: float("nan") for slot in range(31, 60)})
    assert build_features(history, IDENTITY, ORIGIN, 30, 6) == expected


def test_constant_price_age_is_capped_without_implying_a_missing_feed():
    history = {slot: 0.25 for slot in range(25)}
    features = build_features(history, IDENTITY, ORIGIN, 24, 1)
    assert features["rollingStd24h"] == 0
    assert features["hoursSinceLastChange"] == 24
    assert features["priceAgeCapped"] == 1
    history[22] = 0.2
    assert build_features(history, IDENTITY, ORIGIN, 24, 1)["hoursSinceLastChange"] == 1


def test_missing_history_invalid_values_and_horizons_are_explicit():
    history = {slot: 0.25 for slot in range(25)}
    for value in (None,):
        history[10] = value
        with pytest.raises(InsufficientHistoryError):
            build_features(history, IDENTITY, ORIGIN, 24, 1)
    for value in (-1, float("nan"), float("inf")):
        history[10] = value
        with pytest.raises(ValueError):
            build_features(history, IDENTITY, ORIGIN, 24, 1)
    for horizon in (0, 7, True):
        with pytest.raises(ValueError):
            build_features(history, IDENTITY, ORIGIN, 24, horizon)


def test_cpu_gpu_feature_keys_match_and_identity_values_remain_separate():
    history = {slot: 1.0 for slot in range(25)}
    cpu = SeriesIdentity("other-region", "other-zone", "test.cpu", "Linux/UNIX", "CPU")
    gpu_features = build_features(history, IDENTITY, ORIGIN, 24, 1)
    cpu_features = build_features(history, cpu, ORIGIN, 24, 1)
    assert list(gpu_features) == list(cpu_features)
    assert cpu_features["resourceType"] == "CPU" and cpu_features["gpuType"] == "NONE"
    assert gpu_features["availabilityZone"] != cpu_features["availabilityZone"]
