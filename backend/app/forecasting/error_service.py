"""Serve the selected CPU/GPU price models through the shared forecast contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pydantic.alias_generators import to_camel

from app.api.schemas import Forecast, ForecastRequest
from app.forecasting.baselines import persistence_forecasts
from app.forecasting.contracts import current_observations, pool_key, timestamp_for_slot, validate_forecasts
from app.market.features import SeriesIdentity

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / 'data/forecast-serving.json'


class ErrorForecastService:
    def __init__(self, models, selections, *, origin_utc, available_from_slot, evaluation=None,
                 routes=None, bundles=None, route_config=None, evidence=None):
        self.evaluation = evaluation
        self.models = models
        self.routes = routes
        self.bundles = bundles or {}
        self.route_config = route_config or []
        self.evidence = evidence or []
        self.selections = {}
        self.origin_utc = timestamp_for_slot(origin_utc, 0).isoformat()
        self.available_from_slot = available_from_slot
        for selection in selections:
            if selection.api_key in self.selections:
                raise ValueError('Select only one instance/AZ/product per API pool key')
            self.selections[selection.api_key] = selection
        checked_models = list(models.items()) if routes is None else [(key[1], model) for key, model in routes.items()]
        for resource, model in checked_models:
            if (model.metadata['originUtc'] != self.origin_utc or
                    model.metadata['trainingEndExclusive'] > available_from_slot):
                raise ValueError('Model origin or availability differs from serving configuration')
            if any(identity['resource_type'] != resource for identity in model.metadata['identities']):
                raise ValueError('Model resource identities do not match its resource group')

    @classmethod
    def from_config(cls, path=DEFAULT_CONFIG, *, models_directory=None):
        config = json.loads(Path(path).read_text())
        if config['schemaVersion'] not in ('error-price-serving-v1', 'error-price-serving-v2'):
            raise ValueError('Unsupported price serving configuration')
        if (type(config['availableFromSlot']) is not int or
                config['availableFromSlot'] <= config['selectedUsingValidationThroughSlot']):
            raise ValueError('Serving cannot precede the model selection labels')
        if config['schemaVersion'] == 'error-price-serving-v2':
            evidence = config['selectionEvidence']
            for item in evidence:
                if hashlib.sha256((PROJECT_ROOT / item['path']).read_bytes()).hexdigest() != item['sha256']:
                    raise ValueError('Model-selection evidence checksum differs from serving configuration')
            bundles = {}
            for name, spec in config['modelBundles'].items():
                directory = (PROJECT_ROOT / models_directory / Path(spec['modelsDirectory']).name
                             if models_directory is not None else PROJECT_ROOT / spec['modelsDirectory'])
                bundles[name] = cls._load_bundle(directory, spec)
            routes = {}
            for row in config['routes']:
                key = (row['region'], row['resourceType'])
                if key in routes:
                    raise ValueError('Duplicate model route')
                routes[key] = bundles[row['bundle']][row['resourceType']]
            selections = [SeriesIdentity(**row) for row in config['poolSelections']]
            if set(routes) != {(s.region, s.resource_type) for s in selections}:
                raise ValueError('Model routes and selected source regions differ')
            service = cls({resource: routes[('eu-north-1', resource)] for resource in ('CPU', 'GPU')},
                selections, origin_utc=config['originUtc'], available_from_slot=config['availableFromSlot'],
                routes=routes, bundles=bundles, route_config=config['routes'], evidence=evidence)
            for selection in selections:
                if selection.to_dict() not in service.model_for(selection.region, selection.resource_type).metadata['identities']:
                    raise ValueError('Configured source pool is not in the routed model metadata')
            return service
        directory = PROJECT_ROOT / (models_directory or config['modelsDirectory'])
        models = cls._load_bundle(directory, config)
        receipt = json.loads((PROJECT_ROOT / config['artifactReceipt']).read_text())
        selections = [SeriesIdentity(**row) for row in config['poolSelections']]
        evaluation = None
        if config.get('evaluationReport'):
            evaluation = json.loads((PROJECT_ROOT / config['evaluationReport']).read_text())
            if (evaluation['design']['artifactReceipt'] != receipt or
                    any(evaluation['design']['datasetSha256'] != model.metadata['datasetSha256']
                        for model in models.values())):
                raise ValueError('Evaluation report does not describe the serving artifacts')
        service = cls(models, selections, origin_utc=config['originUtc'],
                      available_from_slot=config['availableFromSlot'], evaluation=evaluation)
        for selection in selections:
            if selection.to_dict() not in models[selection.resource_type].metadata['identities']:
                raise ValueError('Configured source pool is not in the model metadata')
        return service

    @staticmethod
    def _load_bundle(directory, config):
        from app.forecasting.error_model import ErrorPriceModel

        receipt = json.loads((PROJECT_ROOT / config['artifactReceipt']).read_text())
        expected = {'CPU-model.json', 'GPU-model.json', 'CPU-scaled-l1-31.txt', 'GPU-scaled-l1-31.txt'}
        if {Path(item['path']).name for item in receipt['files']} != expected:
            raise ValueError('Incomplete selected-model artifact receipt')
        for item in receipt['files']:
            payload = (directory / Path(item['path']).name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('Serving artifact checksum differs from selected-model receipt')
        models = {resource: ErrorPriceModel(directory, resource) for resource in ('CPU', 'GPU')}
        return models

    def model_for(self, region, resource):
        return self.models.get(resource) if self.routes is None else self.routes.get((region, resource))

    def predict(self, request: ForecastRequest) -> list[Forecast]:
        forecasts = []
        observations = current_observations(request)
        histories = {}
        for row in request.history:
            histories.setdefault(pool_key(row), {})[row.slot] = row.price_usd_per_unit_hour
        for observation in observations:
            key = pool_key(observation)
            selection = self.selections.get(key)
            model = self.model_for(observation.region, observation.resource_type)
            reason = None
            if selection is None:
                reason = 'unmapped-pool'
            elif model is None or selection.to_dict() not in model.metadata['identities']:
                reason = 'unsupported-pool'
            elif model.metadata['identities'].index(selection.to_dict()) not in model.metadata['supportedPoolIndices']:
                reason = 'unsupported-pool'
            elif request.current_slot < self.available_from_slot:
                reason = 'model-not-available'
            history = histories[key]
            if reason is None and any(slot not in history for slot in range(request.current_slot-168, request.current_slot+1)):
                reason = 'insufficient-history'
            if reason is None and observation.price_usd_per_unit_hour == 0:
                reason = 'zero-current-price'
            if reason is not None:
                forecasts.extend(persistence_forecasts(observation, request, reason))
                continue
            prices = model.predict_horizons(history, selection, request.current_slot, request.horizon_slots)
            version = f"lightgbm-price-l1-v1-{observation.resource_type.lower()}-{model.metadata['modelSha256'][:12]}"
            forecasts.extend(Forecast(generated_at_slot=request.current_slot,
                target_slot=request.current_slot+horizon, region=observation.region,
                resource_type=observation.resource_type, gpu_type=observation.gpu_type,
                predicted_price_usd_per_unit_hour=price, model_version=version)
                for horizon, price in enumerate(prices, 1))
        return validate_forecasts(request, forecasts)

    def status(self):
        return dict(status='READY', modelFamily='LightGBM', objective='regression_l1',
            defaultForecastMode='ML', originUtc=self.origin_utc,
            availableFromSlot=self.available_from_slot, lookbackHours=168,
            horizonHours=[1, 2, 3, 4, 5, 6],
            validationStatus='EXPERIMENTAL_POST_HOLDOUT',
            selectionEvidence=self.evidence,
            modelsScope='eu-north-1' if self.routes is not None else 'all-configured-regions',
            routes=[dict(row, modelSha256=self.model_for(row['region'], row['resourceType']).metadata['modelSha256'],
                         datasetSha256=self.model_for(row['region'], row['resourceType']).metadata['datasetSha256'])
                    for row in self.route_config],
            poolSelections=[dict({to_camel(k): v for k, v in selection.to_dict().items()},
                                 availabilityZoneKind='GLOBAL_ID' if '-az' in selection.availability_zone else 'ACCOUNT_NAME')
                            for selection in self.selections.values()],
            evaluation=None if self.evaluation is None else dict(
                status="POST_HOLDOUT_REUSED_TEST_PLUS_ONE_FORWARD_DAY",
                periods=self.evaluation["design"]["periods"],
                resources=self.evaluation["resources"]),
            models={resource: dict(modelSha256=model.metadata['modelSha256'],
                trainingEndExclusive=model.metadata['trainingEndExclusive'],
                datasetSha256=model.metadata['datasetSha256'],
                supportedPoolCount=len(model.metadata['supportedPoolIndices']))
                for resource, model in self.models.items()})
