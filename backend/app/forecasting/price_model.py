"""A pooled LightGBM price-change model and an adapter for the shared forecast API."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from app.api.schemas import Forecast, ForecastRequest
from app.forecasting.baselines import persistence_forecasts
from app.forecasting.contracts import current_observations, pool_key, validate_forecasts
from app.forecasting.training_data import Example
from app.market import features as feature_module
from app.market.features import FEATURE_SCHEMA_VERSION, InsufficientHistoryError, SeriesIdentity, build_features


def feature_code_hash() -> str:
    return hashlib.sha256(Path(feature_module.__file__).read_bytes()).hexdigest()


class LightGBMPriceModel:
    def __init__(self, booster, vectorizer, metadata: dict):
        self.booster = booster
        self.vectorizer = vectorizer
        self.metadata = metadata

    @classmethod
    def fit(cls, examples: list[Example], parameters: dict, *, seed: int = 42,
            feature_schema: str = FEATURE_SCHEMA_VERSION,
            feature_code_sha256: str | None = None) -> LightGBMPriceModel:
        import lightgbm as lgb
        import numpy as np
        from sklearn.feature_extraction import DictVectorizer

        if not examples:
            raise ValueError("No training examples")
        vectorizer = DictVectorizer(sparse=False, sort=True)
        matrix = vectorizer.fit_transform([example.features for example in examples])
        # Persistence is the reference level; learn the future change in USD/unit-hour.
        targets = np.array([e.target_price - e.current_price for e in examples], dtype=float)
        params = dict(parameters)
        rounds = params.pop("num_boost_round")
        params.update(seed=seed, data_random_seed=seed, feature_fraction_seed=seed,
                      bagging_seed=seed, deterministic=True, force_col_wise=True,
                      num_threads=1, verbosity=-1)
        training = lgb.Dataset(matrix, label=targets,
                               feature_name=[f"f{index}" for index in range(matrix.shape[1])])
        booster = lgb.train(params, training, num_boost_round=rounds)
        return cls(booster, vectorizer, {"schemaVersion": "price-model-artifact-v1",
                                        "seriesIdentities": [identity.to_dict() for identity in sorted({e.identity for e in examples})],
                                        "featureSchemaVersion": feature_schema,
                                        "featureCodeSha256": feature_code_sha256 or feature_code_hash(),
                                        "parameters": parameters, "seed": seed,
                                        "predictionTarget": "futurePrice minus currentPrice"})

    def predict_features(self, rows: list[dict]) -> list[float]:
        import numpy as np

        if not rows:
            return []
        matrix = self.vectorizer.transform(rows)
        delta = self.booster.predict(matrix, num_threads=1)
        prices = np.maximum(0, np.array([row["latestPrice"] for row in rows]) + delta)
        if not np.isfinite(prices).all():
            raise ValueError("Model returned a nonfinite price")
        return prices.tolist()

    def predict_examples(self, examples: list[Example]) -> list[float]:
        supported = {SeriesIdentity(**row) for row in self.metadata["seriesIdentities"]}
        indices = [index for index, example in enumerate(examples) if example.identity in supported]
        result = [example.current_price for example in examples]
        predictions = self.predict_features([examples[index].features for index in indices])
        for index, prediction in zip(indices, predictions):
            result[index] = prediction
        return result

    def make_features(self, prices: dict, identity: SeriesIdentity, current_slot: int, horizon: int) -> dict:
        if self.metadata["featureSchemaVersion"] != FEATURE_SCHEMA_VERSION:
            raise ValueError("Extended artifacts require their matching experiment feature builder")
        return build_features(prices, identity, self.metadata["originUtc"], current_slot, horizon)

    def save(self, directory: Path) -> dict:
        if directory.exists():
            raise ValueError("Model directory exists; choose a new version")
        model = self.booster.model_to_string().encode()
        encoding = (json.dumps({"featureNames": self.vectorizer.get_feature_names_out().tolist()},
                               indent=2, sort_keys=True) + "\n").encode()
        metadata = {key: value for key, value in self.metadata.items() if key not in ("modelVersion", "sha256")}
        signature = hashlib.sha256(model + encoding + json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        metadata["modelVersion"] = f"lightgbm-delta-v1-{signature[:12]}"
        metadata["sha256"] = {"model.txt": hashlib.sha256(model).hexdigest(),
                              "encoder.json": hashlib.sha256(encoding).hexdigest()}
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "model.txt").write_bytes(model)
        (directory / "encoder.json").write_bytes(encoding)
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        self.metadata = metadata
        return metadata

    @classmethod
    def load(cls, directory: Path, *, expected_feature_schema: str = FEATURE_SCHEMA_VERSION,
             expected_feature_code_sha256: str | None = None) -> LightGBMPriceModel:
        import lightgbm as lgb
        from sklearn.feature_extraction import DictVectorizer

        metadata = json.loads((directory / "metadata.json").read_text())
        if metadata.get("schemaVersion") != "price-model-artifact-v1":
            raise ValueError("Unsupported model artifact schema")
        if (metadata["featureSchemaVersion"] != expected_feature_schema or
                metadata["featureCodeSha256"] != (expected_feature_code_sha256 or feature_code_hash())):
            raise ValueError("Feature builder changed; use matching code or retrain the artifact")
        payloads = {}
        for name in ("model.txt", "encoder.json"):
            payloads[name] = (directory / name).read_bytes()
            if hashlib.sha256(payloads[name]).hexdigest() != metadata["sha256"][name]:
                raise ValueError(f"Model artifact checksum mismatch: {name}")
        names = json.loads(payloads["encoder.json"])["featureNames"]
        if not names or len(names) != len(set(names)):
            raise ValueError("Invalid encoder feature names")
        vectorizer = DictVectorizer(sparse=False, sort=True)
        vectorizer.feature_names_ = names
        vectorizer.vocabulary_ = {name: index for index, name in enumerate(names)}
        booster = lgb.Booster(model_str=payloads["model.txt"].decode())
        if booster.num_feature() != len(names):
            raise ValueError("Encoder and model feature counts differ")
        return cls(booster, vectorizer, metadata)


class PricePredictor(Protocol):
    metadata: dict

    def make_features(self, prices: dict, identity: SeriesIdentity, current_slot: int, horizon: int) -> dict: ...

    def predict_features(self, rows: list[dict]) -> list[float]: ...


class LightGBMForecastService:
    """Explicit source-pool selection avoids merging multiple AZs in the API.

    Unknown pools, missing feature history and pre-availability calls use
    persistence with an explicit fallback modelVersion. Invalid/stale requests
    still fail shared validation. No capacities are inferred from this model.
    """

    def __init__(self, model: PricePredictor, *, pool_selections: list[SeriesIdentity]):
        self.model = model
        self.selections = {}
        for selection in pool_selections:
            if selection.api_key in self.selections:
                raise ValueError("Select only one AZ/instance/product per API pool key")
            self.selections[selection.api_key] = selection
        self.supported = {SeriesIdentity(**row) for row in model.metadata["seriesIdentities"]}

    def predict(self, request: ForecastRequest) -> list[Forecast]:
        forecasts = []
        for row in current_observations(request):
            key = pool_key(row)
            selection = self.selections.get(key)
            reason = None
            if selection is None:
                reason = "unmapped-pool"
            elif selection not in self.supported:
                reason = "unsupported-pool"
            elif request.current_slot < self.model.metadata["availableFromSlot"]:
                # Model selection used validation outcomes; do not deploy it before then.
                reason = "model-not-available"
            if reason is not None:
                forecasts.extend(persistence_forecasts(row, request, reason))
                continue
            history = {observation.slot: observation.price_usd_per_unit_hour
                       for observation in request.history if pool_key(observation) == key}
            try:
                features = [self.model.make_features(history, selection, request.current_slot, horizon)
                            for horizon in range(1, request.horizon_slots + 1)]
            except InsufficientHistoryError:
                forecasts.extend(persistence_forecasts(row, request, "insufficient-history"))
                continue
            predictions = self.model.predict_features(features)
            forecasts.extend(Forecast(generated_at_slot=request.current_slot,
                                      target_slot=request.current_slot + horizon,
                                      region=row.region, resource_type=row.resource_type, gpu_type=row.gpu_type,
                                      predicted_price_usd_per_unit_hour=price,
                                      price_lower_bound=None, price_upper_bound=None,
                                      availability_probability=None, interruption_probability=None,
                                      model_version=self.model.metadata["modelVersion"])
                             for horizon, price in enumerate(predictions, 1))
        return validate_forecasts(request, forecasts)
