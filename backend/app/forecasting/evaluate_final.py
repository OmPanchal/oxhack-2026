"""One frozen final-test recipe; no tuning, calibration or production promotion."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

from app.forecasting.collect_spot import utc
from app.forecasting.contracts import slot_for_timestamp
from app.forecasting.evaluate_expanded import evaluate_period
from app.forecasting.training_data import Partition, PriceSeries, load_prepared_dataset

DEFAULT_DESIGN = Path(__file__).resolve().parents[3] / "data/final-evaluation-design.json"


def run_final(dataset_directory, report_directory, *, design_path=DEFAULT_DESIGN):
    if report_directory.exists():
        raise ValueError("Use a fresh final report directory; never overwrite results")
    payload = design_path.read_bytes()
    design = json.loads(payload)
    if design["schemaVersion"] != "frozen-final-price-evaluation-v1":
        raise ValueError("Unsupported final evaluation design")
    incumbent = json.loads(DEFAULT_DESIGN.with_name("expanded-evaluation-design.json").read_text())
    for key in ("seed", "featureProfile", "modelGrouping", "correctionWeight", "parameters"):
        if design[key] != incumbent[key]:
            raise ValueError("Final recipe differs from the frozen development incumbent")
    if not utc(design["trainingEndUtcExclusive"]) < utc(design["testStartUtc"]) < utc(design["testEndUtcExclusive"]):
        raise ValueError("Chronological final boundaries required")
    dataset = load_prepared_dataset(dataset_directory)
    if dataset.sha256 != design["datasetSha256"]:
        raise ValueError("Final dataset fingerprint differs from the frozen design")
    train_end = slot_for_timestamp(dataset.origin, design["trainingEndUtcExclusive"])
    test_start = slot_for_timestamp(dataset.origin, design["testStartUtc"])
    test_end = slot_for_timestamp(dataset.origin, design["testEndUtcExclusive"])
    if not 168 < train_end < test_start < test_end <= dataset.end_slot:
        raise ValueError("Final partitions outside dataset")
    bounded = replace(dataset, end_slot=test_end, series=[PriceSeries(s.identity,
        {slot: price for slot, price in s.prices.items() if slot < test_end}) for s in dataset.series])
    report_directory.mkdir(parents=True, exist_ok=False)
    # Persist the exact recipe and a start receipt before any final scoring.
    (report_directory / "design.json").write_bytes(payload)
    (report_directory / "started.json").write_text(json.dumps(dict(
        designSha256=hashlib.sha256(payload).hexdigest(), datasetSha256=dataset.sha256,
        status="FINAL_TEST_OPENED_DO_NOT_TUNE_ON_THIS_PERIOD"), indent=2)+"\n")
    results, examples, predictions = evaluate_period(bounded, Partition("train", 0, train_end),
        Partition("final-test", test_start, test_end), design)
    with (report_directory / "predictions.jsonl").open("x") as stream:
        for e, prediction in zip(examples, predictions):
            assert e.target_slot < test_end
            stream.write(json.dumps(dict(identity=e.identity.to_dict(), originSlot=e.origin_slot,
                targetSlot=e.target_slot, horizon=e.horizon, actual=e.target_price,
                persistence=e.current_price, prediction=prediction), sort_keys=True, allow_nan=False)+"\n")
    report = dict(schemaVersion="frozen-final-price-results-v1", design=design,
        designSha256=hashlib.sha256(payload).hexdigest(), datasetSha256=dataset.sha256,
        originUtc=dataset.origin.isoformat(), dataKind=dataset.data_kind, poolCount=len(dataset.series),
        partitions=dict(training=Partition("train", 0, train_end).to_dict(),
                        test=Partition("final-test", test_start, test_end).to_dict()), results=results,
        passesByResource={r: m["overall"]["ml"]["mae"] < m["overall"]["persistence"]["mae"]
                          for r, m in results["metrics"].items()},
        implementationSha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("evaluate_final.py", "evaluate_expanded.py", "complex_models.py", "alternative_models.py", "training_data.py")},
        packageVersions={name: version(name) for name in ("lightgbm", "scikit-learn", "numpy", "scipy")},
        limitations=["This final period has now been evaluated and cannot be called untouched for later tuning.",
            "Frozen training ends before development/calibration; B200 remains an unsupported-pool persistence fallback.",
            "Overlapping horizons and related sizes/AZs are correlated, with one region only.",
            "Forecast error improvement is not compute savings or calibrated deadline reliability.",
            "No automatic deployment, default change or uncertainty calibration is performed."])
    (report_directory / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print("Final MAE improvements:", {r: m["overall"]["maeImprovementPct"] for r, m in results["metrics"].items()}, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    parser.add_argument("--design", default=DEFAULT_DESIGN, type=Path)
    args = parser.parse_args()
    try:
        run_final(args.dataset, args.report_output, design_path=args.design)
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1, f"Final evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
