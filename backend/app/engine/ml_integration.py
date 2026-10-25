"""Adapt selected fixed-pool ML models to the engine's clock and resource keys."""
from datetime import datetime
from pathlib import Path
from threading import RLock

from app.api.schemas import Forecast, ForecastRequest
from app.engine.forecast_bridge import EngineUnavailable, PersistenceForecastProvider


def gpu_name(value):
    return (value or '').removeprefix('NVIDIA ').strip()


class SelectedModelProvider:
    def __init__(self, service, lock=None):
        self.service = service
        self.lock = lock or RLock()

    def __deepcopy__(self, memo):
        # Frozen inference artifacts have no per-policy training/adaptive state.
        # Serialize access to shared native predictors; replay history stays isolated.
        return SelectedModelProvider(self.service, self.lock)

    def predict(self, request):
        with self.lock:
            return self.service.predict(request)

    def predict_at(self, request, origin_utc):
        model_origin = datetime.fromisoformat(self.service.origin_utc)
        delta = (origin_utc - model_origin).total_seconds() / 3600
        if delta != int(delta):
            raise ValueError('Engine/model origins must align to whole hours')
        offset = int(delta)
        results = []
        pools = {(r.region, r.resource_type, r.gpu_type) for r in request.history}
        for region, resource, gpu in sorted(pools, key=repr):
            rows = [r for r in request.history if (r.region, r.resource_type, r.gpu_type) == (region, resource, gpu)]
            current = max(rows, key=lambda r: r.slot)
            selection = next((s for s in self.service.selections.values()
                              if s.region == region and s.resource_type == resource
                              and gpu_name(s.gpu_type) == gpu_name(gpu)), None)
            reason = None
            if current.slot != request.current_slot:
                reason = 'stale-pool'
            elif request.current_slot + offset < self.service.available_from_slot:
                reason = 'model-not-available'
            elif selection is None:
                reason = 'unmapped-pool'
            else:
                prefix = fixed_pool_source(selection)
                window = [r for r in rows if r.slot >= request.current_slot - 168]
                if any(r.data_kind == 'OBSERVED' and not r.source.startswith(prefix) for r in window):
                    reason = 'source-identity-mismatch'
            if reason:
                fallback = PersistenceForecastProvider().predict(ForecastRequest(
                    current_slot=request.current_slot, horizon_slots=request.horizon_slots, history=[current]))
                results.extend(r.model_copy(update={'model_version': f'persistence-v1:fallback-{reason}'}) for r in fallback)
                continue
            shifted = [r.model_copy(update={'slot': r.slot + offset,
                       'gpu_type': selection.gpu_type or None}) for r in rows
                       if request.current_slot - 168 <= r.slot <= request.current_slot and r.slot + offset >= 0]
            with self.lock:
                predictions = self.service.predict(ForecastRequest(current_slot=request.current_slot + offset,
                    horizon_slots=request.horizon_slots, history=shifted))
            results.extend(Forecast(**{**r.model_dump(), 'generated_at_slot': request.current_slot,
                'target_slot': r.target_slot - offset, 'gpu_type': gpu}) for r in predictions)
        return results


def fixed_pool_source(selection):
    return (f'AWS EC2 OBSERVED FIXED POOL; {selection.instance_type}; '
            f'{selection.availability_zone}; {selection.product_description}; ')


class ModelLoader:
    def __init__(self, config=None, directory=None):
        self.config, self.directory = config, directory
        self.service = None
        self.lock = RLock()

    def load(self):
        with self.lock:
            if self.service is None:
                try:
                    from app.forecasting.error_service import DEFAULT_CONFIG, ErrorForecastService
                    self.service = ErrorForecastService.from_config(
                        Path(self.config) if self.config else DEFAULT_CONFIG, models_directory=self.directory)
                except (OSError, ValueError, KeyError, ImportError) as exc:
                    raise EngineUnavailable('MODEL_UNAVAILABLE', f'Selected ML model cannot load: {exc}') from exc
            return self.service

    def status(self):
        try:
            return self.load().status()
        except EngineUnavailable as exc:
            return {'status': 'UNAVAILABLE', 'reason': str(exc)}
