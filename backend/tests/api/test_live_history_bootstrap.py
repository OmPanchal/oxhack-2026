from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

pytest.importorskip('lightgbm')

from app.forecasting.error_service import ErrorForecastService
from app.main import create_app
from app.market.aws import AwsSpotMarket


def test_live_bootstrap_works_before_engine_origin_and_never_seeds_replay(tmp_path):
    now = [datetime(2026, 10, 25, 2, 15, tzinfo=timezone.utc)]
    class Ec2:
        history_calls = 0
        def describe_instance_types(self, **params):
            return {'InstanceTypes': [dict(InstanceType='g5.xlarge', SupportedUsageClasses=['spot'],
                GpuInfo={'Gpus': [dict(Name='A10G', Count=1, MemoryInfo={'SizeInMiB': 24576})]})]}
        def describe_instance_type_offerings(self, **params):
            return {'InstanceTypeOfferings': [dict(InstanceType='g5.xlarge', Location='eu-north-1b')]}
        def describe_spot_price_history(self, **params):
            return {'SpotPriceHistory': [dict(InstanceType='g5.xlarge', AvailabilityZone='eu-north-1b',
                ProductDescription='Linux/UNIX', SpotPrice='0.25', Timestamp=now[0] - timedelta(days=10))]}
        def get_paginator(self, operation):
            return self
        def paginate(self, **params):
            self.history_calls += 1
            yield self.describe_spot_price_history()
    model = ErrorForecastService.from_config()
    path = tmp_path / 'live.sqlite3'
    ec2 = Ec2()
    source = AwsSpotMarket(['eu-north-1'], client_factory=lambda _: ec2, clock=lambda: now[0])
    client = TestClient(create_app(path, aws_market=source, forecast_service=model, clock=lambda: now[0], tick_interval_seconds=0))
    result = client.post('/api/optimize', json={'currentSlot': 0, 'forecastMode': 'ML', 'executionMode': 'PAPER'})
    assert result.status_code == 200, result.text
    rows = client.get('/api/forecasts').json()
    assert len(rows) == 6 and all(r['modelVersion'].startswith('lightgbm-price-l1-v1-gpu-') for r in rows)
    assert client.get('/api/models/status').json()['history']['status'] == 'READY'
    assert all(r['slot'] == 0 for r in client.get('/api/market').json())
    # Reopening a process/database must use the saved backfill without fetching it again.
    new_ec2 = Ec2()
    restarted = TestClient(create_app(path, aws_market=AwsSpotMarket(['eu-north-1'],
        client_factory=lambda _: new_ec2, clock=lambda: now[0]), forecast_service=model,
        clock=lambda: now[0], tick_interval_seconds=0))
    assert restarted.post('/api/optimize', json={'currentSlot': 0, 'forecastMode': 'ML'}).status_code == 200
    assert new_ec2.history_calls == 0
    # Replay uses a separate provider and cannot use retrospective live history.
    assert restarted.post('/api/replay/reset', json={'scenarioId': 'capacity-pressure', 'seed': 42}).status_code == 200
    ml = restarted.post('/api/replay/step', json={'slots': 1}).json()['strategyStates'][-1]
    assert all('fallback-model-not-available' in row['modelVersion'] for row in ml['forecasts'])
    assert new_ec2.history_calls == 0
