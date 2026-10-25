from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.forecasting.training_data import (
    PriceDataset, PriceSeries, build_examples, chronological_partitions, load_prepared_dataset,
)
from app.market.features import SeriesIdentity


def synthetic_dataset(slots=160):
    return PriceDataset(datetime(2026, 1, 1, tzinfo=timezone.utc), slots, [
        PriceSeries(SeriesIdentity("r1", zone, "test.gpu", "Linux/UNIX", "GPU", "TestGPU"),
                    {slot: 1 + ((slot // 3) % 5) / 10 for slot in range(slots)})
        for zone in ("z1", "z2")], "synthetic-test-fingerprint", "SIMULATED")


def test_common_partitions_and_maximum_horizon_purging():
    dataset = synthetic_dataset()
    partitions = chronological_partitions(dataset.end_slot)
    assert [(p.start, p.end) for p in partitions.values()] == [(0, 96), (96, 120), (120, 136), (136, 160)]
    for partition in partitions.values():
        examples, summary = build_examples(dataset, partition)
        assert summary["sampleCount"] == len(examples)
        assert all(partition.start <= e.origin_slot and e.origin_slot + 6 < partition.end for e in examples)
        assert all(e.origin_slot < e.target_slot < partition.end for e in examples)
        assert {e.horizon for e in examples} == set(range(1, 7))
    train, _ = build_examples(dataset, partitions["train"])
    validation, _ = build_examples(dataset, partitions["validation"])
    assert max(e.target_slot for e in train) < min(e.origin_slot for e in validation)


def test_future_changes_cannot_change_training_examples():
    dataset = synthetic_dataset()
    partition = chronological_partitions(dataset.end_slot)["train"]
    expected, _ = build_examples(dataset, partition)
    changed = deepcopy(dataset)
    for series in changed.series:
        series.prices.update({slot: 1000 for slot in range(partition.end, dataset.end_slot)})
    actual, _ = build_examples(changed, partition)
    assert actual == expected


def test_missing_history_skips_whole_origin_without_backfill():
    dataset = synthetic_dataset()
    partitions = chronological_partitions(dataset.end_slot)
    _, before = build_examples(dataset, partitions["train"])
    dataset.series[0].prices[0] = None
    examples, after = build_examples(dataset, partitions["train"])
    assert after["sampleCount"] == before["sampleCount"] - 6
    assert after["skippedOriginsWithMissingHistoryOrLabels"] == 1
    assert not any(e.identity.availability_zone == "z1" and e.origin_slot == 24 for e in examples)


def test_loader_requires_integrity_and_explicit_synthetic_opt_in(tmp_path):
    fixture = Path(__file__).resolve().parents[3]/"data/examples/prepared-hourly-simulated"
    with pytest.raises(ValueError, match="observed"):
        load_prepared_dataset(fixture)
    dataset = load_prepared_dataset(fixture, allow_simulated=True)
    assert len(dataset.series) == 2
    for name in ("hourly-prices.jsonl", "manifest.json"):
        (tmp_path/name).write_bytes((fixture/name).read_bytes())
    with (tmp_path/"hourly-prices.jsonl").open("a") as stream:
        stream.write("tampered")
    with pytest.raises(ValueError, match="checksum"):
        load_prepared_dataset(tmp_path, allow_simulated=True)
    with pytest.raises(ValueError, match="coverage"):
        chronological_partitions(20)
