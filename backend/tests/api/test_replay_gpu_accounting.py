import json

import pytest
from fastapi.testclient import TestClient

from app.engine.forecast_bridge import PersistenceForecastProvider
from app.main import create_app


def client_for(path):
    return TestClient(create_app(path, tick_interval_seconds=0,
        forecast_services={'ML': PersistenceForecastProvider()}))


def test_capacity_metrics_use_allocated_gpu_at_every_step_and_after_restart(tmp_path):
    path = tmp_path / 'gpu-accounting.sqlite3'
    client = client_for(path)
    assert client.post('/api/replay/reset', json={'scenarioId': 'capacity-pressure'}).status_code == 200
    for slot in range(8):
        state = client.post('/api/replay/step', json={'slots': 1})
        assert state.status_code == 200, state.text
        response = client.get('/api/metrics?scope=REPLAY')
        assert response.status_code == 200, response.text
        assert response.json()['asOfSlot'] == slot + 1
        assert all(run['ledgerReconciled'] for run in response.json()['strategies'])
        if slot == 0:
            naive = state.json()['strategyStates'][2]
            assert next(j for j in naive['jobs'] if j['id'] == 'gpu-choice')['gpuType'] is None
            charge = next(c for c in naive['charges'] if c['jobId'] == 'gpu-choice')
            assert charge['gpuType'] == 'T4'
            assert charge['computeUsd'] == .2
            # Persisted charges retain their selected pool across process reload.
            client = client_for(path)
            assert client.get('/api/metrics?scope=REPLAY').json() == response.json()
    assert response.json()['status'] == 'COMPLETED'
    naive = response.json()['strategies'][2]
    assert naive['totals']['completedJobs'] == 4
    assert naive['totals']['failedJobs'] == 2
    assert naive['totals']['infeasibleJobs'] == 1


@pytest.mark.parametrize('corruption', ['incompatible', 'price', 'missing-observation', 'changed-model'])
def test_gpu_ledger_still_rejects_corruption(tmp_path, corruption):
    client = client_for(tmp_path / 'invalid.sqlite3')
    client.post('/api/replay/reset', json={'scenarioId': 'capacity-pressure'})
    client.post('/api/replay/step', json={'slots': 2})
    replay = client.app.state.replay
    with replay.database.transaction() as connection:
        session = replay._load(connection)
        run = session.runs[2]
        charge = next(c for c in run.charges if c.job_id == 'gpu-choice')
        if corruption == 'incompatible':
            charge.gpu_type = 'H100'
        elif corruption == 'price':
            charge.compute_usd = .4  # A10G price must not replace the allocated T4 price.
        elif corruption == 'missing-observation':
            session.history = [r for r in session.history if not (r.slot == charge.slot and r.gpu_type == 'T4')]
        else:
            later = next(c for c in run.charges if c.job_id == 'gpu-choice' and c.slot == 1)
            later.gpu_type = 'A10G'
        replay._save(connection, session)
    response = client.get('/api/metrics?scope=REPLAY')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'METRICS_LEDGER_MISMATCH'


@pytest.mark.parametrize('ambiguous', [False, True])
def test_old_persisted_ledgers_require_reset_only_when_gpu_identity_is_ambiguous(tmp_path, ambiguous):
    client = client_for(tmp_path / 'legacy.sqlite3')
    client.post('/api/replay/reset', json={'scenarioId': 'capacity-pressure'})
    client.post('/api/replay/step', json={'slots': 1})
    replay = client.app.state.replay
    with replay.database.transaction() as connection:
        raw = json.loads(connection.execute('SELECT payload FROM replay_session WHERE id=1').fetchone()['payload'])
        for run in raw['runs']:
            for charge in run['charges']:
                if ambiguous or charge['jobId'] != 'gpu-choice':
                    charge.pop('gpuType')
        connection.execute('UPDATE replay_session SET payload=? WHERE id=1', (json.dumps(raw),))
    response = client.get('/api/metrics?scope=REPLAY')
    if ambiguous:
        assert response.status_code == 409
        assert 'reset replay' in response.json()['detail']['message'].lower()
        assert client.post('/api/replay/reset', json={'scenarioId': 'capacity-pressure'}).status_code == 200
        client.post('/api/replay/step', json={'slots': 1})
        assert client.get('/api/metrics?scope=REPLAY').status_code == 200
    else:
        assert response.status_code == 200, response.text
