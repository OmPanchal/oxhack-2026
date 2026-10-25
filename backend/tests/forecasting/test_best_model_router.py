"""Exercise the frozen router, source identities and anti-leakage cutoffs."""
import json

import pytest

pytest.importorskip('lightgbm')
from app.api.schemas import ForecastRequest, MarketSnapshot
from app.forecasting.error_service import DEFAULT_CONFIG, ErrorForecastService, PROJECT_ROOT


@pytest.fixture(scope='module')
def service():
    return ErrorForecastService.from_config()


def sample(identity, current=2200):
    return ForecastRequest(currentSlot=current, history=[MarketSnapshot(
        slot=t, region=identity.region, resourceType=identity.resource_type,
        gpuType=identity.gpu_type or None, priceUsdPerUnitHour=.1 + (t % 19) * .001,
        source='SIMULATED router parity', dataKind='SIMULATED')
        for t in range(current - 168, current + 1)])


def test_every_selected_source_matches_exact_winning_native_bundle(service):
    assert len(service.selections) == 42
    for identity in service.selections.values():
        model = service.model_for(identity.region, identity.resource_type)
        expected_bundle = 'stockholm' if identity.region == 'eu-north-1' and identity.resource_type == 'GPU' else 'multi-region'
        assert model is service.bundles[expected_bundle][identity.resource_type]
        request = sample(identity)
        rows = service.predict(request)
        if identity.region == 'eu-north-1' and identity.gpu_type == 'NVIDIA B200':
            assert all(r.model_version.endswith('fallback-unsupported-pool') for r in rows)
            continue
        native = model.predict_horizons({r.slot: r.price_usd_per_unit_hour for r in request.history}, identity, 2200, 6)
        assert [r.predicted_price_usd_per_unit_hour for r in rows] == pytest.approx(native, abs=1e-13)
        assert all(model.metadata['modelSha256'][:12] in r.model_version for r in rows)


def test_routing_cannot_be_used_before_selection_results_were_available(service):
    for identity in service.selections.values():
        if identity.gpu_type == 'NVIDIA B200' and identity.region == 'eu-north-1':
            continue
        rows = service.predict(sample(identity, current=2135))
        assert all(r.model_version.endswith('fallback-model-not-available') for r in rows)
        assert all(r.model_version.startswith('lightgbm-') for r in service.predict(sample(identity, current=2136)))


def test_global_zone_ids_are_not_guessed_from_account_zone_names(service):
    from datetime import datetime
    from app.engine.ml_integration import SelectedModelProvider, fixed_pool_source

    identity = next(s for s in service.selections.values() if s.region == 'us-east-1' and s.gpu_type == 'NVIDIA T4')
    assert '-az' in identity.availability_zone
    request = sample(identity)
    for row in request.history:
        row.data_kind = 'OBSERVED'
        row.source = fixed_pool_source(identity).replace(identity.availability_zone, 'us-east-1a')
    provider = SelectedModelProvider(service)
    rows = provider.predict_at(request, datetime.fromisoformat(service.origin_utc))
    assert all(r.model_version.endswith('fallback-source-identity-mismatch') for r in rows)
    for row in request.history:
        row.source = fixed_pool_source(identity)
    assert all(r.model_version.startswith('lightgbm-') for r in provider.predict_at(request, datetime.fromisoformat(service.origin_utc)))


@pytest.mark.parametrize('failure', ['duplicate-route', 'wrong-bundle', 'bad-evidence', 'late-selection', 'corrupt-bundle'])
def test_invalid_router_configuration_is_rejected(tmp_path, failure):
    config = json.loads(DEFAULT_CONFIG.read_text())
    if failure == 'duplicate-route':
        config['routes'].append(config['routes'][0])
    elif failure == 'wrong-bundle':
        next(r for r in config['routes'] if r['region'] == 'us-east-1')['bundle'] = 'stockholm'
    elif failure == 'bad-evidence':
        config['selectionEvidence'][0]['sha256'] = '0' * 64
    elif failure == 'late-selection':
        config['selectedUsingValidationThroughSlot'] = config['availableFromSlot']
    else:
        spec = config['modelBundles']['multi-region']
        for item in json.loads((PROJECT_ROOT / spec['artifactReceipt']).read_text())['files']:
            (tmp_path / item['path'].split('/')[-1]).write_bytes((PROJECT_ROOT / item['path']).read_bytes())
        spec['modelsDirectory'] = str(tmp_path)
        (tmp_path / 'GPU-scaled-l1-31.txt').write_text('corrupt')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        ErrorForecastService.from_config(path)


def test_legacy_configuration_remains_reproducible():
    old = ErrorForecastService.from_config(PROJECT_ROOT / 'data/forecast-serving-stockholm-v1.json')
    assert old.available_from_slot == 1578
    assert old.status()['evaluation']['resources']['CPU']['designatedTest']['maeImprovementPct'] > 10
    assert old.models['CPU'].metadata['datasetSha256'] != ErrorForecastService.from_config().models['CPU'].metadata['datasetSha256']
