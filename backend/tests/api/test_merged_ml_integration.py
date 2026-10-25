from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

pytest.importorskip('lightgbm')

from app.api.replay_schemas import ReplayScenario
from app.api.schemas import ForecastRequest, JobCreate, MarketSnapshot
from app.engine.ml_integration import SelectedModelProvider
from app.forecasting.error_service import ErrorForecastService
from app.main import create_app
from app.market.adapter import MemoryMarketSource


@pytest.fixture(scope='module')
def model():
    return ErrorForecastService.from_config()


def history(current=291, *, kind='SIMULATED', source='SIMULATED integration test'):
    return [MarketSnapshot(slot=t, region='eu-north-1', resource_type='GPU', gpu_type='T4',
        price_usd_per_unit_hour=.05 + ((t + 1500) % 17) * .0001,
        available_units=1, source=source, data_kind=kind) for t in range(current - 168, current + 1)]


def test_actual_model_flows_through_engine_with_rebased_clock_and_gpu_alias(model, tmp_path, monkeypatch):
    origin = datetime.fromisoformat(model.origin_utc) + timedelta(hours=1500)
    monkeypatch.setenv('COMPUTE_ORIGIN_UTC', origin.isoformat())
    rows = history()
    app = create_app(tmp_path / 'merged.sqlite3', forecast_service=model,
        market_source=MemoryMarketSource(rows), clock=lambda: origin + timedelta(hours=291), tick_interval_seconds=0)
    client = TestClient(app)
    client.post('/api/jobs', json=dict(id='job', name='test', arrivalSlot=291, durationSlots=1,
        deadlineSlot=294, resourceType='GPU', gpuType='T4', resourceUnits=1, allowedRegions=['eu-north-1']))
    response = client.post('/api/optimize', json=dict(currentSlot=291, forecastMode='ML', executionMode='PAPER'))
    assert response.status_code == 200, response.text
    forecasts = client.get('/api/forecasts').json()
    assert all(row['modelVersion'].startswith('lightgbm-price-l1-v1-gpu-') for row in forecasts)
    assert all(row['gpuType'] == 'T4' and row['generatedAtSlot'] == 291 for row in forecasts)
    assert [row['targetSlot'] for row in forecasts] == list(range(292, 298))
    native = model.predict(ForecastRequest(current_slot=1791, history=[r.model_copy(update={
        'slot': r.slot + 1500, 'gpu_type': 'NVIDIA T4'}) for r in rows]))
    assert [row['predictedPriceUsdPerUnitHour'] for row in forecasts] == pytest.approx(
        [r.predicted_price_usd_per_unit_hour for r in native])
    details = client.get('/api/decisions/details').json()
    assert details and details[-1]['forecastsUsed']
    assert client.get('/api/engine/state').json()['mlConfigured'] is True
    assert client.get('/api/models/status').json()['engineEnabled'] is True
    # Exploratory report must not be relabeled as disjoint held-out evidence.
    assert client.get('/api/models/metrics').json()['status'] == 'UNAVAILABLE'
    assert client.get('/api/jobs').json()[0]['status'] == 'PENDING'
    reopened = TestClient(create_app(tmp_path / 'merged.sqlite3', forecast_service=model,
        market_source=MemoryMarketSource(rows), clock=lambda: origin + timedelta(hours=291), tick_interval_seconds=0))
    assert reopened.get('/api/forecasts').json() == forecasts


def test_regional_index_cannot_be_fed_to_fixed_az_model(model):
    request = ForecastRequest(current_slot=291, history=history(kind='OBSERVED', source='AWS EC2 OBSERVED PRICE INDEX; g4dn.xlarge; eu-north-1a'))
    origin = datetime.fromisoformat(model.origin_utc) + timedelta(hours=1500)
    rows = SelectedModelProvider(model).predict_at(request, origin)
    assert all(r.model_version == 'persistence-v1:fallback-source-identity-mismatch' for r in rows)


def test_ml_replay_can_warm_up_from_fallback_to_actual_model(model, tmp_path):
    origin = datetime.fromisoformat(model.origin_utc) + timedelta(hours=1791)
    scenario = ReplayScenario(id='ml-warmup', description='SIMULATED ML integration, not evaluation',
        origin_utc=origin, end_slot=170, jobs=[JobCreate(id='late', name='late', arrival_slot=168,
            duration_slots=1, deadline_slot=170, resource_type='GPU', gpu_type='T4', resource_units=1,
            allowed_regions=['eu-north-1'])], market=[MarketSnapshot(slot=t, region='eu-north-1',
            resource_type='GPU', gpu_type='T4', price_usd_per_unit_hour=.05 + (t % 17) * .0001,
            available_units=1, source='SIMULATED integration', data_kind='SIMULATED') for t in range(170)])
    client = TestClient(create_app(tmp_path / 'replay.sqlite3', forecast_service=model,
        replay_scenarios={'ml-warmup': scenario}, tick_interval_seconds=0))
    assert client.post('/api/replay/reset', json={'scenarioId': 'ml-warmup', 'seed': 42}).status_code == 200
    first = client.post('/api/replay/step', json={'slots': 1}).json()['strategyStates'][-1]
    assert all('fallback-insufficient-history' in r['modelVersion'] for r in first['forecasts'])
    for slots in [24] * 7 + [1]:
        response = client.post('/api/replay/step', json={'slots': slots})
        assert response.status_code == 200, response.text
    ml = response.json()['strategyStates'][-1]
    assert ml['status'] == 'ACTIVE', ml['error']
    assert any(r['modelVersion'].startswith('lightgbm-price-l1-v1-gpu-') for r in ml['forecasts'])
    assert ml['metrics']['completedJobs'] == 1
    metrics = client.get('/api/metrics').json()['strategies'][-1]
    assert any('fallback-insufficient-history' in version for version in metrics['modelVersions'])
    assert any(version.startswith('lightgbm-price-l1-v1-gpu-') for version in metrics['modelVersions'])
    assert client.get('/api/jobs').json() == []
