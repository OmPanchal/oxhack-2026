from copy import deepcopy
import json
from pathlib import Path
import pytest

pytest.importorskip('lightgbm')
pytest.importorskip('numpy')
from app.api.schemas import ForecastRequest, MarketSnapshot
from app.forecasting.error_service import DEFAULT_CONFIG, ErrorForecastService

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture(scope='module')
def service():
    return ErrorForecastService.from_config()


def request(service, *, resource='GPU', gpu='NVIDIA T4', current=2200, full=True):
    identity=next(s for s in service.selections.values() if s.resource_type==resource and (resource=='CPU' or s.gpu_type==gpu))
    rows=[MarketSnapshot(slot=t, region=identity.region,resourceType=resource,
        gpuType=identity.gpu_type or None,priceUsdPerUnitHour=.05+(t%17)*.0001,
        availableUnits=1,source='SIMULATED inference test',dataKind='SIMULATED')
        for t in (range(current-168,current+1) if full else [current])]
    return ForecastRequest(currentSlot=current,history=rows)


def test_selected_native_models_contract_and_parity(service):
    for resource in ('CPU','GPU'):
        data=request(service,resource=resource)
        identity=service.selections[(data.history[0].region,resource,data.history[0].gpu_type or '')]
        model=service.models[resource]
        history={r.slot:r.price_usd_per_unit_hour for r in data.history}
        expected=[model.predict(history,identity,data.current_slot,h) for h in range(1,7)]
        rows=service.predict(data)
        assert [r.predicted_price_usd_per_unit_hour for r in rows]==pytest.approx(expected,abs=1e-13)
        assert [r.target_slot for r in rows]==list(range(data.current_slot+1,data.current_slot+7))
        assert all(r.model_version.startswith('lightgbm-price-l1-v1-') for r in rows)
        assert all(r.price_lower_bound is None and r.price_upper_bound is None and
            r.availability_probability is None and r.interruption_probability is None for r in rows)


@pytest.mark.parametrize('horizon',range(1,7))
def test_horizon_coverage(service,horizon):
    data=request(service);data.horizon_slots=horizon
    assert len(service.predict(data))==horizon


def test_explicit_fallbacks_and_empty_history(service):
    for data,reason in [(request(service,full=False),'insufficient-history'),
                        (request(service,current=1577),'model-not-available'),
                        (request(service,gpu='NVIDIA B200'),'unsupported-pool')]:
        rows=service.predict(data)
        assert all(r.model_version==f'persistence-v1:fallback-{reason}' for r in rows)
        assert all(r.predicted_price_usd_per_unit_hour==data.history[-1].price_usd_per_unit_hour for r in rows)
    data=request(service)
    for row in data.history:
        row.region='unmapped-region'
    assert all(r.model_version.endswith('fallback-unmapped-pool') for r in service.predict(data))
    assert service.predict(ForecastRequest(currentSlot=2200,history=[]))==[]


def test_rejects_stale_conflicting_and_forecast_history(service):
    data=request(service);data.current_slot+=1
    with pytest.raises(ValueError,match='Stale'):
        service.predict(data)
    data=request(service);bad=deepcopy(data.history[-1]);bad.price_usd_per_unit_hour+=1;data.history.append(bad)
    with pytest.raises(ValueError,match='Conflicting'):
        service.predict(data)
    data=request(service);data.history[0].data_kind='FORECAST'
    with pytest.raises(ValueError,match='observations'):
        service.predict(data)


def test_config_refuses_duplicate_pool_and_corrupted_artifact(service,tmp_path):
    selected=next(iter(service.selections.values()))
    with pytest.raises(ValueError,match='one instance'):
        ErrorForecastService(service.models,[selected,selected],origin_utc=service.origin_utc,
                             available_from_slot=service.available_from_slot)
    config=json.loads((ROOT/'data/forecast-serving-stockholm-v1.json').read_text())
    config['modelsDirectory']=str(tmp_path)
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    for item in json.loads((ROOT/config['artifactReceipt']).read_text())['files']:
        name=Path(item['path']).name
        (tmp_path/name).write_bytes((ROOT/item['path']).read_bytes())
    (tmp_path/'CPU-scaled-l1-31.txt').write_text('corrupt')
    with pytest.raises(ValueError,match='checksum'):
        ErrorForecastService.from_config(path)


def test_model_status_has_clock_pool_identity_and_verified_metrics(service):
    status=service.status()
    assert status['defaultForecastMode']=='ML'
    assert status['originUtc']=='2026-07-28T00:00:00+00:00'
    assert status['evaluation'] is None
    assert len(status['routes']) == 12
    assert status['availableFromSlot'] == 2136
    assert 'availabilityZone' in status['poolSelections'][0]
    assert 'availability_zone' not in status['poolSelections'][0]


def test_constant_prices_spikes_zero_and_determinism(service):
    import math
    data=request(service)
    for row in data.history:
        row.price_usd_per_unit_hour=.1
    constant=service.predict(data)
    assert constant==service.predict(data)
    data.history[-1].price_usd_per_unit_hour=1000
    assert all(math.isfinite(r.predicted_price_usd_per_unit_hour) and r.predicted_price_usd_per_unit_hour>=0
               for r in service.predict(data))
    data.history[-1].price_usd_per_unit_hour=0
    assert all(r.model_version.endswith('fallback-zero-current-price') for r in service.predict(data))
