from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.api.market_schemas import AwsSpotQuote
from app.database import Database
from app.market.model_history import AwsModelHistory


NOW = datetime(2026, 10, 25, 2, 15, tzinfo=timezone.utc)
BOUNDARY = NOW.replace(minute=0)
IDENTITY = SimpleNamespace(region='eu-north-1', instance_type='p4d.24xlarge',
    availability_zone='eu-north-1c', product_description='Linux/UNIX', gpu_type='NVIDIA A100')
QUOTE = AwsSpotQuote(region=IDENTITY.region, instance_type=IDENTITY.instance_type,
    availability_zone=IDENTITY.availability_zone, availability_zones=[IDENTITY.availability_zone],
    product_description='Linux/UNIX', gpu_type='A100', gpus_per_instance=8,
    cpu_architectures=['x86_64'], price_usd_per_instance_hour=8, price_usd_per_gpu_hour=1,
    effective_at_utc=NOW - timedelta(days=10), observed_at_utc=NOW)


def event(at, price):
    return dict(InstanceType=IDENTITY.instance_type, AvailabilityZone=IDENTITY.availability_zone,
        ProductDescription='Linux/UNIX', Timestamp=at, SpotPrice=str(price))


class Client:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.events = [event(NOW - timedelta(days=10), 8), event(BOUNDARY - timedelta(hours=2, minutes=30), 16)]

    def get_paginator(self, operation):
        assert operation == 'describe_spot_price_history'
        return self

    def paginate(self, **params):
        self.calls.append(params)
        assert params['InstanceTypes'] == [IDENTITY.instance_type]
        assert params['AvailabilityZone'] == IDENTITY.availability_zone
        start, end = params['StartTime'], params['EndTime']
        before = [e for e in self.events if e['Timestamp'] <= start]
        anchor = sorted(before, key=lambda e: e['Timestamp'])[-1:] if before else []
        changes = [e for e in self.events if start < e['Timestamp'] <= end]
        yield {'SpotPriceHistory': deepcopy(anchor)}
        if self.fail:
            raise OSError('private diagnostic must not reach status')
        yield {'SpotPriceHistory': deepcopy(changes)}


def make(tmp_path, client=None, now=None):
    client = client or Client()
    now = now or [NOW]
    store = AwsModelHistory(Database(tmp_path / 'history.sqlite3'), lambda _: client, lambda: now[0])
    return store, client, now


def test_initial_backfill_pagination_normalization_and_restart_reuse(tmp_path):
    store, client, now = make(tmp_path)
    store.ensure(IDENTITY, QUOTE)
    state = store.status()
    assert state['status'] == 'READY' and state['pools'][0]['availableHours'] == 168
    native = store.native_history(IDENTITY, BOUNDARY - timedelta(hours=1000), BOUNDARY)
    assert len(native) == 168 and [r.slot for r in native] == list(range(832, 1000))
    assert native[0].price_usd_per_unit_hour == 1
    assert native[-1].price_usd_per_unit_hour == 2
    assert all(r.available_units is None and r.data_kind == 'OBSERVED' for r in native)
    store.ensure(IDENTITY, QUOTE)
    reopened, _, _ = make(tmp_path, client, now)
    reopened.ensure(IDENTITY, QUOTE)
    assert len(client.calls) == 1
    with store.database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM model_history_fetches').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM model_price_history').fetchone()[0] == 168


def test_hour_rollover_and_offline_gap_fetch_only_missing_period(tmp_path):
    store, client, now = make(tmp_path)
    store.ensure(IDENTITY, QUOTE)
    now[0] += timedelta(hours=1)
    store.ensure(IDENTITY, QUOTE)
    assert client.calls[-1]['StartTime'] == BOUNDARY
    assert client.calls[-1]['EndTime'] == BOUNDARY + timedelta(hours=1)
    now[0] += timedelta(hours=4)
    restarted, _, _ = make(tmp_path, client, now)
    restarted.ensure(IDENTITY, QUOTE)
    assert client.calls[-1]['StartTime'] == BOUNDARY + timedelta(hours=1)
    assert client.calls[-1]['EndTime'] == BOUNDARY + timedelta(hours=5)
    assert restarted.status()['pools'][0]['availableHours'] == 168
    assert len(client.calls) == 3


def test_incomplete_pagination_is_atomic_and_backed_off(tmp_path):
    store, client, now = make(tmp_path)
    client.fail = True
    store.ensure(IDENTITY, QUOTE)
    pool = store.status()['pools'][0]
    assert pool['availableHours'] == 0 and pool['errorCode'] == 'OSError'
    assert 'private diagnostic' not in str(pool)
    with store.database.transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM model_price_history').fetchone()[0] == 0
    store.ensure(IDENTITY, QUOTE)
    assert len(client.calls) == 1
    now[0] += timedelta(seconds=61)
    client.fail = False
    store.ensure(IDENTITY, QUOTE)
    assert store.status()['status'] == 'READY'
    assert len(client.calls) == 2


def test_missing_anchor_stays_missing_and_zero_is_retained(tmp_path):
    store, client, _ = make(tmp_path)
    client.events = [event(BOUNDARY - timedelta(hours=10), 0)]
    store.ensure(IDENTITY, QUOTE)
    pool = store.status()['pools'][0]
    assert pool['availableHours'] == 10 and len(pool['missingHours']) == 158
    rows = store.native_history(IDENTITY, BOUNDARY - timedelta(hours=1000), BOUNDARY)
    assert len(rows) == 10 and all(r.price_usd_per_unit_hour == 0 for r in rows)


def test_retrieval_time_blocks_earlier_decisions(tmp_path):
    import pytest
    store, _, now = make(tmp_path)
    store.ensure(IDENTITY, QUOTE)
    with pytest.raises(ValueError, match='historical/replay'):
        store.native_history(IDENTITY, BOUNDARY - timedelta(hours=1000), BOUNDARY - timedelta(hours=1))
    now[0] -= timedelta(minutes=5)
    assert store.native_history(IDENTITY, BOUNDARY - timedelta(hours=1000), BOUNDARY) == []
