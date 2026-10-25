"""Isolated UI audit fixture: every market observation is SIMULATED."""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
TEMP = tempfile.TemporaryDirectory(prefix='arbitr-ui-audit-')
os.environ['COMPUTE_DB_PATH'] = str(Path(TEMP.name) / 'unused.sqlite3')
os.environ['COMPUTE_MARKET_SOURCE'] = 'none'
os.environ['COMPUTE_ENABLE_ML'] = '0'
os.environ['COMPUTE_DEMO'] = '0'
from app.main import create_app
from app.api.schemas import MarketSnapshot, JobCreate
from app.forecasting.error_service import ErrorForecastService
from app.market.adapter import MemoryMarketSource
from app.jobs.store import JobStore
model = ErrorForecastService.from_config()
origin = datetime.fromisoformat(model.origin_utc) + timedelta(hours=1970)
now = origin + timedelta(hours=168)
rows = [MarketSnapshot(slot=t,region=s.region,resourceType=s.resource_type,
    gpuType=s.gpu_type.removeprefix('NVIDIA ') or None,
    priceUsdPerUnitHour=(.03 if s.resource_type == 'CPU' else .2)+(t%17)*.001,
    availableUnits=4 if s.resource_type=='CPU' else None,
    source='SIMULATED isolated endpoint/UI audit; not live AWS data', dataKind='SIMULATED')
    for s in model.selections.values() for t in range(169)]
app = create_app(Path(TEMP.name) / 'fixture.sqlite3',market_source=MemoryMarketSource(rows),
    clock=lambda:now,forecast_service=model,tick_interval_seconds=0)
# Set the engine clock explicitly for this isolated database.
app.state.engine.origin = origin
store = JobStore(app.state.engine.database)
if not store.list():
    store.create(JobCreate(id='audit-cpu',name='SIMULATED CPU audit',arrivalSlot=168,durationSlots=1,
        deadlineSlot=169,resourceType='CPU',resourceUnits=1,allowedRegions=['eu-north-1']))
    store.create(JobCreate(id='audit-gpu',name='SIMULATED GPU audit',arrivalSlot=168,durationSlots=1,
        deadlineSlot=169,resourceType='GPU',resourceUnits=1,allowedGpuTypes=['A100','H100'],allowedRegions=['eu-north-1']))
app.state.engine.tick(168,forecast_mode='ML',execution_mode='PAPER',force=True)
app.state.replay.reset('model-coverage')

if __name__ == '__main__':
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8011)
    args = parser.parse_args()
    print('SIMULATED integration fixture only. No AWS calls or Docker execution. Database:', TEMP.name, flush=True)
    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port)
    finally:
        TEMP.cleanup()
