"""Prespecified alternative-model comparison on development data only."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

from app.forecasting.alternative_models import AlternativePriceModel, gated_predictions
from app.forecasting.collect_spot import stamp
from app.forecasting.evaluate import compare_predictions, evaluation_report
from app.forecasting.experiment_features import feature_profile
from app.forecasting.experiments import walk_forward_folds
from app.forecasting.training_data import PriceSeries, build_examples, chronological_partitions, load_prepared_dataset

DEFAULT_DESIGN = Path(__file__).resolve().parents[3]/"data/alternative-model-design.json"


def choose_variant(variants):
    eligible = [v for v in variants if v["eligibleForSelection"]]
    return min(eligible, key=lambda v: (v["earlier"]["overall"]["ml"]["mae"], v["id"])) if eligible else None


def run_comparison(dataset_directory, report_directory, *, design_path=DEFAULT_DESIGN):
    if report_directory.exists():
        raise ValueError("Use a fresh report directory")
    payload = design_path.read_bytes()
    design = json.loads(payload)
    if design["schemaVersion"] != "alternative-price-model-design-v1" or design["featureProfile"] != "extended168" or design["architecture"] != "per-horizon":
        raise ValueError("Unsupported alternative-model design")
    weights, thresholds = design["correctionWeights"], design["changeThresholds"]
    if not weights or not thresholds or any(not 0 < x <= 1 for x in weights) or any(not 0 <= x <= 1 for x in thresholds):
        raise ValueError("Invalid correction weights or thresholds")
    dataset = load_prepared_dataset(dataset_directory)
    partitions = chronological_partitions(dataset.end_slot)
    cutoff = partitions["validation"].end
    development = replace(dataset, end_slot=cutoff, series=[PriceSeries(s.identity,
        {slot: value for slot, value in s.prices.items() if slot < cutoff}) for s in dataset.series])
    builder, schema, feature_hash, lookback = feature_profile(design["featureProfile"])
    def examples(partition):
        return build_examples(development, partition, feature_builder=builder,
                              feature_lookback=lookback, eligibility_lookback=lookback)
    folds = walk_forward_folds(partitions["train"].end, design["walkForwardFractions"])
    caches, earlier, slices, summaries = [], [], [], []
    for train_part, val_part in folds:
        training, train_summary = examples(train_part)
        validation, val_summary = examples(val_part)
        if train_summary["lastTargetSlot"] >= val_summary["firstOriginSlot"]:
            raise ValueError("Training labels overlap validation origins")
        slices.append((len(earlier), len(earlier)+len(validation)))
        earlier.extend(validation)
        caches.append((training, validation))
        summaries.append(dict(training=train_summary, validation=val_summary))
    variants = []
    tolerance, minimum_wins = design["absoluteMaeTolerance"], design["minimumImprovingFolds"]
    if tolerance < 0 or not 1 <= minimum_wins <= len(folds):
        raise ValueError("Invalid selection rule")
    for family, parameters in design["models"].items():
        deltas, probabilities = [], []
        for index, (training, validation) in enumerate(caches, 1):
            model = AlternativePriceModel(family, parameters, seed=design["seed"]).fit(training)
            d, p = model.components([e.features for e in validation])
            deltas.extend(d.tolist())
            probabilities.extend(p.tolist())
            print(f"{family}: completed earlier fold {index}/{len(folds)}", flush=True)
        gates = thresholds if family == "two-stage" else [0.0]
        for weight in weights:
            for threshold in gates:
                predictions = gated_predictions(earlier, deltas, probabilities, weight=weight, threshold=threshold)
                overall = compare_predictions(earlier, predictions)
                metrics = [compare_predictions(earlier[a:b], predictions[a:b]) for a, b in slices]
                wins = sum(m["ml"]["mae"] < m["persistence"]["mae"]-tolerance for m in metrics)
                variants.append(dict(id=f"{family}-weight-{weight:g}-gate-{threshold:g}", family=family,
                    correctionWeight=weight, changeThreshold=threshold,
                    earlier=dict(overall=overall, folds=metrics, improvingFolds=wins),
                    eligibleForSelection=wins >= minimum_wins and overall["ml"]["mae"] < overall["persistence"]["mae"]-tolerance))
    frozen = choose_variant(variants)
    frozen_id = frozen["id"] if frozen else "persistence"
    print(f"Frozen earlier-fold selection: {frozen_id}", flush=True)
    training, training_summary = examples(partitions["train"])
    validation, validation_summary = examples(partitions["validation"])
    predictions_by_variant = {}
    for family, parameters in design["models"].items():
        model = AlternativePriceModel(family, parameters, seed=design["seed"]).fit(training)
        deltas, probabilities = model.components([e.features for e in validation])
        for variant in (v for v in variants if v["family"] == family):
            predictions = gated_predictions(validation, deltas, probabilities,
                weight=variant["correctionWeight"], threshold=variant["changeThreshold"])
            predictions_by_variant[variant["id"]] = predictions
            variant["laterDevelopment"] = evaluation_report(validation, predictions)
        print(f"{family}: completed later development comparison", flush=True)
    selected_predictions = predictions_by_variant[frozen_id] if frozen else [e.current_price for e in validation]
    selected_metrics = compare_predictions(validation, selected_predictions)
    passed = frozen is not None and selected_metrics["ml"]["mae"] < selected_metrics["persistence"]["mae"]-tolerance
    report = dict(schemaVersion="alternative-price-model-results-v1", design=design,
        designSha256=hashlib.sha256(payload).hexdigest(), datasetSha256=dataset.sha256,
        dataKind=dataset.data_kind, originUtc=stamp(dataset.origin), featureSchema=schema,
        featureCodeSha256=feature_hash,
        implementationSha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("alternative_models.py", "compare_models.py")},
        trainingSummary=training_summary, laterValidationSummary=validation_summary, folds=summaries,
        frozenSelection=frozen_id, selectedLaterDevelopment=selected_metrics,
        provisionalDevelopmentPass=passed,
        recommendation="CANDIDATE_FOR_FROZEN_FINAL_EVALUATION" if passed else "KEEP_PERSISTENCE",
        calibration={"status": "RESERVED_NOT_USED"}, test={"status": "RESERVED_NOT_EVALUATED"},
        protectedFromSlot=cutoff, earliestHistoricalDeploymentSlot=cutoff,
        variants=sorted(variants,key=lambda v: (v["earlier"]["overall"]["ml"]["mae"],v["id"])),
        packageVersions={name:version(name) for name in ("scikit-learn", "lightgbm", "numpy", "scipy", "threadpoolctl")},
        pythonVersion=platform.python_version(),
        limitations=["Earlier-fold scores are model-selection scores, not independent performance estimates.",
            "The later development period was inspected before this design; all later gains are exploratory.",
            "Many alternatives have been compared on these development periods; selection optimism is expected.",
            "Price-change classifier probabilities are not calibrated or interruption-risk estimates.",
            "Only one region, one instance type and three AZ source series are represented.",
            "No final-test, scheduling-cost or statistical-significance claim is made.",
            "Fitted estimators are not serialized; this report and per-variant predictions are reproducible from the frozen recipe."])
    report_directory.mkdir(parents=True, exist_ok=False)
    (report_directory/"report.json").write_text(json.dumps(report, indent=2, sort_keys=True,allow_nan=False)+"\n")
    (report_directory/"design.json").write_bytes(payload)
    with (report_directory/"later-predictions.jsonl").open("x") as stream:
        for i, e in enumerate(validation):
            stream.write(json.dumps(dict(identity=e.identity.to_dict(), originSlot=e.origin_slot,
                targetSlot=e.target_slot, horizon=e.horizon, actual=e.target_price,
                persistence=e.current_price, predictions={key:values[i] for key,values in predictions_by_variant.items()}),
                sort_keys=True,allow_nan=False)+"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    args = parser.parse_args()
    try:
        report = run_comparison(args.dataset, args.report_output, design_path=args.design)
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1, f"Comparison failed: {exc}\n")
    print(f"Frozen selection: {report['frozenSelection']}; {report['recommendation']}")
    print("Calibration and final test remain unused.")


if __name__ == "__main__":
    main()
