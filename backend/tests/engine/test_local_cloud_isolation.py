import pytest

from app.api.schemas import JobCreate, MarketSnapshot
from app.database import Database
from app.engine.scheduling import SchedulingService
from app.jobs.store import JobStore


@pytest.mark.parametrize('mode', ['PAPER', 'SIMULATED', 'LOCAL'])
def test_local_tasks_never_use_cloud_market_coverage_or_become_cloud_infeasible(tmp_path, mode):
    db = Database(tmp_path / 'local.sqlite3')
    store = JobStore(db)
    store.create(JobCreate(id='local',name='Local CPU task',arrival_slot=0,duration_slots=1,
        deadline_slot=2,resource_type='CPU',resource_units=1,
        allowed_regions=['local'],docker_task_id='cpu-hash-v1'))
    service = SchedulingService(db)
    for slot in [0,1,2,3]:
        market = [MarketSnapshot(slot=slot,region='eu-north-1',resource_type='GPU',gpu_type='T4',
            price_usd_per_unit_hour=.1,available_units=None,source='test observed price',data_kind='OBSERVED')]
        with db.transaction() as connection:
            decision = service.run_in_transaction(connection,current_slot=slot,market=market,
                                                  forecasts=[],execution_mode=mode).decisions[0]
        assert decision.reason_code == 'LOCAL_EXECUTION_REQUIRED'
        assert decision.execution_mode == 'LOCAL'
        assert store.get('local').status == 'PENDING'
    with db.transaction() as connection:
        from app.api.runtime_schemas import DecisionDetail
        detail=DecisionDetail.model_validate_json(connection.execute('SELECT payload FROM decision_details ORDER BY decision_id DESC LIMIT 1').fetchone()['payload'])
        assert detail.execution_mode == 'LOCAL'
