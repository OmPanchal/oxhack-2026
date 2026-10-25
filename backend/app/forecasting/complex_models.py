"""More expressive residual models for offline development experiments only."""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction import DictVectorizer
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from threadpoolctl import threadpool_limits

from app.forecasting.alternative_models import AlternativePriceModel


class ComplexPriceModel:
    """Fit one delta regressor per horizon; all learned transforms use train only.

    Neural training has no random validation split or early stopping. Its stopping
    rule uses training loss only. Convergence warnings are retained in the report.
    This experiment class is deliberately not installed into the forecast API.
    """

    def __init__(self, family: str, parameters: dict, *, seed: int = 42):
        if family not in {"lightgbm-reference", "deep-lightgbm", "random-forest", "rbf-svr", "mlp"}:
            raise ValueError("Unknown complex model family")
        self.family, self.parameters, self.seed = family, dict(parameters), seed
        self.models, self.target_scalers, self.fit_warnings = {}, {}, []

    @threadpool_limits.wrap(limits=1)
    def fit(self, examples):
        if not examples or {e.horizon for e in examples} != set(range(1, 7)):
            raise ValueError("Training requires all six horizons")
        self.fit_warnings = []
        self.supported = {e.identity for e in examples}
        self.training_max_target_slot = max(e.target_slot for e in examples)
        if self.family in {"lightgbm-reference", "deep-lightgbm"}:
            self.delegate = AlternativePriceModel("lightgbm-reference", self.parameters, seed=self.seed).fit(examples)
            return self
        self.encoder = DictVectorizer(sparse=False, sort=True)
        matrix = self.encoder.fit_transform([e.features for e in examples])
        self.scaler = StandardScaler().fit(matrix) if self.family in {"mlp", "rbf-svr"} else None
        if self.scaler is not None:
            matrix = self.scaler.transform(matrix)
        horizons = np.array([e.horizon for e in examples])
        labels = np.array([e.target_price - e.current_price for e in examples])
        constructors = {"random-forest": RandomForestRegressor, "rbf-svr": SVR, "mlp": MLPRegressor}
        self.models, self.target_scalers = {}, {}
        for horizon in range(1, 7):
            mask = horizons == horizon
            target = labels[mask]
            if self.scaler is not None:
                target_scaler = StandardScaler().fit(target.reshape(-1, 1))
                self.target_scalers[horizon] = target_scaler
                target = target_scaler.transform(target.reshape(-1, 1)).ravel()
            params = dict(self.parameters)
            if self.family != "rbf-svr":
                params["random_state"] = self.seed
            if self.family == "random-forest":
                params["n_jobs"] = 1
            if self.family == "mlp":
                if params.get("early_stopping", False):
                    raise ValueError("Random internal validation is prohibited")
                params.update(early_stopping=False, shuffle=False)
                params["hidden_layer_sizes"] = tuple(params["hidden_layer_sizes"])
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                self.models[horizon] = constructors[self.family](**params).fit(matrix[mask], target)
            self.fit_warnings.extend(dict(horizon=horizon, category=w.category.__name__, message=str(w.message))
                                     for w in caught)
        return self

    @threadpool_limits.wrap(limits=1)
    def predict_deltas(self, examples):
        if not hasattr(self, "supported"):
            raise ValueError("Model must be fitted")
        if not examples:
            return []
        result = np.zeros(len(examples))
        supported_indices = [i for i, e in enumerate(examples) if e.identity in self.supported]
        if not supported_indices:
            return result.tolist()
        rows = [examples[i].features for i in supported_indices]
        if self.family in {"lightgbm-reference", "deep-lightgbm"}:
            deltas, _ = self.delegate.components(rows)
            result[supported_indices] = deltas
        else:
            matrix = self.encoder.transform(rows)
            if self.scaler is not None:
                matrix = self.scaler.transform(matrix)
            horizons = np.array([examples[i].horizon for i in supported_indices])
            if not np.isin(horizons, np.arange(1, 7)).all():
                raise ValueError("Invalid forecast horizon")
            for horizon, model in self.models.items():
                mask = horizons == horizon
                if not mask.any():
                    continue
                prediction = model.predict(matrix[mask])
                if horizon in self.target_scalers:
                    prediction = self.target_scalers[horizon].inverse_transform(prediction.reshape(-1, 1)).ravel()
                result[np.array(supported_indices)[mask]] = prediction
        if not np.isfinite(result).all():
            raise ValueError("Nonfinite predicted delta")
        return result.tolist()
