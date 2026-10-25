from datetime import datetime, timezone
import hashlib
import json

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from app.forecasting.benchmark_final import generate_workloads, run_benchmark
from app.forecasting.evaluate_final import DEFAULT_DESIGN
from app.forecasting.training_data import PriceDataset, PriceSeries
from app.market.features import SeriesIdentity


def test_workload_generation_is_reproducible_deadline_feasible_and_stops_before_tail():
    design = json.loads(DEFAULT_DESIGN.read_text())["replay"]
    first = generate_workloads("test.cpu", ["p1", "p2"], 4, 0, 100, design, 42)
    assert first == generate_workloads("test.cpu", ["p1", "p2"], 4, 0, 100, design, 42)
    assert first != generate_workloads("test.cpu", ["p1", "p2"], 4, 0, 100, design, 43)
    assert len({j.id for j in first}) == len(first)
    assert all(j.arrival+j.duration <= j.deadline < 100 and j.units == 4 for j in first)


def test_full_adapter_uses_same_inputs_for_four_policies_and_reconciles_cost(tmp_path, monkeypatch):
    import app.forecasting.benchmark_final as module
    design = json.loads(DEFAULT_DESIGN.read_text())
    design.update(testStartUtc="2026-07-28T00:00:00Z", testEndUtcExclusive="2026-07-28T18:00:00Z")
    design["replay"].update(seeds=[42], instanceTypes=["test.cpu"])
    path = tmp_path / "design.json"
    payload = json.dumps(design).encode()
    path.write_bytes(payload)
    monkeypatch.setattr(module, "DEFAULT_DESIGN", path)
    identity = SeriesIdentity("r", "z", "test.cpu", "Linux/UNIX", "CPU")
    data = PriceDataset(datetime(2026, 7, 28, tzinfo=timezone.utc), 24,
        [PriceSeries(identity, {t: .1 for t in range(24)})], "test", "SIMULATED")
    monkeypatch.setattr(module, "load_prepared_dataset", lambda _: data)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([dict(region="r", instanceType="test.cpu", resourceType="CPU", allocationGranularityUnits=4)]))
    forecast_dir = tmp_path / "forecast"
    forecast_dir.mkdir()
    (forecast_dir / "report.json").write_text(json.dumps(dict(designSha256=hashlib.sha256(payload).hexdigest(), datasetSha256="test")))
    with (forecast_dir / "predictions.jsonl").open("w") as stream:
        for t in range(12):
            for h in range(1, 7):
                stream.write(json.dumps(dict(identity=identity.to_dict(), originSlot=t, targetSlot=t+h, prediction=.1))+"\n")
    report = run_benchmark(tmp_path, forecast_dir, tmp_path / "out", metadata)
    assert report["comparableWorkloadOutcomes"]
    assert report["mlSavingsVsNaivePct"] == 0
    assert len(report["cases"]) == 1
    case = report["cases"][0]
    assert len(case["policies"]) == 4
    for policy in case["policies"]:
        assert policy["totalSpendUsd"] == pytest.approx(sum(j["costUsd"] for j in policy["jobs"]))
        assert policy["completedJobs"] == case["jobCount"]
        assert policy["missedDeadlines"] == policy["failedJobs"] == policy["unfinishedJobs"] == 0
    assert report["provenance"]["capacity"] == "SIMULATED"
