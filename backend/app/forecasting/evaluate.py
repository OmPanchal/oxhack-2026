"""Price accuracy on identical origins and targets; no scheduling savings inferred."""
from __future__ import annotations

from collections import defaultdict
import math
from statistics import fmean

from app.forecasting.training_data import Example


def regression_metrics(actual: list[float], predicted: list[float]) -> dict:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metrics need equal nonempty actual and prediction arrays")
    if not all(math.isfinite(value) for value in actual + predicted):
        raise ValueError("Metrics require finite prices")
    errors = [prediction - target for target, prediction in zip(actual, predicted)]
    return {"sampleCount": len(errors), "mae": fmean(abs(error) for error in errors),
            "rmse": math.sqrt(fmean(error * error for error in errors))}


def compare_predictions(examples: list[Example], predictions: list[float]) -> dict:
    actual = [example.target_price for example in examples]
    baseline = regression_metrics(actual, [example.current_price for example in examples])
    ml = regression_metrics(actual, predictions)
    improvement = 100 * (baseline["mae"] - ml["mae"]) / baseline["mae"] if baseline["mae"] else None
    return {"sampleCount": len(examples), "persistence": baseline, "ml": ml,
            "maeImprovementPct": improvement,
            "changedTargetCount": sum(e.target_price != e.current_price for e in examples),
            "note": "Improvement is undefined when persistence MAE is zero" if improvement is None else "Lower MAE is better"}


def evaluation_report(examples: list[Example], predictions: list[float]) -> dict:
    overall = compare_predictions(examples, predictions)
    dimensions = {
        "byHorizon": lambda e: str(e.horizon),
        "byRegion": lambda e: e.identity.region,
        "byResourceType": lambda e: e.identity.resource_type,
        "byPriceMovement": lambda e: "CHANGED" if e.target_price != e.current_price else "UNCHANGED",
    }
    result = {"overall": overall}
    for name, key in dimensions.items():
        groups = defaultdict(list)
        for index, example in enumerate(examples):
            groups[key(example)].append(index)
        result[name] = {group: compare_predictions([examples[i] for i in indices], [predictions[i] for i in indices])
                        for group, indices in sorted(groups.items())}
    pools = defaultdict(list)
    for index, example in enumerate(examples):
        pools[example.identity].append(index)
    result["byPool"] = [{"identity": identity.to_dict(),
                         "metrics": compare_predictions([examples[i] for i in indices], [predictions[i] for i in indices])}
                        for identity, indices in sorted(pools.items())]
    return result
