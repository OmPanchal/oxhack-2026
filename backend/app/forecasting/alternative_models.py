"""Alternative residual price models; inputs are causal and encoders fit training only.

The two-stage model classifies PRICE changes, not capacity or interruptions.
These classes intentionally keep fitted sklearn objects in memory (no pickle).
"""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from app.forecasting.experiment_features import extended_features
from app.market.features import SeriesIdentity


class AlternativePriceModel:
    def __init__(self, family: str, parameters: dict, *, seed: int = 42):
        if family not in {"ridge", "extra-trees", "hist-gradient", "two-stage", "lightgbm-reference"}:
            raise ValueError("Unsupported alternative model family")
        self.family, self.parameters, self.seed = family, dict(parameters), seed
        self.models, self.classifiers, self.metadata = {}, {}, {}

    def _lightgbm(self, matrix, labels, objective):
        import lightgbm as lgb
        parameters = dict(self.parameters)
        rounds = parameters.pop("num_boost_round")
        parameters.update(objective=objective, seed=self.seed, data_random_seed=self.seed,
                          feature_fraction_seed=self.seed, bagging_seed=self.seed,
                          deterministic=True, force_col_wise=True, num_threads=1, verbosity=-1)
        return lgb.train(parameters, lgb.Dataset(matrix, label=labels), num_boost_round=rounds)

    @threadpool_limits.wrap(limits=1)
    def fit(self, examples):
        if not examples or {e.horizon for e in examples} != set(range(1, 7)):
            raise ValueError("Training requires nonempty examples for all six horizons")
        self.encoder = DictVectorizer(sparse=False, sort=True)
        matrix = self.encoder.fit_transform([e.features for e in examples])
        self.scaler = StandardScaler().fit(matrix) if self.family == "ridge" else None
        if self.scaler is not None:
            matrix = self.scaler.transform(matrix)
        deltas = np.array([e.target_price-e.current_price for e in examples])
        horizons = np.array([e.horizon for e in examples])
        self.models, self.classifiers = {}, {}
        for horizon in range(1, 7):
            mask = horizons == horizon
            x, y = matrix[mask], deltas[mask]
            if self.family == "two-stage":
                changed = y != 0
                # Single-class training is valid: preserve an explicit constant gate.
                self.classifiers[horizon] = (float(changed[0]) if np.all(changed == changed[0]) else
                    self._lightgbm(x, changed.astype(int), "binary"))
                self.models[horizon] = (0.0 if not changed.any() else
                    self._lightgbm(x[changed], y[changed], "regression_l1"))
            elif self.family == "lightgbm-reference":
                self.models[horizon] = self._lightgbm(x, y, "regression_l1")
            else:
                constructors = {"ridge": Ridge, "extra-trees": ExtraTreesRegressor,
                                "hist-gradient": HistGradientBoostingRegressor}
                parameters = dict(self.parameters)
                if self.family != "ridge":
                    parameters["random_state"] = self.seed
                if self.family == "extra-trees":
                    parameters["n_jobs"] = 1
                self.models[horizon] = constructors[self.family](**parameters).fit(x, y)
        identities = sorted({e.identity for e in examples})
        self.metadata = dict(seriesIdentities=[s.to_dict() for s in identities],
                             trainingMaxTargetSlot=max(e.target_slot for e in examples))
        return self

    @staticmethod
    def _predict(model, matrix):
        if isinstance(model, float):
            return np.full(matrix.shape[0], model)
        # Native LightGBM predict explicitly avoids the host's default thread count.
        if model.__class__.__module__.startswith("lightgbm"):
            return model.predict(matrix, num_threads=1)
        return model.predict(matrix)

    @threadpool_limits.wrap(limits=1)
    def components(self, rows):
        """Return conditional deltas and price-change probabilities without labels."""
        if not self.models:
            raise ValueError("Model must be fitted")
        if not rows:
            return np.array([]), np.array([])
        horizons = np.array([row["horizonHours"] for row in rows])
        if not np.isin(horizons, np.arange(1, 7)).all():
            raise ValueError("Forecast horizon must be an integer from one through six")
        matrix = self.encoder.transform(rows)
        if self.scaler is not None:
            matrix = self.scaler.transform(matrix)
        deltas, probabilities = np.zeros(len(rows)), np.ones(len(rows))
        for horizon, model in self.models.items():
            mask = horizons == horizon
            if not mask.any():
                continue
            deltas[mask] = self._predict(model, matrix[mask])
            if self.family == "two-stage":
                probabilities[mask] = self._predict(self.classifiers[horizon], matrix[mask])
        if not np.isfinite(deltas).all() or not np.isfinite(probabilities).all():
            raise ValueError("Nonfinite model output")
        return deltas, probabilities

    def predict_features(self, rows):
        deltas, probabilities = self.components(rows)
        weight = self.metadata.get("correctionWeight", 1.0)
        threshold = self.metadata.get("changeThreshold", .5)
        current = np.array([row["latestPrice"] for row in rows])
        return np.maximum(0, current + weight*deltas*(probabilities >= threshold)).tolist()

    def predict_examples(self, examples):
        supported = {SeriesIdentity(**row) for row in self.metadata["seriesIdentities"]}
        indices = [i for i, e in enumerate(examples) if e.identity in supported]
        result = [e.current_price for e in examples]
        for index, value in zip(indices, self.predict_features([examples[i].features for i in indices])):
            result[index] = value
        return result

    def make_features(self, prices, identity, current_slot, horizon):
        return extended_features(prices, identity, self.metadata["originUtc"], current_slot, horizon)


def gated_predictions(examples, deltas, probabilities, *, weight, threshold):
    if len(examples) != len(deltas) or len(examples) != len(probabilities):
        raise ValueError("Unequal prediction/sample counts")
    if not 0 <= weight <= 1 or not 0 <= threshold <= 1:
        raise ValueError("Weight and threshold must be within [0,1]")
    if not np.isfinite(deltas).all() or not np.isfinite(probabilities).all():
        raise ValueError("Nonfinite model output")
    if np.any(np.array(probabilities) < 0) or np.any(np.array(probabilities) > 1):
        raise ValueError("Invalid price-change probability")
    current = np.array([e.current_price for e in examples])
    return np.maximum(0, current+weight*np.array(deltas)*(np.array(probabilities) >= threshold)).tolist()
