"""Frozen, chronological comparison of complex models against the incumbent."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

import numpy as np

from app.forecasting.complex_models import ComplexPriceModel
from app.forecasting.evaluate import compare_predictions, evaluation_report
from app.forecasting.experiment_features import feature_profile
from app.forecasting.experiments import walk_forward_folds
from app.forecasting.training_data import PriceSeries, build_examples, chronological_partitions, load_prepared_dataset

DEFAULT_DESIGN = Path(__file__).resolve().parents[3] / "data/complex-model-design.json"


def variant_predictions(examples, deltas, design):
    current = np.array([e.current_price for e in examples])
    if set(deltas) != set(design["models"]) or any(len(v) != len(examples) for v in deltas.values()):
        raise ValueError("Incomplete model predictions")
    result = {}
    for family, values in deltas.items():
        weights = [.5] if family == "lightgbm-reference" else design["correctionWeights"]
        for weight in weights:
            result[f"{family}-weight-{weight:g}"] = np.maximum(0, current + weight * np.array(values)).tolist()
    for name, members in design["ensembles"].items():
        delta = np.mean([deltas[member] for member in members], axis=0)
        result[name] = np.maximum(0, current + design["ensembleCorrectionWeight"] * delta).tolist()
    if any(not np.isfinite(values).all() for values in result.values()):
        raise ValueError("Nonfinite predictions")
    return result


def relative_metrics(examples, predictions, reference):
    # Reuse metric definitions, replacing only the comparator's prediction array.
    from app.forecasting.evaluate import regression_metrics
    actual = [e.target_price for e in examples]
    candidate = regression_metrics(actual, predictions)
    incumbent = regression_metrics(actual, reference)
    return dict(maeImprovementPct=100 * (1 - candidate["mae"] / incumbent["mae"]) if incumbent["mae"] else None,
                rmseImprovementPct=100 * (1 - candidate["rmse"] / incumbent["rmse"]) if incumbent["rmse"] else None)


def select_variant(variants, incumbent):
    eligible = [v for v in variants if v["eligibleToReplaceIncumbent"]]
    return min(eligible, key=lambda v: (v["earlier"]["overall"]["ml"]["mae"], v["id"]))["id"] if eligible else incumbent


def save_predictions(path, examples, predictions):
    with path.open("x") as stream:
        for i, e in enumerate(examples):
            stream.write(json.dumps(dict(identity=e.identity.to_dict(), originSlot=e.origin_slot,
                targetSlot=e.target_slot, horizon=e.horizon, actual=e.target_price,
                persistence=e.current_price, predictions={key: values[i] for key, values in predictions.items()}),
                sort_keys=True, allow_nan=False) + "\n")


def run_comparison(dataset_directory, report_directory, *, design_path=DEFAULT_DESIGN):
    if report_directory.exists():
        raise ValueError("Use a fresh report directory")
    payload = design_path.read_bytes()
    design = json.loads(payload)
    if design["schemaVersion"] != "complex-price-model-design-v1" or design["featureProfile"] != "extended168":
        raise ValueError("Unsupported complex-model design")
    weights = design["correctionWeights"] + [design["ensembleCorrectionWeight"]]
    if not weights or any(type(w) not in (int, float) or not np.isfinite(w) or not 0 < w <= 1 for w in weights):
        raise ValueError("Invalid correction weights")
    if "lightgbm-reference" not in design["models"]:
        raise ValueError("Incumbent model required")
    for members in design["ensembles"].values():
        if not members or len(set(members)) != len(members) or not set(members) <= set(design["models"]):
            raise ValueError("Invalid ensemble membership")
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
    tolerance, minimum_wins = design["absoluteMaeTolerance"], design["minimumImprovingFolds"]
    if not np.isfinite(tolerance) or tolerance < 0 or not 1 <= minimum_wins <= len(folds):
        raise ValueError("Invalid selection thresholds")
    earlier, slices, summaries, fit_warnings = [], [], [], []
    deltas = {name: [] for name in design["models"]}
    for index, (train_part, val_part) in enumerate(folds, 1):
        training, train_summary = examples(train_part)
        validation, val_summary = examples(val_part)
        if train_summary["lastTargetSlot"] >= val_summary["firstOriginSlot"]:
            raise ValueError("Overlapping training labels and validation origins")
        slices.append((len(earlier), len(earlier) + len(validation)))
        earlier.extend(validation)
        summaries.append(dict(training=train_summary, validation=val_summary))
        for family, parameters in design["models"].items():
            model = ComplexPriceModel(family, parameters, seed=design["seed"]).fit(training)
            deltas[family].extend(model.predict_deltas(validation))
            fit_warnings.extend(dict(family=family, period=f"earlier-{index}", **w) for w in model.fit_warnings)
            print(f"{family}: earlier fold {index}/{len(folds)} complete", flush=True)
    predictions = variant_predictions(earlier, deltas, design)
    incumbent = design["incumbent"]
    reference = predictions[incumbent]
    variants = []
    for name, values in predictions.items():
        overall = compare_predictions(earlier, values)
        folded = [compare_predictions(earlier[a:b], values[a:b]) for a, b in slices]
        reference_folds = [relative_metrics(earlier[a:b], values[a:b], reference[a:b]) for a, b in slices]
        reference_maes = [compare_predictions(earlier[a:b], reference[a:b])["ml"]["mae"] for a, b in slices]
        wins = sum(m["ml"]["mae"] < ref - tolerance for m, ref in zip(folded, reference_maes))
        earlier_metrics = dict(overall=overall, folds=folded, versusIncumbent=relative_metrics(earlier, values, reference),
                               foldsVersusIncumbent=reference_folds, improvingFoldsAgainstIncumbent=wins,
                               improvingFoldsAgainstPersistence=sum(m["maeImprovementPct"] is not None and m["maeImprovementPct"] > 0 for m in folded))
        eligible = (name != incumbent and wins >= minimum_wins and
                    overall["ml"]["mae"] < compare_predictions(earlier, reference)["ml"]["mae"] - tolerance and
                    overall["ml"]["mae"] < overall["persistence"]["mae"] - tolerance)
        variants.append(dict(id=name, earlier=earlier_metrics, eligibleToReplaceIncumbent=eligible))
    frozen = select_variant(variants, incumbent)
    print(f"Frozen earlier selection: {frozen}", flush=True)
    training, training_summary = examples(partitions["train"])
    validation, validation_summary = examples(partitions["validation"])
    if training_summary["lastTargetSlot"] >= validation_summary["firstOriginSlot"]:
        raise ValueError("Overlapping later development partition")
    later_deltas = {}
    for family, parameters in design["models"].items():
        model = ComplexPriceModel(family, parameters, seed=design["seed"]).fit(training)
        later_deltas[family] = model.predict_deltas(validation)
        fit_warnings.extend(dict(family=family, period="later-development", **w) for w in model.fit_warnings)
        print(f"{family}: later development complete", flush=True)
    later_predictions = variant_predictions(validation, later_deltas, design)
    for variant in variants:
        values = later_predictions[variant["id"]]
        variant["laterDevelopment"] = evaluation_report(validation, values)
        variant["laterVersusIncumbent"] = relative_metrics(validation, values, later_predictions[incumbent])
    selected = next(v for v in variants if v["id"] == frozen)
    report = dict(schemaVersion="complex-price-model-results-v1", design=design,
        designSha256=hashlib.sha256(payload).hexdigest(), datasetSha256=dataset.sha256, dataKind=dataset.data_kind,
        featureSchema=schema, featureCodeSha256=feature_hash, originUtc=dataset.origin.isoformat(),
        implementationSha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ("complex_models.py", "compare_complex_models.py")},
        folds=summaries, trainingSummary=training_summary, laterValidationSummary=validation_summary,
        incumbent=incumbent, frozenSelection=frozen,
        recommendation="KEEP_INCUMBENT" if frozen == incumbent else "CANDIDATE_FOR_FROZEN_FINAL_EVALUATION",
        selectedLater=selected["laterDevelopment"]["overall"], selectedLaterVersusIncumbent=selected["laterVersusIncumbent"],
        variants=sorted(variants, key=lambda v: (v["earlier"]["overall"]["ml"]["mae"], v["id"])),
        fitWarnings=fit_warnings, protectedFromSlot=cutoff,
        calibration={"status": "RESERVED_NOT_USED"}, test={"status": "RESERVED_NOT_EVALUATED"},
        packageVersions={name: version(name) for name in ("scikit-learn", "lightgbm", "numpy", "scipy", "threadpoolctl")},
        pythonVersion=platform.python_version(),
        limitations=["All scores are development evidence; both earlier and later periods have previously informed experiments.",
            "Selection uses earlier folds only; later results do not change the frozen choice.",
            "Overlapping horizons and related zones are correlated; no significance claim is made.",
            "One region, one instance type, three AZs; no cross-region or hardware-generalization evidence.",
            "MAE is the selection metric; neural, kernel and forest estimators optimize different training losses.",
            "No risk probabilities, scheduling savings, final-test results or deployment changes are produced.",
            "Fitted estimators remain in memory; reproducibility artifacts store recipe and predictions, not serialized weights."])
    report_directory.mkdir(parents=True, exist_ok=False)
    (report_directory / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (report_directory / "design.json").write_bytes(payload)
    save_predictions(report_directory / "earlier-predictions.jsonl", earlier, predictions)
    save_predictions(report_directory / "later-predictions.jsonl", validation, later_predictions)
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
        parser.exit(1, f"Complex-model comparison failed: {exc}\n")
    print(f"Frozen selection: {report['frozenSelection']}; {report['recommendation']}")
    print("Calibration and final test remain unused.")


if __name__ == "__main__":
    main()
