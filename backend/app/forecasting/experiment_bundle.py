"""A pooled or per-horizon model with frozen persistence-correction weights."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from app.forecasting.experiment_features import feature_profile
from app.forecasting.price_model import LightGBMPriceModel
from app.forecasting.training_data import Example
from app.market.features import SeriesIdentity


class ExperimentBundle:
    def __init__(self, models: dict[str, LightGBMPriceModel], config: dict,
                 weights: dict[str, float], metadata: dict):
        if config["architecture"] not in ("pooled", "per-horizon"):
            raise ValueError("Unsupported model architecture")
        expected = {"pooled"} if config["architecture"] == "pooled" else {str(h) for h in range(1, 7)}
        if set(models) != expected or set(weights) != {str(h) for h in range(1, 7)}:
            raise ValueError("Incomplete model or correction-weight bundle")
        if any(type(w) not in (int, float) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights.values()):
            raise ValueError("Correction weights must be finite and between zero and one")
        self.models, self.config, self.weights, self.metadata = models, config, weights, metadata

    def make_features(self, prices: dict, identity: SeriesIdentity, current_slot: int, horizon: int) -> dict:
        builder, _, _, _ = feature_profile(self.config["featureProfile"])
        return builder(prices, identity, self.metadata["originUtc"], current_slot, horizon)

    def predict_features(self, rows: list[dict]) -> list[float]:
        groups = defaultdict(list)
        for index, row in enumerate(rows):
            horizon = int(row["horizonHours"])
            if horizon != row["horizonHours"] or not 1 <= horizon <= 6:
                raise ValueError("Invalid prediction horizon")
            key = "pooled" if self.config["architecture"] == "pooled" else str(horizon)
            groups[key].append(index)
        result = [float(row["latestPrice"]) for row in rows]
        for key, indices in groups.items():
            raw = self.models[key].predict_features([rows[i] for i in indices])
            for index, prediction in zip(indices, raw):
                weight = self.weights[str(int(rows[index]["horizonHours"]))]
                latest = rows[index]["latestPrice"]
                result[index] = max(0.0, latest + weight * (prediction - latest))
        return result

    def predict_examples(self, examples: list[Example]) -> list[float]:
        supported = {SeriesIdentity(**row) for row in self.metadata["seriesIdentities"]}
        indices = [i for i, example in enumerate(examples) if example.identity in supported]
        result = [example.current_price for example in examples]
        predictions = self.predict_features([examples[i].features for i in indices])
        for index, prediction in zip(indices, predictions):
            result[index] = prediction
        return result

    def save(self, directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=False)
        children = {}
        for key, model in sorted(self.models.items()):
            model.save(directory/key)
            children[key] = hashlib.sha256((directory/key/"metadata.json").read_bytes()).hexdigest()
        metadata = {k: v for k, v in self.metadata.items() if k != "modelVersion"}
        metadata.update(schemaVersion="forecast-experiment-bundle-v1", config=self.config,
                        correctionWeights=self.weights, childMetadataSha256=children)
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        metadata["modelVersion"] = f"lightgbm-experiment-v1-{digest[:12]}"
        (directory/"metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        self.metadata = metadata
        return metadata

    @classmethod
    def load(cls, directory: Path) -> ExperimentBundle:
        metadata = json.loads((directory/"metadata.json").read_text())
        if metadata["schemaVersion"] != "forecast-experiment-bundle-v1":
            raise ValueError("Unsupported experimental artifact")
        _, schema, digest, _ = feature_profile(metadata["config"]["featureProfile"])
        models = {}
        for key, expected in metadata["childMetadataSha256"].items():
            if key not in {"pooled", "1", "2", "3", "4", "5", "6"}:
                raise ValueError("Invalid child artifact name")
            if hashlib.sha256((directory/key/"metadata.json").read_bytes()).hexdigest() != expected:
                raise ValueError("Child metadata checksum mismatch")
            models[key] = LightGBMPriceModel.load(directory/key, expected_feature_schema=schema,
                                                  expected_feature_code_sha256=digest)
        return cls(models, metadata["config"], metadata["correctionWeights"], metadata)
