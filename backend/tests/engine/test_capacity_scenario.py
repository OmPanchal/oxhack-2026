from collections import defaultdict

from fastapi.testclient import TestClient

from app.api.replay_schemas import ReplayShockRequest
from app.database import Database
from app.engine.forecast_bridge import PersistenceForecastProvider
from app.engine.replay_scenarios import capacity_pressure_scenario
from app.engine.simulator import ReplayService
from app.main import create_app


def test_capacity_pressure_respects_every_pool_and_exposes_realized_failures(tmp_path, monkeypatch):
    replay = ReplayService(Database(tmp_path / 'scenario.sqlite3'))
    replay.reset('capacity-pressure', 42)
    checked = []
    charge = replay._charge

    def verify_allocations(run, market, slot, config):
        pools = {(r.region, r.gpu_type): r.available_units for r in market}
        used = defaultdict(int)
        jobs = {j.id: j for j in run.jobs}
        for allocation in run.reservations:
            job = jobs[allocation.job_id]
            key = allocation.region, allocation.gpu_type
            used[key] += allocation.resource_units
            assert used[key] <= pools[key]
            assert allocation.gpu_type in job.allowed_gpu_types
            assert allocation.region in job.allowed_regions
            assert allocation.resource_units == job.resource_units
            assert job.arrival_slot <= allocation.start_slot <= slot < allocation.end_slot <= job.deadline_slot
            checked.append((run.strategy, slot, job.id, allocation.gpu_type))
        charge(run, market, slot, config)

    monkeypatch.setattr(replay, '_charge', verify_allocations)
    for slot in range(8):
        state = replay.step()
        assert max(r.slot for r in state.observed_market) == slot
        assert all(r.data_kind == 'SIMULATED' and 'not AWS inventory' in r.source for r in state.observed_market)
    naive = state.strategy_states[2]
    assert naive.status == 'ACTIVE'
    assert [(d.decided_at_slot, d.action) for d in naive.decisions if d.job_id == 'needs-two'] == [
        (1, 'WAIT'), (2, 'WAIT'), (3, 'WAIT'), (4, 'RUN')]
    assert any(d.job_id == 'route-job' and d.action == 'ROUTE' and d.region == 'eu-central-1' for d in naive.decisions)
    assert any(d.job_id == 'oversized' and d.action == 'INFEASIBLE' for d in naive.decisions)
    assert any(o.reason == 'REALIZED_CAPACITY_LOSS' for o in naive.outcomes)
    assert ('OPTIMIZER_WITH_NAIVE_FORECAST', 0, 'gpu-choice', 'T4') in checked
    assert naive.metrics.completed_jobs == 4
    assert naive.metrics.failed_jobs == 2
    assert naive.metrics.infeasible_jobs == 1
    assert naive.metrics.unfinished_jobs == 0
    assert state.strategy_states[-1].status == 'UNAVAILABLE'


def test_capacity_scenario_reset_restart_and_shock_are_reproducible(tmp_path):
    database = Database(tmp_path / 'repeat.sqlite3')
    replay = ReplayService(database)
    shock = ReplayShockRequest(kind='CAPACITY_SHORTAGE', slot=1, region='eu-north-1',
                              resource_type='GPU', gpu_type='T4', magnitude=1)
    replay.reset('capacity-pressure', 42)
    replay.shock(shock)
    expected = replay.step(8).model_dump(mode='json')
    replay.reset('capacity-pressure', 42)
    replay.shock(shock)
    replay.step(2)
    restarted = ReplayService(Database(database.path))
    actual = restarted.step(6).model_dump(mode='json')
    assert actual == expected
    assert replay.scenarios['capacity-pressure'] == capacity_pressure_scenario()


def test_forecasting_does_not_receive_later_capacity_profile(tmp_path):
    class RecordingProvider(PersistenceForecastProvider):
        def __init__(self):
            self.requests = []

        def predict(self, request):
            self.requests.append(request.model_copy(deep=True))
            return super().predict(request)

    replay = ReplayService(Database(tmp_path / 'visibility.sqlite3'),
                           forecast_services={'NAIVE': RecordingProvider()})
    replay.reset('capacity-pressure', 42)
    replay.step(2)
    requests = replay.providers['NAIVE'].requests
    assert [request.current_slot for request in requests] == [0, 1]
    for request in requests:
        assert all(row.slot <= request.current_slot for row in request.history)
        assert not any(row.available_units == 0 for row in request.history)


def test_default_api_exposes_scenario_without_changing_live_capacity(tmp_path):
    client = TestClient(create_app(tmp_path / 'api.sqlite3', tick_interval_seconds=0))
    live_before = client.get('/api/market').json()
    response = client.post('/api/replay/reset', json={'scenarioId': 'capacity-pressure', 'seed': 42})
    assert response.status_code == 200
    assert response.json()['observedMarket'] == []
    assert 'not live AWS' in response.json()['description']
    first = client.post('/api/replay/step', json={'slots': 1}).json()
    assert len(first['observedMarket']) == 3
    assert {(r['gpuType'], r['availableUnits']) for r in first['observedMarket']} == {('A10G', 2), ('A10G', 1), ('T4', 1)}
    assert client.get('/api/market').json() == live_before
    assert client.get('/api/jobs').json() == []
    assert client.get('/api/decisions').json() == []
