from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

pytest.importorskip('lightgbm')
from app.main import create_app
from app.api.schemas import JobCreate
from app.jobs.store import JobStore


def demo(path):
    return create_app(path, demo_mode=True, demo_slot_seconds=3600, tick_interval_seconds=0)


def test_normal_queue_plans_acquires_runs_completes_and_survives_restart(tmp_path):
    path = tmp_path / 'demo.sqlite3'
    app = demo(path)
    client = TestClient(app)
    state = client.get('/api/engine/state').json()
    assert state['acquisitionMode'] == state['executionMode'] == 'SIMULATED'
    assert state['forecastMode'] == 'ML'
    assert client.get('/api/jobs').json() and client.get('/api/acquisitions').json() == []
    assert client.post('/api/optimize', json={'currentSlot': 168, 'forecastMode': 'ML', 'executionMode': 'SIMULATED'}).status_code == 200
    assert all(j['status'] == 'RUNNING' for j in client.get('/api/jobs').json())
    receipts = client.get('/api/acquisitions').json()
    assert len(receipts) == 3
    assert all(r['stages'] == ['PLANNED', 'ACQUISITION_REQUESTED', 'CAPACITY_ACQUIRED', 'EXECUTION_RUNNING'] for r in receipts)
    assert len(client.get('/api/forecasts').json()) == 252
    assert all(r['dataKind'] == 'SIMULATED' for r in client.get('/api/market').json())
    app.state.engine.tick(169, force=True)
    assert JobStore(app.state.engine.database).get('demo-cpu').status == 'COMPLETED'
    assert JobStore(app.state.engine.database).get('demo-gpu').status == 'RUNNING'
    reopened = demo(path)
    reopened.state.engine.tick(170, force=True)
    assert all(j.status == 'COMPLETED' for j in JobStore(reopened.state.engine.database).list())
    assert {r.id for r in reopened.state.engine.acquisition_provider.list()} == {r['id'] for r in receipts}
    reopened.state.engine.tick(170, force=True)
    assert all(r.status == 'COMPLETED' and r.stages.count('EXECUTION_COMPLETED') == 1 for r in reopened.state.engine.acquisition_provider.list())
    assert TestClient(reopened).get('/api/metrics?scope=LIVE').json()['realizedSpendUsd'] is None
    assert client.get('/api/execution/tasks').json()['tasks'][0]['id'] == 'cpu-hash-v1'
    assert client.post('/api/execute/demo-cpu', json={}).status_code == 409


def test_rejected_acquisition_never_becomes_a_running_job(tmp_path):
    app = demo(tmp_path / 'reject.sqlite3')
    adapter = app.state.engine.acquisition_provider
    original = dict(adapter.capacity)
    adapter.capacity = {key: 0 for key in original}
    app.state.engine.tick(168, force=True)
    assert all(j.status == 'PENDING' for j in JobStore(app.state.engine.database).list())
    assert all(r.status == 'REJECTED' for r in adapter.list())
    with app.state.engine.database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM reservations').fetchone()[0] == 0
    adapter.capacity = original
    app.state.engine.tick(168, force=True)
    assert all(j.status == 'RUNNING' for j in JobStore(app.state.engine.database).list())


def test_new_urgent_job_submitted_from_normal_ui_is_acquired_and_completed(tmp_path):
    app = demo(tmp_path / 'new.sqlite3')
    client = TestClient(app)
    slot = client.get('/api/engine/state').json()['wallClockSlot']
    response = client.post('/api/jobs', json=dict(id='new-urgent', name='New urgent GPU',
        arrivalSlot=slot, durationSlots=1, deadlineSlot=slot+1, resourceType='GPU',
        resourceUnits=1, allowedGpuTypes=['H100'], allowedRegions=['eu-north-1']))
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'RUNNING'
    receipt = next(r for r in client.get('/api/acquisitions').json() if r['jobId'] == 'new-urgent')
    assert receipt['status'] == 'ACQUIRED' and receipt['gpuType'] == 'H100'
    app.state.engine.tick(slot+1, force=True)
    assert next(j for j in client.get('/api/jobs').json() if j['id'] == 'new-urgent')['status'] == 'COMPLETED'


def test_routed_frankfurt_job_runs_there_and_completes_with_original_route_retained(tmp_path):
    app = demo(tmp_path / 'routed.sqlite3')
    engine = app.state.engine
    engine.market_source.capacity[('eu-north-1','GPU','A100')] = 0
    engine.acquisition_provider.capacity[('eu-north-1','GPU','A100')] = 0
    client = TestClient(app)
    slot = engine.state().wall_clock_slot
    response = client.post('/api/jobs', json=dict(id='routed',name='Routed A100',
        arrivalSlot=slot,durationSlots=1,deadlineSlot=slot+1,resourceType='GPU',
        resourceUnits=1,gpuType='A100',allowedRegions=['eu-north-1','eu-central-1']))
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'RUNNING'
    receipt = next(r for r in client.get('/api/acquisitions').json() if r['jobId']=='routed')
    assert receipt['status']=='ACQUIRED' and receipt['region']=='eu-central-1'
    decision = next(d for d in reversed(client.get('/api/decisions').json()) if d['jobId']=='routed')
    assert decision['action']=='ROUTE' and decision['region']=='eu-central-1'
    engine.tick(slot+1,force=True)
    assert next(j for j in client.get('/api/jobs').json() if j['id']=='routed')['status']=='COMPLETED'
    receipt = next(r for r in client.get('/api/acquisitions').json() if r['jobId']=='routed')
    assert receipt['status']=='COMPLETED' and receipt['region']=='eu-central-1'
    assert next(d for d in reversed(client.get('/api/decisions').json()) if d['jobId']=='routed')==decision


def test_pause_blocks_acquisition_but_running_jobs_still_complete(tmp_path):
    app = demo(tmp_path / 'pause.sqlite3')
    engine = app.state.engine
    engine.tick(168)
    engine.pause()
    store = JobStore(engine.database)
    store.create(JobCreate(id='paused', name='Paused demo', arrival_slot=169, duration_slots=1,
        deadline_slot=173, resource_type='CPU', resource_units=1, allowed_regions=['eu-north-1']))
    engine.tick(170, force=True)
    assert all(store.get(id).status == 'COMPLETED' for id in ['demo-cpu','demo-gpu','demo-urgent'])
    assert store.get('paused').status == 'PENDING'
    assert 'paused' not in {r.job_id for r in engine.acquisition_provider.list()}


def test_finite_pool_capacity_is_never_overallocated(tmp_path):
    app = demo(tmp_path / 'finite.sqlite3')
    engine = app.state.engine
    store = JobStore(engine.database)
    for i in range(5):
        store.create(JobCreate(id=f'big-{i}', name='Competing demo', arrival_slot=168,
            duration_slots=1, deadline_slot=169, resource_type='GPU', gpu_type='A10G',
            resource_units=3, priority=10, allowed_regions=['eu-north-1']))
    engine.tick(168)
    with engine.database.transaction() as connection:
        from app.api.schemas import Reservation
        used = defaultdict(int)
        for raw in connection.execute('SELECT payload FROM reservations'):
            r = Reservation.model_validate_json(raw['payload'])
            for slot in range(r.start_slot, r.end_slot):
                used[(r.region, r.resource_type, r.gpu_type, slot)] += r.resource_units
    assert used
    assert all(value <= engine.acquisition_provider.capacity[key[:3]] for key,value in used.items())


def test_demo_never_reuses_a_non_demo_database(tmp_path):
    path = tmp_path / 'existing.sqlite3'
    app = create_app(path, tick_interval_seconds=0)
    store = JobStore(app.state.engine.database)
    store.create(JobCreate(id='keep', name='Preserved real portfolio', arrival_slot=0,
        duration_slots=1, deadline_slot=2, resource_type='CPU', resource_units=1, allowed_regions=['eu-north-1']))
    with pytest.raises(ValueError, match='own database'):
        demo(path)
    assert store.get('keep').status == 'PENDING'


def test_demo_local_execution_uses_persisted_clock_but_preserves_arrival_and_deadline_guards(tmp_path):
    from datetime import datetime, timezone
    class Adapter:
        launches=0
        def prepare(self): return 'sha256:test'
        def launch(self, record): self.launches+=1
        def inspect(self, record):
            return dict(container_id='clock-test',state='exited',started_at_utc=datetime.now(timezone.utc),
                completed_at_utc=datetime.now(timezone.utc),exit_code=0,stdout='done',stderr='',oom=False,error=None)
    adapter=Adapter()
    app=create_app(tmp_path/'clock-floor.sqlite3',demo_mode=True,demo_slot_seconds=10,
        tick_interval_seconds=0,execution_adapter=adapter)
    client=TestClient(app)
    # Persisted scheduling time leads this process's accelerated clock.
    with app.state.engine.database.transaction() as connection:
        state=app.state.engine._load_state(connection)
        state['currentSlot']=180
        app.state.engine._save_state(connection,state)
    store=JobStore(app.state.engine.database)
    for id,arrival,deadline in [('valid',180,200),('future',190,210),('expired',180,180)]:
        store.create(JobCreate(id=id,name=id,arrival_slot=arrival,duration_slots=1,deadline_slot=deadline,
            resource_type='CPU',resource_units=1,allowed_regions=['local'],docker_task_id='cpu-hash-v1'))
    assert client.post('/api/execute/future',json={}).status_code==409
    assert client.post('/api/execute/expired',json={}).status_code==409
    response=client.post('/api/execute/valid',json={})
    assert response.status_code==200,response.text
    assert response.json()['executionMode']=='LOCAL' and response.json()['status']=='COMPLETED'
    assert adapter.launches==1


def test_real_docker_task_in_demo_is_never_simulated_and_uses_real_timeout_clock(tmp_path):
    from datetime import datetime, timezone, timedelta
    class Adapter:
        launches = 0
        observed = None
        def prepare(self):
            return 'sha256:test'
        def launch(self, execution):
            self.launches += 1
            self.observed = dict(container_id='local-demo',state='running',
                started_at_utc=datetime.now(timezone.utc),completed_at_utc=None,
                exit_code=0,stdout='real adapter test',stderr='',oom=False,error=None)
        def inspect(self, execution):
            return self.observed
        def kill(self, execution):
            raise AssertionError('Accelerated simulation clock must not kill a real container')
    adapter=Adapter()
    path=tmp_path/'docker-demo.sqlite3'
    app=create_app(path,demo_mode=True,demo_slot_seconds=10,tick_interval_seconds=0,execution_adapter=adapter)
    client=TestClient(app)
    slot=app.state.engine.state().wall_clock_slot
    created=client.post('/api/jobs',json=dict(id='real-local',name='Real local CPU',
        arrivalSlot=slot,durationSlots=1,deadlineSlot=slot+12,resourceType='CPU',resourceUnits=1,
        allowedRegions=['local'],dockerTaskId='cpu-hash-v1'))
    assert created.status_code==201 and created.json()['status']=='PENDING'
    assert 'real-local' not in {r['jobId'] for r in client.get('/api/acquisitions').json()}
    assert client.get('/api/executions').json()==[]
    assert adapter.launches==0
    app.state.engine.tick(slot,force=True)
    assert next(j for j in client.get('/api/jobs').json() if j['id']=='real-local')['status']=='PENDING'
    assert next(d for d in reversed(client.get('/api/decisions').json()) if d['jobId']=='real-local')['reasonCode']=='LOCAL_EXECUTION_REQUIRED'
    result=client.post('/api/execute/real-local',json={})
    assert result.status_code==200,result.text
    assert result.json()['executionMode']=='LOCAL' and result.json()['status']=='RUNNING'
    assert adapter.launches==1
    # Advancing the simulation past the reserved interval must not fake a real exit.
    app.state.engine.tick(slot+1,force=True)
    assert next(j for j in client.get('/api/jobs').json() if j['id']=='real-local')['status']=='RUNNING'
    adapter.observed.update(state='exited',completed_at_utc=datetime.now(timezone.utc),stdout='done',exit_code=0)
    records=client.get('/api/executions').json()
    assert records[0]['status']=='COMPLETED' and records[0]['stdout']=='done'
    assert next(j for j in client.get('/api/jobs').json() if j['id']=='real-local')['status']=='COMPLETED'
    assert adapter.launches==1
