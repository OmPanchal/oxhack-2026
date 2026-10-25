"""Optional inference adapter for the post-holdout MAE experiment.

Native LightGBM text models only; no pickle loading or production default change.
"""
from pathlib import Path
import hashlib
import json
import math

import lightgbm as lgb
import numpy as np

from app.forecasting.error_search import causal_matrix
from app.forecasting.training_data import PriceSeries


class ErrorPriceModel:
    def __init__(self, directory: Path, resource: str):
        self.directory = Path(directory)
        self.metadata = json.loads((self.directory / f'{resource}-model.json').read_text())
        if self.metadata['schemaVersion'] != 'relative-price-error-model-v1':
            raise ValueError('Unsupported model schema')
        feature_path = Path(__file__).with_name('error_search.py')
        if hashlib.sha256(feature_path.read_bytes()).hexdigest() != self.metadata['featureImplementationSha256']:
            raise ValueError('Model and feature implementation do not match')
        model_path = self.directory / self.metadata['modelFile']
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != self.metadata['modelSha256']:
            raise ValueError('Model checksum mismatch')
        self.model = lgb.Booster(model_file=str(model_path))

    def predict(self, prices, identity, current_slot: int, horizon: int) -> float:
        return self.predict_horizons(prices, identity, current_slot, horizon)[-1]

    def predict_horizons(self, prices, identity, current_slot: int, horizon: int) -> list[float]:
        """Batch all requested horizons using the same causal training features."""
        if type(horizon) is not int or not 1 <= horizon <= 6:
            raise ValueError('Horizon must be an integer from 1 through 6')
        if type(current_slot) is not int or current_slot < 0:
            raise ValueError('Current slot must be a nonnegative integer')
        current = prices.get(current_slot)
        if current is None or not math.isfinite(current) or current < 0:
            raise ValueError('A finite nonnegative current observation is required')
        fallback = [float(current)] * horizon
        identities = self.metadata['identities']
        if identity.to_dict() not in identities or current == 0:
            return fallback
        pool = identities.index(identity.to_dict())
        if pool not in self.metadata['supportedPoolIndices']:
            return fallback
        # No future observations enter even when callers supply a larger series.
        series = PriceSeries(identity, {t: p for t, p in prices.items() if t <= current_slot})
        x, origins, horizons, _, _ = causal_matrix(series, current_slot+7)
        mask = (origins == current_slot) & (horizons <= horizon)
        if not mask.any():
            return fallback
        hardware = identity.gpu_type or identity.instance_type.split('.')[0]
        matrix = np.column_stack([x[mask], np.full(horizon, pool),
            np.full(horizon, self.metadata['hardware'].index(hardware))]).astype(np.float32)
        delta = self.model.predict(matrix, num_threads=1)
        divisor = current if self.metadata['target'] == 'relative' else self.metadata['scale']
        predictions = current + self.metadata['weight'] * delta * divisor
        if not np.isfinite(predictions).all():
            raise ValueError('Nonfinite model output')
        return np.maximum(0., predictions).tolist()


def export_selected_model(directory: Path, dataset, resource: str):
    """Attach the frozen training categories and units to a selected text model."""
    directory = Path(directory)
    report = json.loads((directory/'report.json').read_text())
    design = report['design']
    if dataset.sha256 != design['datasetSha256']:
        raise ValueError('Dataset does not match the training run')
    winner = report['resources'][resource]['winner']
    name, weight = winner.rsplit('-w', 1)
    spec = next(s for s in design['candidates'] if s['name'] == name)
    pools = [s for s in dataset.series if s.identity.resource_type == resource]
    current_values, supported = [], []
    for idx, series in enumerate(pools):
        _, _, _, current, _ = causal_matrix(series, design['trainEnd'])
        if len(current):
            supported.append(idx)
            current_values.append(current)
    model_path = directory/f'{resource}-{name}.txt'
    metadata = dict(schemaVersion='relative-price-error-model-v1',
        status='EXPERIMENTAL_POST_HOLDOUT', originUtc=dataset.origin.isoformat(),
        datasetSha256=dataset.sha256, trainingEndExclusive=design['trainEnd'],
        modelFile=model_path.name, modelSha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        identities=[s.identity.to_dict() for s in pools], supportedPoolIndices=supported,
        hardware=sorted({s.identity.gpu_type or s.identity.instance_type.split('.')[0] for s in pools}),
        target=spec['target'],weight=float(weight),scale=float(np.median(np.concatenate(current_values))),
        featureSchema='relative-price-error-features-v1', featureImplementationSha256=design['implementationSha256'])
    (directory/f'{resource}-model.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata
