from collections import Counter

import pytest
from fastapi.testclient import TestClient

pytest.importorskip('lightgbm')
from app.forecasting.error_service import ErrorForecastService
from app.main import create_app


def test_all_model_pools_flow_through_optimizer_and_persisted_replay(tmp_path):
    model = ErrorForecastService.from_config()
    path = tmp_path / 'all-models.sqlite3'
    client = TestClient(create_app(path, forecast_service=model, tick_interval_seconds=0))
    initial = client.post('/api/replay/reset', json={'scenarioId': 'model-coverage', 'seed': 42})
    assert initial.status_code == 200, initial.text
    assert initial.json()['currentSlot'] == 168
    assert len(initial.json()['observedMarket']) == 42 * 168
    assert max(r['slot'] for r in initial.json()['observedMarket']) == 167
    first = client.post('/api/replay/step', json={'slots': 1})
    assert first.status_code == 200, first.text
    ml = first.json()['strategyStates'][-1]
    assert ml['status'] == 'ACTIVE', ml['error']
    assert len(ml['forecasts']) == 252
    assert Counter(r['resourceType'] for r in ml['forecasts']) == {'CPU': 36, 'GPU': 216}
    assert len({r['region'] for r in ml['forecasts']}) == 6
    assert sum(r['modelVersion'].startswith('lightgbm-') for r in ml['forecasts']) == 246
    assert ml['metrics']['completedJobs'] == 42
    response = client.get('/api/metrics?scope=REPLAY')
    assert response.status_code == 200, response.text
    assert all(r['ledgerReconciled'] for r in response.json()['strategies'])
    assert client.get('/api/jobs').json() == []
    assert client.get('/api/market').json() == []
    reopened = TestClient(create_app(path, forecast_service=model, tick_interval_seconds=0))
    assert reopened.get('/api/metrics?scope=REPLAY').json() == response.json()
    final = reopened.post('/api/replay/step', json={'slots': 7})
    assert final.status_code == 200, final.text
    assert final.json()['status'] == 'COMPLETED'
    metrics = reopened.get('/api/metrics?scope=REPLAY').json()
    assert metrics['status'] == 'COMPLETED'
    assert all(r['totals']['completedJobs'] == 42 for r in metrics['strategies'])
    assert all(r['totals']['failedJobs'] == 0 for r in metrics['strategies'])


def test_warmup_cannot_hide_execution_or_reveal_future_observations():
    from app.engine.replay_scenarios import model_coverage_scenario
    from app.api.replay_schemas import ReplayScenario
    scenario = model_coverage_scenario(ErrorForecastService.from_config())
    data = scenario.model_dump()
    data['jobs'][0]['arrival_slot'] = 0
    with pytest.raises(ValueError, match='warmup'):
        ReplayScenario.model_validate(data)
