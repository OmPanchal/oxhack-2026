"""Train and select an initial model using only chronological train/validation data."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform

from app.forecasting.collect_spot import stamp
from app.forecasting.contracts import timestamp_for_slot
from app.forecasting.evaluate import compare_predictions, evaluation_report
from app.forecasting.price_model import LightGBMPriceModel
from app.forecasting.training_data import build_examples, chronological_partitions, load_prepared_dataset
from app.market.features import LOOKBACK_SLOTS, MAX_HORIZON

# Frozen before looking at validation results; no search over calibration/test.
CANDIDATES = (
    {"id": "small-l1", "objective": "regression_l1", "num_leaves": 7, "max_depth": 3,
     "min_data_in_leaf": 100, "learning_rate": 0.05, "num_boost_round": 120},
    {"id": "medium-l1", "objective": "regression_l1", "num_leaves": 15, "max_depth": 5,
     "min_data_in_leaf": 50, "learning_rate": 0.05, "num_boost_round": 180},
    {"id": "medium-l2", "objective": "regression", "num_leaves": 15, "max_depth": 5,
     "min_data_in_leaf": 100, "learning_rate": 0.03, "num_boost_round": 160},
)


def run_training(dataset_directory: Path, model_directory: Path, report_directory: Path,
                 *, seed: int = 42) -> dict:
    if model_directory.exists() or report_directory.exists():
        raise ValueError("Model/report directories must be new; existing runs are never overwritten")
    model_path, report_path = model_directory.resolve(), report_directory.resolve()
    if model_path == report_path or model_path in report_path.parents or report_path in model_path.parents:
        raise ValueError("Model and report directories must be separate, nonnested paths")
    dataset = load_prepared_dataset(dataset_directory)
    partitions = chronological_partitions(dataset.end_slot)
    # Calibration/test records are not turned into labeled examples or scored here.
    training, train_summary = build_examples(dataset, partitions["train"])
    validation, validation_summary = build_examples(dataset, partitions["validation"])
    trained_identities = {example.identity for example in training}
    if max(e.target_slot for e in training) >= min(e.origin_slot for e in validation):
        raise ValueError("Training labels overlap validation forecast origins")
    candidates = []
    best = None
    for specification in CANDIDATES:
        parameters = {key: value for key, value in specification.items() if key != "id"}
        model = LightGBMPriceModel.fit(training, parameters, seed=seed)
        predictions = model.predict_examples(validation)
        metrics = compare_predictions(validation, predictions)
        candidates.append({"candidateId": specification["id"], "parameters": parameters,
                           "validation": metrics})
        rank = (metrics["ml"]["mae"], metrics["ml"]["rmse"], specification["id"])
        if best is None or rank < best[0]:
            best = rank, model, predictions, specification["id"]
    _, model, predictions, selected_id = best
    package_versions = {name: version(name) for name in ("lightgbm", "scikit-learn", "numpy", "scipy")}
    package_versions["python"] = platform.python_version()
    split_report = [{**partition.to_dict(),
                     "startUtc": stamp(timestamp_for_slot(dataset.origin, partition.start)),
                     "endUtcExclusive": stamp(timestamp_for_slot(dataset.origin, partition.end))}
                    for partition in partitions.values()]
    model.metadata.update(schemaVersion="price-model-artifact-v1", candidateId=selected_id,
                          originUtc=stamp(dataset.origin), datasetSha256=dataset.sha256,
                          dataKind=dataset.data_kind,
                          trainingMaxTargetSlot=train_summary["lastTargetSlot"],
                          trainingEndSlotExclusive=partitions["train"].end,
                          selectedUsingValidationThroughSlot=partitions["validation"].end - 1,
                          availableFromSlot=partitions["validation"].end,
                          partitions=split_report, packageVersions=package_versions,
                          lookbackSlots=LOOKBACK_SLOTS, maximumHorizon=MAX_HORIZON)
    metadata = model.save(model_directory)
    full_metrics = evaluation_report(validation, predictions)
    improvement = full_metrics["overall"]["maeImprovementPct"]
    report = dict(schemaVersion="forecast-evaluation-v1", evaluationPeriod="VALIDATION_MODEL_SELECTION",
                  datasetSha256=dataset.sha256, dataKind=dataset.data_kind, seed=seed,
                  sampleUnit="USD per quoted resource-unit-hour; not capacity weighted",
                  modelVersion=metadata["modelVersion"], selectedCandidate=selected_id,
                  selectionRule="Lowest validation MAE, then RMSE, then candidate ID",
                  recommendedForecastMode="ML" if improvement is not None and improvement > 0 else "NAIVE",
                  validationImprovementTargetPct=5, targetMet=improvement is not None and improvement >= 5,
                  partitions=split_report, training=train_summary, validation=validation_summary,
                  validationFallbackSampleCount=sum(
                      example.identity not in trained_identities for example in validation),
                  calibration={"status": "RESERVED_NOT_USED"}, test={"status": "RESERVED_NOT_EVALUATED"},
                  candidates=candidates, metrics=full_metrics, packageVersions=package_versions,
                  limitations=["Validation selected the model; it is not final held-out test performance.",
                               "No scheduling replay or compute savings have been evaluated.",
                               "Risk probabilities and uncertainty intervals remain unknown.",
                               "Future model use requires matching origin, source pool and feature code.",
                               "API pool selection must preserve AZ and instance identity outside the API schema."])
    report_directory.mkdir(parents=True, exist_ok=False)
    (report_directory / "metrics.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    with (report_directory / "validation-predictions.jsonl").open("x") as stream:
        for example, prediction in zip(validation, predictions):
            learned = example.identity.to_dict() in metadata["seriesIdentities"]
            record = dict(example.identity.to_dict(), generatedAtSlot=example.origin_slot,
                          targetSlot=example.target_slot, horizonHours=example.horizon,
                          generatedAtUtc=stamp(timestamp_for_slot(dataset.origin, example.origin_slot)),
                          targetUtc=stamp(timestamp_for_slot(dataset.origin, example.target_slot)),
                          actualPriceUsdPerUnitHour=example.target_price,
                          persistencePriceUsdPerUnitHour=example.current_price,
                          predictedPriceUsdPerUnitHour=prediction, actualDataKind=dataset.data_kind,
                          modelVersion=metadata["modelVersion"] if learned else "persistence-v1:fallback-unsupported-pool")
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--model-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        report = run_training(args.dataset, args.model_output, args.report_output, seed=args.seed)
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.exit(1, f"Training failed: {exc}\n")
    metrics = report["metrics"]["overall"]
    print(f"Selected {report['selectedCandidate']}: validation MAE {metrics['ml']['mae']:.8f}; "
          f"persistence MAE {metrics['persistence']['mae']:.8f}.")
    print(f"Recommended forecast mode: {report['recommendedForecastMode']}; final test remains unevaluated.")
    print(f"Model: {args.model_output}; reports: {args.report_output}")


if __name__ == "__main__":
    main()
