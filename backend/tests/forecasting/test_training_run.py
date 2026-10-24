"""Synthetic in-memory data only; no real calibration/test labels are evaluated."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from app.forecasting import train
from app.forecasting.training_data import PriceDataset, PriceSeries
from app.market.features import SeriesIdentity


def test_training_run_reserves_holdouts_and_reproduces_weights(monkeypatch, tmp_path):
    identity = SeriesIdentity("r1", "z1", "test.gpu", "Linux/UNIX", "GPU", "TestGPU")
    dataset = PriceDataset(datetime(2026, 1, 1, tzinfo=timezone.utc), 160,
                           [PriceSeries(identity, {slot: 1 + ((slot // 3) % 5) / 10 for slot in range(160)})],
                           "synthetic-input", "SIMULATED")
    monkeypatch.setattr(train, "load_prepared_dataset", lambda _: dataset)
    monkeypatch.setattr(train, "CANDIDATES", (
        {"id": "test-l1", "objective": "regression_l1", "num_leaves": 3, "max_depth": 2,
         "min_data_in_leaf": 5, "learning_rate": 0.1, "num_boost_round": 4},
        {"id": "test-l2", "objective": "regression", "num_leaves": 3, "max_depth": 2,
         "min_data_in_leaf": 5, "learning_rate": 0.1, "num_boost_round": 4},
    ))
    original_builder = train.build_examples
    used = []
    def checked_builder(data, partition):
        used.append(partition.name)
        assert partition.name in ("train", "validation")
        return original_builder(data, partition)
    monkeypatch.setattr(train, "build_examples", checked_builder)
    original = train.run_training(tmp_path/"input", tmp_path/"model-a", tmp_path/"report-a")
    repeated = train.run_training(tmp_path/"input", tmp_path/"model-b", tmp_path/"report-b")
    assert original == repeated
    assert (tmp_path/"model-a/model.txt").read_bytes() == (tmp_path/"model-b/model.txt").read_bytes()
    assert (tmp_path/"model-a/metadata.json").read_bytes() == (tmp_path/"model-b/metadata.json").read_bytes()
    changed = deepcopy(dataset)
    for slot in range(120, 160):
        changed.series[0].prices[slot] = 9999
    changed.sha256 = "different-holdout-data"
    monkeypatch.setattr(train, "load_prepared_dataset", lambda _: changed)
    altered = train.run_training(tmp_path/"input", tmp_path/"model-c", tmp_path/"report-c")
    assert altered["metrics"] == original["metrics"]
    assert altered["selectedCandidate"] == original["selectedCandidate"]
    assert (tmp_path/"model-a/model.txt").read_bytes() == (tmp_path/"model-c/model.txt").read_bytes()
    assert original["calibration"]["status"] == "RESERVED_NOT_USED"
    assert original["test"]["status"] == "RESERVED_NOT_EVALUATED"
    assert original["dataKind"] == "SIMULATED"
    assert used == ["train", "validation"] * 3
    metadata = json.loads((tmp_path/"model-a/metadata.json").read_text())
    assert metadata["trainingMaxTargetSlot"] < 96
    assert metadata["availableFromSlot"] == 120
    with pytest.raises(ValueError, match="new"):
        train.run_training(tmp_path/"input", tmp_path/"model-a", tmp_path/"another-report")
    with pytest.raises(ValueError, match="nonnested"):
        train.run_training(tmp_path/"input", tmp_path/"nested", tmp_path/"nested/report")
