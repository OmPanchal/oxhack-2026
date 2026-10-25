from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

pytest.importorskip('lightgbm')
ROOT=Path(__file__).resolve().parents[3]


def payload(*, full=True):
    current=2200
    return dict(currentSlot=current,horizonSlots=6,history=[dict(slot=t,
        region='eu-north-1',resourceType='GPU',gpuType='NVIDIA T4',
        priceUsdPerUnitHour=.05+(t%17)*.0001,availableUnits=1,
        source='SIMULATED API test',dataKind='SIMULATED')
        for t in (range(current-168,current+1) if full else [current])])


def test_explicit_ml_inference_does_not_replace_server_forecasts():
    client=TestClient(create_app())
    assert client.get('/api/forecasts').json()==[]
    data=payload()
    response=client.post('/api/forecasts',json=data)
    assert response.status_code==200,response.text
    rows=response.json()
    assert len(rows)==6
    assert all(r['modelVersion'].startswith('lightgbm-price-l1-v1-gpu-') for r in rows)
    assert all(r['generatedAtSlot']==2200 for r in rows)
    assert all('predicted_price_usd_per_unit_hour' not in r for r in rows)
    assert client.get('/api/forecasts').json()==[]
    status=client.get('/api/models/status').json()
    assert status['status']=='READY' and status['defaultForecastMode']=='ML'
    assert 'availabilityZone' in status['poolSelections'][0]
    assert TestClient(create_app()).get('/api/forecasts').json()==[]


def test_naive_mode_does_not_require_model_artifacts(monkeypatch,tmp_path):
    monkeypatch.setenv('PRICE_MODEL_DIR',str(tmp_path/'missing'))
    client=TestClient(create_app())
    data=payload(full=False)
    response=client.post('/api/forecasts?forecastMode=NAIVE',json=data)
    assert response.status_code==200
    assert all(r['modelVersion']=='persistence-v1' for r in response.json())
    assert client.post('/api/forecasts',json=data).status_code==503
    assert client.get('/api/models/status').json()['status']=='UNAVAILABLE'


def test_fallback_validation_and_cache_atomicity():
    client=TestClient(create_app())
    response=client.post('/api/forecasts',json=payload(full=False))
    assert response.status_code==200
    assert all(r['modelVersion']=='persistence-v1:fallback-insufficient-history' for r in response.json())
    saved=client.get('/api/forecasts').json()
    bad=payload();bad['currentSlot']+=1
    assert client.post('/api/forecasts',json=bad).status_code==422
    bad=payload();bad['history'][0]['slot']=2400
    assert client.post('/api/forecasts',json=bad).status_code==422
    assert client.get('/api/forecasts').json()==saved
    assert client.post('/api/forecasts?forecastMode=INVALID',json=payload()).status_code==422


def test_packaged_example_matches_person1_service_output():
    import json
    from app.api.schemas import ForecastRequest
    from app.forecasting.error_service import ErrorForecastService
    data=json.loads((ROOT/'data/examples/ml-forecast-request.simulated.json').read_text())
    expected=ErrorForecastService.from_config().predict(ForecastRequest.model_validate(data))
    response=TestClient(create_app()).post('/api/forecasts',json=data)
    assert response.status_code==200
    assert len(response.json())==12
    assert response.json()==[row.model_dump(by_alias=True,mode='json') for row in expected]
    assert all(row['modelVersion'].startswith('lightgbm-price-l1-v1-') for row in response.json())
