from datetime import datetime, timezone
import math

import pytest

from app.forecasting.evaluate import compare_predictions, evaluation_report, regression_metrics
from app.forecasting.training_data import PriceDataset, PriceSeries, build_examples, chronological_partitions
from app.market.features import SeriesIdentity


def test_metrics_match_hand_calculation_and_reject_bad_input():
    metrics = regression_metrics([1, 3], [1, 1])
    assert metrics["mae"] == 1
    assert metrics["rmse"] == pytest.approx(math.sqrt(2))
    for actual, predicted in (([], []), ([1], [1, 2]), ([float("nan")], [1])):
        with pytest.raises(ValueError):
            regression_metrics(actual, predicted)


def test_zero_baseline_and_grouped_metrics_are_explicit():
    identity = SeriesIdentity("r1", "z1", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
    dataset = PriceDataset(datetime(2026, 1, 1, tzinfo=timezone.utc), 160,
                           [PriceSeries(identity, {slot: 1.0 for slot in range(160)})], "test", "SIMULATED")
    examples, _ = build_examples(dataset, chronological_partitions(160)["validation"])
    comparison = compare_predictions(examples, [1.1] * len(examples))
    assert comparison["maeImprovementPct"] is None
    assert comparison["ml"]["mae"] > 0
    report = evaluation_report(examples, [1.0] * len(examples))
    assert report["overall"]["maeImprovementPct"] is None
    assert set(report["byHorizon"]) == {str(i) for i in range(1, 7)}
    assert set(report["byPriceMovement"]) == {"UNCHANGED"}
    assert sum(row["sampleCount"] for row in report["byHorizon"].values()) == len(examples)
