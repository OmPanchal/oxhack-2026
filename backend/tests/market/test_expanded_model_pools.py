from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip('lightgbm')
from app.database import Database
from app.forecasting.error_service import ErrorForecastService
from app.market.aws import AwsSpotMarket
from app.market.model_history import AwsModelHistory

NOW = datetime(2026, 10, 25, 3, 15, tzinfo=timezone.utc)


class Ec2:
    def __init__(self, identities):
        self.zones = {s.availability_zone: f'us-east-1{chr(97 + n)}'
                      for n, s in enumerate(identities)}
        self.identities = {s.instance_type: s for s in identities}
        self.requests = []

    def describe_availability_zones(self, **params):
        self.requests.append(('zones', params))
        return {'AvailabilityZones': [dict(ZoneId=z, ZoneName=self.zones[z], RegionName='us-east-1') for z in params['ZoneIds'] if z in self.zones]}

    def describe_instance_types(self, **params):
        names = params.get('InstanceTypes', ['g4dn.xlarge'])
        return {'InstanceTypes': [dict(InstanceType=n, SupportedUsageClasses=['spot'],
            VCpuInfo={'DefaultVCpus': 4}, ProcessorInfo={'SupportedArchitectures': ['x86_64']},
            GpuInfo={'Gpus': [dict(Name='T4', Count=1)]} if n.startswith('g') else {}) for n in names]}

    def describe_instance_type_offerings(self, **params):
        return {'InstanceTypeOfferings': [dict(InstanceType='g4dn.xlarge', Location=self.zones[self.identities['g4dn.xlarge'].availability_zone])]}

    def describe_spot_price_history(self, **params):
        self.requests.append(('prices', params))
        name = params['InstanceTypes'][0]
        zone = self.zones[self.identities[name].availability_zone]
        return {'SpotPriceHistory': [dict(InstanceType=name, AvailabilityZone=zone,
            ProductDescription='Linux/UNIX', SpotPrice='0.8' if name.startswith('m') else '0.4',
            Timestamp=NOW - timedelta(days=10))]}

    def get_paginator(self, operation):
        return self

    def paginate(self, **params):
        yield self.describe_spot_price_history(**params)


def test_cpu_gpu_global_az_mapping_units_backfill_and_region_scope(tmp_path):
    model = ErrorForecastService.from_config()
    selections = [s for s in model.selections.values() if s.region == 'us-east-1'
                  and (s.resource_type == 'CPU' or s.gpu_type == 'NVIDIA T4')]
    client = Ec2(selections)
    regions = []
    def factory(region):
        regions.append(region)
        assert region == 'us-east-1'  # No implicit reads in the other five model regions.
        return client
    market = AwsSpotMarket(['us-east-1'], client_factory=factory, clock=lambda: NOW,
                           pool_selections=list(model.selections.values()))
    market.model_history = AwsModelHistory(Database(tmp_path / 'history.sqlite3'), factory, lambda: NOW)
    origin = NOW.replace(minute=0)
    rows = market.poll_with_origin(0, origin)
    assert len(rows) == 2
    cpu = next(r for r in rows if r.resource_type == 'CPU')
    assert cpu.gpu_type is None and cpu.price_usd_per_unit_hour == .2  # $0.8 / four vCPUs
    gpu = next(r for r in rows if r.resource_type == 'GPU')
    assert gpu.gpu_type == 'T4' and gpu.price_usd_per_unit_hour == .4
    assert all(r.available_units is None and r.data_kind == 'OBSERVED' for r in rows)
    assert set(regions) == {'us-east-1'}
    for identity in selections:
        native = market.model_history.native_history(identity,
            datetime.fromisoformat(model.origin_utc), origin)
        assert len(native) == 168
        assert all(r.resource_type == identity.resource_type for r in native)
        assert all(identity.availability_zone in r.source for r in native)
        assert native[-1].price_usd_per_unit_hour == (.2 if identity.resource_type == 'CPU' else .4)
    assert all(call['AvailabilityZone'] in client.zones.values() for op, call in client.requests if op == 'prices' and 'AvailabilityZone' in call)


def test_mapping_failure_does_not_guess_or_discard_other_supported_pools():
    from types import SimpleNamespace
    model = ErrorForecastService.from_config()
    selected = [s for s in model.selections.values() if s.region == 'us-east-1'
                and (s.resource_type == 'CPU' or s.gpu_type == 'NVIDIA T4')]
    client = Ec2(selected)
    cpu = next(s for s in selected if s.resource_type == 'CPU')
    # Verify partial feeds remain usable when one pool's metadata cannot resolve.
    original = client.describe_instance_types
    def describe(**params):
        if params.get('InstanceTypes') == [cpu.instance_type]:
            raise PermissionError('CPU read denied')
        return original(**params)
    client.describe_instance_types = describe
    market = AwsSpotMarket(['us-east-1'], client_factory=lambda _: client, clock=lambda: NOW, pool_selections=selected)
    rows = market.poll_with_origin(0, NOW.replace(minute=0))
    assert len(rows) == 1 and rows[0].resource_type == 'GPU'
    assert market.fixed_pool_reader.errors[0]['resourceType'] == 'CPU'
    client.zones.clear()
    market.fixed_pool_reader.zones.clear()
    with pytest.raises(Exception, match='No configured fixed'):
        market.poll_with_origin(0, NOW.replace(minute=0))


def test_live_cpu_gpu_history_reaches_engine_model_without_invented_capacity(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    model = ErrorForecastService.from_config()
    selected = [s for s in model.selections.values() if s.region == 'us-east-1'
                and (s.resource_type == 'CPU' or s.gpu_type == 'NVIDIA T4')]
    ec2 = Ec2(selected)
    market = AwsSpotMarket(['us-east-1'], client_factory=lambda _: ec2, clock=lambda: NOW)
    client = TestClient(create_app(tmp_path / 'live.sqlite3', aws_market=market,
        forecast_service=model, clock=lambda: NOW, tick_interval_seconds=0))
    for resource in ['CPU', 'GPU']:
        created = client.post('/api/jobs', json=dict(id=resource, name=resource,
            resourceType=resource, resourceUnits=1, arrivalSlot=0, durationSlots=1,
            deadlineSlot=3, allowedRegions=['us-east-1'],
            allowedGpuTypes=['T4'] if resource == 'GPU' else []))
        assert created.status_code == 201, created.text
    result = client.post('/api/optimize', json={'currentSlot': 0, 'forecastMode': 'ML'})
    assert result.status_code == 200, result.text
    forecasts = client.get('/api/forecasts').json()
    assert len(forecasts) == 12
    assert {r['resourceType'] for r in forecasts} == {'CPU', 'GPU'}
    assert all(r['modelVersion'].startswith('lightgbm-') for r in forecasts)
    assert all(r['generatedAtSlot'] == 0 for r in forecasts)
    assert all(j['status'] == 'PENDING' for j in client.get('/api/jobs').json())
    assert all(r['availableUnits'] is None for r in client.get('/api/market').json())
    status = client.get('/api/models/status').json()
    assert status['history']['status'] == 'READY'
    assert {r['resourceType'] for r in status['history']['pools']} == {'CPU', 'GPU'}
