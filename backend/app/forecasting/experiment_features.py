"""Optional longer causal history for controlled forecasting experiments."""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from statistics import fmean, pstdev
import math
from typing import Mapping

from app.market import features as base_module
from app.market.features import InsufficientHistoryError, SeriesIdentity, build_features

EXTENDED_LOOKBACK = 168
EXTENDED_SCHEMA = "causal-price-extended-v1"


def extended_features(prices: Mapping[int, float | None], identity: SeriesIdentity,
                      origin: str | datetime, current_slot: int, horizon: int) -> dict:
    features = build_features(prices, identity, origin, current_slot, horizon)
    history = []
    for slot in range(current_slot - EXTENDED_LOOKBACK, current_slot + 1):
        value = prices.get(slot)
        if value is None:
            raise InsufficientHistoryError("Extended inputs need 169 consecutive known hourly observations")
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Historical prices must be finite and nonnegative")
        history.append(value)
    latest = history[-1]
    for window in (48, 72, 168):
        values = history[-window:]
        mean = fmean(values)
        features[f"lagPrice{window}h"] = history[-1-window]
        features[f"rollingMean{window}h"] = mean
        features[f"rollingStd{window}h"] = pstdev(values)
        features[f"deviationFromMean{window}h"] = latest - mean
    for window in (3, 6, 12, 24, 48, 168):
        changes = [b-a for a, b in zip(history[-window-1:-1], history[-window:])]
        features[f"changeFrequency{window}h"] = sum(change != 0 for change in changes) / window
        features[f"meanAbsoluteChange{window}h"] = fmean(abs(change) for change in changes)
    age = next((offset for offset in range(EXTENDED_LOOKBACK)
                if history[-1-offset] != history[-2-offset]), EXTENDED_LOOKBACK)
    features["extendedHoursSinceLastChange"] = float(age)
    features["extendedPriceAgeCapped"] = float(age == EXTENDED_LOOKBACK)
    return features


def feature_profile(name: str) -> tuple:
    base_bytes = Path(base_module.__file__).read_bytes()
    if name == "base24":
        return build_features, base_module.FEATURE_SCHEMA_VERSION, hashlib.sha256(base_bytes).hexdigest(), 24
    if name == "extended168":
        digest = hashlib.sha256(base_bytes + Path(__file__).read_bytes()).hexdigest()
        return extended_features, EXTENDED_SCHEMA, digest, EXTENDED_LOOKBACK
    raise ValueError("Unknown feature profile")
