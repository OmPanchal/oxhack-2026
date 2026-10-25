"""Frozen ablations, expanding-window model selection, and development confirmation."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
import hashlib
from importlib.metadata import version
from itertools import product
import json
import math
from pathlib import Path
import platform

from app.forecasting.collect_spot import stamp
from app.forecasting.evaluate import compare_predictions, evaluation_report
from app.forecasting.experiment_bundle import ExperimentBundle
from app.forecasting.experiment_features import feature_profile
from app.forecasting.price_model import LightGBMPriceModel
from app.forecasting.training_data import (
    Partition, PriceSeries, build_examples, chronological_partitions, load_prepared_dataset,
)
from app.market.features import SeriesIdentity

DEFAULT_DESIGN = Path(__file__).resolve().parents[3]/"data/forecast-experiment-design.json"


def walk_forward_folds(training_end: int, fractions: list[float]) -> list[tuple[Partition, Partition]]:
    if len(fractions) < 3 or fractions != sorted(set(fractions)) or fractions[0] <= 0 or fractions[-1] != 1:
        raise ValueError("Ordered unique walk-forward fractions ending at one required")
    boundaries = [int(training_end * fraction) for fraction in fractions]
    if len(set(boundaries)) != len(boundaries):
        raise ValueError("Fold boundaries collapse at this dataset size")
    return [(Partition(f"fold-{i}-train", 0, lower), Partition(f"fold-{i}-validation", lower, upper))
            for i, (lower, upper) in enumerate(zip(boundaries, boundaries[1:]), 1)]


def blend_predictions(examples: list, raw: list[float], weights: dict[str, float]) -> list[float]:
    if len(examples) != len(raw):
        raise ValueError("Prediction/sample count mismatch")
    if set(weights) != {str(h) for h in range(1, 7)} or any(
        not math.isfinite(weight) or not 0 <= weight <= 1 for weight in weights.values()
    ):
        raise ValueError("Invalid correction weights")
    return [max(0.0, example.current_price + weights[str(example.horizon)] * (value-example.current_price))
            for example, value in zip(examples, raw)]


def _score(examples: list, predictions: list[float], slices: list[tuple[int, int]], tolerance: float) -> dict:
    overall = compare_predictions(examples, predictions)
    fold_metrics = [compare_predictions(examples[lower:upper], predictions[lower:upper]) for lower, upper in slices]
    wins = sum(m["ml"]["mae"] < m["persistence"]["mae"] - tolerance for m in fold_metrics)
    return dict(overall=overall, folds=fold_metrics, improvingFolds=wins,
                beatsPersistence=overall["ml"]["mae"] < overall["persistence"]["mae"] - tolerance)


def choose_horizon_weights(examples: list, raw: list[float], slices: list[tuple[int, int]],
                           grid: list[float], minimum_wins: int, tolerance: float) -> dict[str, float]:
    """Choose all shrinkage weights from OOF outcomes only, before confirmation."""
    weights = {}
    for horizon in range(1, 7):
        indices = [i for i, example in enumerate(examples) if example.horizon == horizon]
        subset = [examples[i] for i in indices]
        candidates = []
        for weight in grid:
            predictions = [examples[i].current_price + weight * (raw[i]-examples[i].current_price) for i in indices]
            metrics = compare_predictions(subset, predictions)
            wins = 0
            for lower, upper in slices:
                fold_indices = [i for i in indices if lower <= i < upper]
                folded = compare_predictions([examples[i] for i in fold_indices], [
                    examples[i].current_price + weight*(raw[i]-examples[i].current_price) for i in fold_indices])
                wins += folded["ml"]["mae"] < folded["persistence"]["mae"] - tolerance
            if weight == 0 or (wins >= minimum_wins and metrics["ml"]["mae"] < metrics["persistence"]["mae"] - tolerance):
                candidates.append((metrics["ml"]["mae"], weight))
        weights[str(horizon)] = min(candidates)[1]
    return weights


def _fit(config: dict, parameters: dict, training: list, *, seed: int) -> dict:
    _, schema, digest, _ = feature_profile(config["featureProfile"])
    keys = ("pooled",) if config["architecture"] == "pooled" else tuple(map(str, range(1, 7)))
    models = {}
    for key in keys:
        samples = training if key == "pooled" else [e for e in training if e.horizon == int(key)]
        models[key] = LightGBMPriceModel.fit(samples, parameters, seed=seed,
                                            feature_schema=schema, feature_code_sha256=digest)
    return models


def _raw_predictions(models: dict, config: dict, examples: list) -> list[float]:
    if config["architecture"] == "pooled":
        return models["pooled"].predict_examples(examples)
    result = [0.0] * len(examples)
    for horizon in range(1, 7):
        indices = [i for i, example in enumerate(examples) if example.horizon == horizon]
        values = models[str(horizon)].predict_examples([examples[i] for i in indices])
        for index, value in zip(indices, values):
            result[index] = value
    return result


def run_experiments(dataset_directory: Path, model_directory: Path, report_directory: Path,
                    *, design_path: Path = DEFAULT_DESIGN, seed: int = 42) -> dict:
    if model_directory.exists() or report_directory.exists():
        raise ValueError("Use new model/report directories")
    a, b = model_directory.resolve(), report_directory.resolve()
    if a == b or a in b.parents or b in a.parents:
        raise ValueError("Model/report directories must be separate and nonnested")
    design_bytes = design_path.read_bytes()
    design = json.loads(design_bytes)
    if design["schemaVersion"] != "forecast-experiment-design-v1":
        raise ValueError("Unsupported experiment design")
    grid = design["correctionWeights"]
    if not grid or 0 not in grid or 1 not in grid or len(set(grid)) != len(grid) or any(
        type(w) not in (int, float) or not math.isfinite(w) or not 0 <= w <= 1 for w in grid
    ):
        raise ValueError("Weight grid must contain zero and one, within [0,1]")
    dataset = load_prepared_dataset(dataset_directory)
    partitions = chronological_partitions(dataset.end_slot)
    training_end, confirmation_end = partitions["train"].end, partitions["validation"].end
    # Make protected periods inaccessible to feature/example builders after loading.
    development = replace(dataset, end_slot=confirmation_end, series=[
        PriceSeries(s.identity, {slot: value for slot, value in s.prices.items() if slot < confirmation_end})
        for s in dataset.series])
    folds = walk_forward_folds(training_end, design["walkForwardFractionsOfOriginalTraining"])
    minimum_wins, tolerance = design["minimumImprovingFolds"], design["absoluteMaeTolerance"]
    if type(minimum_wins) is not int or not 1 <= minimum_wins <= len(folds) or tolerance < 0:
        raise ValueError("Invalid fold-win rule or MAE tolerance")
    configurations = []
    for profile, architecture, regularization in product(
        design["featureProfiles"], design["architectures"], design["regularization"]
    ):
        if architecture not in ("pooled", "per-horizon"):
            raise ValueError("Unsupported model architecture")
        configurations.append(dict(id=f"{profile}-{architecture}-{regularization}",
                                   featureProfile=profile, architecture=architecture, regularization=regularization))
    caches, oof_examples, slices = {}, {}, None
    common_keys = None
    for profile in design["featureProfiles"]:
        builder, _, _, lookback = feature_profile(profile)
        cached, all_examples, bounds = [], [], []
        for training, validation in folds:
            train_rows, train_summary = build_examples(development, training, feature_builder=builder,
                feature_lookback=lookback, eligibility_lookback=design["commonEligibilityLookback"])
            val_rows, val_summary = build_examples(development, validation, feature_builder=builder,
                feature_lookback=lookback, eligibility_lookback=design["commonEligibilityLookback"])
            if train_summary["lastTargetSlot"] >= val_summary["firstOriginSlot"]:
                raise ValueError("Fold training labels overlap forecast origins")
            bounds.append((len(all_examples), len(all_examples)+len(val_rows)))
            all_examples.extend(val_rows)
            cached.append((train_rows, val_rows, train_summary, val_summary))
        keys = [(e.identity, e.origin_slot, e.target_slot, e.target_price) for e in all_examples]
        if common_keys is not None and keys != common_keys:
            raise ValueError("Feature profiles have unequal evaluation cohorts")
        common_keys, slices = keys, bounds
        caches[profile], oof_examples[profile] = cached, all_examples
    variants, raw_oof = [], {}
    for config in configurations:
        raw = []
        for index, (train_rows, val_rows, _, _) in enumerate(caches[config["featureProfile"]], 1):
            models = _fit(config, design["regularization"][config["regularization"]], train_rows, seed=seed)
            raw.extend(_raw_predictions(models, config, val_rows))
            print(f"Completed {config['id']} walk-forward fold {index}/{len(folds)}", flush=True)
        raw_oof[config["id"]] = raw
        examples = oof_examples[config["featureProfile"]]
        weight_sets = [(f"global-{weight:g}", {str(h): weight for h in range(1, 7)}) for weight in grid if weight > 0]
        if design["includePerHorizonWeights"]:
            weight_sets.append(("per-horizon-weights", choose_horizon_weights(
                examples, raw, slices, grid, minimum_wins, tolerance)))
        for name, weights in weight_sets:
            predictions = blend_predictions(examples, raw, weights)
            score = _score(examples, predictions, slices, tolerance)
            variants.append(dict(id=f"{config['id']}-{name}", config=config, correctionWeights=weights,
                                 outOfFold=score,
                                 eligibleForSelection=score["beatsPersistence"] and score["improvingFolds"] >= minimum_wins))
    eligible = [v for v in variants if v["eligibleForSelection"]]
    ranking = lambda v: (v["outOfFold"]["overall"]["ml"]["mae"],
                         sum(v["correctionWeights"].values()), v["id"])
    selected = min(eligible or variants, key=ranking)
    selected_id = selected["id"] if eligible else "persistence"
    print(f"Frozen OOF selection: {selected_id}; beginning development confirmation", flush=True)
    confirmation_cache = {}
    for profile in design["featureProfiles"]:
        builder, _, _, lookback = feature_profile(profile)
        training, train_summary = build_examples(development, partitions["train"], feature_builder=builder,
            feature_lookback=lookback, eligibility_lookback=design["commonEligibilityLookback"])
        validation, val_summary = build_examples(development, partitions["validation"], feature_builder=builder,
            feature_lookback=lookback, eligibility_lookback=design["commonEligibilityLookback"])
        confirmation_cache[profile] = training, validation, train_summary, val_summary
    confirmation_keys = None
    selected_models = selected_predictions = selected_examples = None
    for config in configurations:
        training, validation, train_summary, _ = confirmation_cache[config["featureProfile"]]
        keys = [(e.identity, e.origin_slot, e.target_slot, e.target_price) for e in validation]
        if confirmation_keys is not None and keys != confirmation_keys:
            raise ValueError("Unequal confirmation cohorts")
        confirmation_keys = keys
        models = _fit(config, design["regularization"][config["regularization"]], training, seed=seed)
        raw = _raw_predictions(models, config, validation)
        for variant in (v for v in variants if v["config"]["id"] == config["id"]):
            predictions = blend_predictions(validation, raw, variant["correctionWeights"])
            variant["confirmation"] = compare_predictions(validation, predictions)
            if variant["id"] == selected["id"]:
                selected_models, selected_predictions, selected_examples = models, predictions, validation
        print(f"Completed {config['id']} development confirmation", flush=True)
    trained_identities = set.intersection(*[
        {SeriesIdentity(**row) for row in model.metadata["seriesIdentities"]}
        for model in selected_models.values()])
    metadata = dict(originUtc=stamp(dataset.origin), datasetSha256=dataset.sha256, dataKind=dataset.data_kind,
                    seriesIdentities=[identity.to_dict() for identity in sorted(trained_identities)],
                    availableFromSlot=confirmation_end, trainingMaxTargetSlot=training_end-1,
                    selectedUsingOutOfFoldThroughSlot=training_end-1,
                    promotionAssessedThroughSlot=confirmation_end-1,
                    experimentDesignSha256=hashlib.sha256(design_bytes).hexdigest(), seed=seed,
                    selectionStatus="OOF_SELECTED" if eligible else "EXPERIMENTAL_ONLY_PERSISTENCE_PREFERRED")
    for model in selected_models.values():
        model.metadata.update(metadata)
    bundle = ExperimentBundle(selected_models, selected["config"], selected["correctionWeights"], metadata)
    artifact = bundle.save(model_directory)
    confirmation = selected["confirmation"]
    confirmed = bool(eligible) and confirmation["ml"]["mae"] < confirmation["persistence"]["mae"] - tolerance
    first_profile = design["featureProfiles"][0]
    reference = oof_examples[first_profile]
    baseline = _score(reference, [e.current_price for e in reference], slices, tolerance)
    report = dict(schemaVersion="forecast-experiments-v1", design=design,
                  designSha256=hashlib.sha256(design_bytes).hexdigest(), datasetSha256=dataset.sha256,
                  dataKind=dataset.data_kind, seed=seed, commonEligibilityLookback=design["commonEligibilityLookback"],
                  protectedFromSlot=confirmation_end,
                  folds=[dict(training=train.to_dict(), validation=val.to_dict(),
                              trainingSummary=caches[first_profile][i][2],
                              validationSummary=caches[first_profile][i][3]) for i, (train, val) in enumerate(folds)],
                  persistenceOutOfFold=baseline, frozenSelection=selected_id, artifactVariant=selected["id"],
                  modelVersion=artifact["modelVersion"], selectedWeights=selected["correctionWeights"],
                  recommendedForecastMode="ML" if confirmed else "NAIVE", provisionalConfirmationPassed=confirmed,
                  selectedOutOfFold=selected["outOfFold"],
                  selectedConfirmation=evaluation_report(selected_examples, selected_predictions),
                  confirmationStatus="PREVIOUSLY_INSPECTED_DEVELOPMENT_VALIDATION_NOT_FINAL_TEST",
                  variants=sorted(variants, key=ranking),
                  calibration={"status": "RESERVED_NOT_USED"}, test={"status": "RESERVED_NOT_EVALUATED"},
                  packageVersions={name: version(name) for name in ("lightgbm", "scikit-learn", "numpy", "scipy")},
                  pythonVersion=platform.python_version(),
                  limitations=["All results are development/model-selection evidence, not final test performance.",
                               "The original validation period was inspected before these experiments were designed.",
                               "OOF scores select configuration and weights; they are optimistic selection estimates.",
                               "Every variant uses the same 168-hour eligibility rule to avoid cohort bias.",
                               "No scheduling cost or savings benchmark was performed."])
    report_directory.mkdir(parents=True, exist_ok=False)
    (report_directory/"report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    (report_directory/"design.json").write_bytes(design_bytes)
    with (report_directory/"selected-confirmation-predictions.jsonl").open("x") as stream:
        for example, prediction in zip(selected_examples, selected_predictions):
            stream.write(json.dumps(dict(example.identity.to_dict(), generatedAtSlot=example.origin_slot,
                targetSlot=example.target_slot, horizonHours=example.horizon,
                actualPriceUsdPerUnitHour=example.target_price, persistencePriceUsdPerUnitHour=example.current_price,
                predictedPriceUsdPerUnitHour=prediction, actualDataKind=dataset.data_kind), sort_keys=True)+"\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--model-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        report = run_experiments(args.dataset, args.model_output, args.report_output,
                                 design_path=args.design, seed=args.seed)
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1, f"Experiments failed: {exc}\n")
    print(f"Frozen selection: {report['frozenSelection']}; recommendation: {report['recommendedForecastMode']}")
    print(f"OOF improvement: {report['selectedOutOfFold']['overall']['maeImprovementPct']:.4f}%; "
          f"confirmation improvement: {report['selectedConfirmation']['overall']['maeImprovementPct']:.4f}%")
    print("Calibration and final test remain unused.")


if __name__ == "__main__":
    main()
