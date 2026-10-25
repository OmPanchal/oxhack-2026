"""Evaluate the frozen incumbent on expanded hardware, preserving old UTC holdouts."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
from statistics import fmean

from app.forecasting.collect_spot import utc
from app.forecasting.complex_models import ComplexPriceModel
from app.forecasting.contracts import slot_for_timestamp, timestamp_for_slot
from app.forecasting.evaluate import compare_predictions, evaluation_report
from app.forecasting.experiment_features import feature_profile
from app.forecasting.training_data import Partition, PriceSeries, build_examples, load_prepared_dataset

DEFAULT_DESIGN = Path(__file__).resolve().parents[3] / "data/expanded-evaluation-design.json"
ORIGINAL_PROTECTED_START = utc("2026-10-01T18:00:00Z")


def grouped_report(examples, predictions):
    """Never combine CPU/vCPU-hour and GPU/device-hour absolute errors."""
    result = {}
    for resource in sorted({e.identity.resource_type for e in examples}):
        indices = [i for i, e in enumerate(examples) if e.identity.resource_type == resource]
        rows, values = [examples[i] for i in indices], [predictions[i] for i in indices]
        metrics = evaluation_report(rows, values)
        pool_metrics = [p["metrics"] for p in metrics["byPool"]]
        defined = [p["maeImprovementPct"] for p in pool_metrics if p["maeImprovementPct"] is not None]
        metrics["poolSummary"] = dict(poolCount=len(pool_metrics),
            improvedPoolCount=sum(p["ml"]["mae"] < p["persistence"]["mae"] for p in pool_metrics),
            tiedPoolCount=sum(p["ml"]["mae"] == p["persistence"]["mae"] for p in pool_metrics),
            macroMaeImprovementPct=fmean(defined) if defined else None,
            undefinedRelativeImprovementPoolCount=len(pool_metrics)-len(defined))
        metrics["unit"] = "USD/GPU-hour" if resource == "GPU" else "USD/vCPU-hour"
        metrics["byInstanceType"] = {}
        for instance in sorted({e.identity.instance_type for e in rows}):
            idx = [i for i, e in enumerate(rows) if e.identity.instance_type == instance]
            metrics["byInstanceType"][instance] = compare_predictions([rows[i] for i in idx], [values[i] for i in idx])
        result[resource] = metrics
    return result


def cached_feature_builder(builder):
    """Cache one origin's horizon-invariant statistics, never a future price.

    Both supported causal builders vary only these three calendar/horizon fields
    across horizons. Equivalence to the original builders is tested directly.
    Only the last origin is retained, so cache memory does not grow with data.
    """
    last_key, base = None, None

    def features(prices, identity, origin, current_slot, horizon):
        nonlocal last_key, base
        if type(horizon) is not int or not 1 <= horizon <= 6:
            raise ValueError("Forecast horizon must be 1–6 hours")
        key = (id(prices), identity, origin, current_slot)
        if key != last_key:
            base = builder(prices, identity, origin, current_slot, 1)
            last_key = key
        target = timestamp_for_slot(origin, current_slot + horizon)
        return dict(base, horizonHours=float(horizon),
                    targetHourSin=math.sin(2 * math.pi * target.hour / 24),
                    targetHourCos=math.cos(2 * math.pi * target.hour / 24))

    return features


def merge_summaries(summaries):
    first = dict(summaries[0])
    for field in ("sampleCount", "originCount", "skippedOriginsWithMissingHistoryOrLabels"):
        first[field] = sum(s[field] for s in summaries)
    first["firstOriginSlot"] = min(s["firstOriginSlot"] for s in summaries)
    for field in ("lastOriginSlot", "lastTargetSlot"):
        first[field] = max(s[field] for s in summaries)
    return first


def evaluate_period(dataset, train_part, score_part, design):
    raw_builder, _, _, lookback = feature_profile(design["featureProfile"])
    scoring, predictions, training_summaries, score_summaries = [], [], [], []
    fallback_count = 0
    for resource in sorted({s.identity.resource_type for s in dataset.series}):
        subset = replace(dataset, series=[s for s in dataset.series if s.identity.resource_type == resource])
        train, train_summary = build_examples(subset, train_part, feature_builder=cached_feature_builder(raw_builder),
            feature_lookback=lookback, eligibility_lookback=lookback)
        rows, score_summary = build_examples(subset, score_part, feature_builder=cached_feature_builder(raw_builder),
            feature_lookback=lookback, eligibility_lookback=lookback)
        if train_summary["lastTargetSlot"] >= score_summary["firstOriginSlot"]:
            raise ValueError("Training labels overlap scoring origins")
        training_summaries.append(train_summary)
        score_summaries.append(score_summary)
        model = ComplexPriceModel("lightgbm-reference", design["parameters"], seed=design["seed"]).fit(train)
        deltas = model.predict_deltas(rows)
        fallback_count += sum(e.identity not in model.supported for e in rows)
        predictions.extend(max(0, e.current_price + design["correctionWeight"] * delta) for e, delta in zip(rows, deltas))
        # Scoring/accounting need identities and labels, not large feature dicts.
        # Release them before retaining earlier windows for aggregate metrics.
        for e in rows:
            e.features = {}
        scoring.extend(rows)
        del train, model, rows, deltas
        print(f"{score_part.start}:{score_part.end} {resource} fit/scoring complete", flush=True)
    return dict(training=merge_summaries(training_summaries), scoring=merge_summaries(score_summaries), fallbackSampleCount=fallback_count,
                metrics=grouped_report(scoring, predictions)), scoring, predictions


def run_evaluation(dataset_directory, report_directory, *, design_path=DEFAULT_DESIGN):
    if report_directory.exists():
        raise ValueError("Use a fresh report directory")
    design_bytes = design_path.read_bytes()
    design = json.loads(design_bytes)
    if (design["schemaVersion"] != "expanded-price-evaluation-design-v1" or
            design["modelGrouping"] != "resourceType" or design["featureProfile"] != "extended168" or
            design["correctionWeight"] != .5):
        raise ValueError("Unsupported fixed incumbent evaluation design")
    if utc(design["laterEndUtcExclusive"]) > ORIGINAL_PROTECTED_START:
        raise ValueError("Cannot consume the original protected periods")
    dataset = load_prepared_dataset(dataset_directory)
    boundaries = [slot_for_timestamp(dataset.origin, t) for t in design["earlierBoundariesUtc"]]
    cutoff = slot_for_timestamp(dataset.origin, design["laterEndUtcExclusive"])
    if len(boundaries) != 4 or boundaries != sorted(set(boundaries)) or not 168 < boundaries[0] < boundaries[-1] < cutoff <= dataset.end_slot:
        raise ValueError("Invalid fixed chronological windows")
    development = replace(dataset, end_slot=cutoff, series=[PriceSeries(s.identity,
        {slot: price for slot, price in s.prices.items() if slot < cutoff}) for s in dataset.series])
    periods = [(f"earlier-{i}", Partition("train", 0, a), Partition("score", a, b))
               for i, (a, b) in enumerate(zip(boundaries, boundaries[1:]), 1)]
    periods.append(("later-development", Partition("train", 0, boundaries[-1]), Partition("score", boundaries[-1], cutoff)))
    reports, earlier_rows, earlier_predictions = {}, [], []
    report_directory.mkdir(parents=True, exist_ok=False)
    for name, train_part, score_part in periods:
        metrics, rows, predictions = evaluate_period(development, train_part, score_part, design)
        reports[name] = metrics
        if name.startswith("earlier"):
            earlier_rows.extend(rows)
            earlier_predictions.extend(predictions)
        with (report_directory / f"{name}-predictions.jsonl").open("x") as stream:
            for e, prediction in zip(rows, predictions):
                stream.write(json.dumps(dict(identity=e.identity.to_dict(), originSlot=e.origin_slot,
                    targetSlot=e.target_slot, horizon=e.horizon, actual=e.target_price,
                    persistence=e.current_price, prediction=prediction), sort_keys=True, allow_nan=False)+"\n")
        print(name, {r: m["overall"]["maeImprovementPct"] for r, m in metrics["metrics"].items()}, flush=True)
    _, schema, feature_hash, _ = feature_profile(design["featureProfile"])
    report = dict(schemaVersion="expanded-price-evaluation-results-v1", design=design,
        designSha256=hashlib.sha256(design_bytes).hexdigest(), datasetSha256=dataset.sha256,
        originUtc=dataset.origin.isoformat(), dataKind=dataset.data_kind,
        featureSchema=schema, featureCodeSha256=feature_hash,
        implementationSha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("evaluate_expanded.py", "complex_models.py", "alternative_models.py", "training_data.py")},
        poolCount=len(dataset.series), periods=reports,
        earlierAggregate=grouped_report(earlier_rows, earlier_predictions),
        protectedFromSlot=cutoff, protectedFromUtc=design["laterEndUtcExclusive"],
        calibration={"status": "RESERVED_NOT_USED"}, test={"status": "RESERVED_NOT_EVALUATED"},
        packageVersions={name: version(name) for name in ("lightgbm", "scikit-learn", "numpy", "scipy")},
        pythonVersion=platform.python_version(),
        limitations=["Hardware expansion is one region only; actual collection exclusions are recorded in the import receipt.",
            "This is a fixed-recipe development comparison, with no hyperparameter or correction-weight search.",
            "CPU and GPU are fitted separately to preserve resource-unit semantics; expensive GPU pools can still dominate GPU dollar MAE.",
            "Earlier dataset has a shifted start, warmup and hardware mix: differences from previous scores are not isolated effects of more data.",
            "Overlapping horizons and related zones are correlated; no statistical significance or scheduling savings claim.",
            "No deployment change, serialized model weights, calibrated uncertainty or interruption estimates are produced."])
    (report_directory / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    (report_directory / "design.json").write_bytes(design_bytes)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    args = parser.parse_args()
    try:
        run_evaluation(args.dataset, args.report_output, design_path=args.design)
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1, f"Expanded evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
