from datetime import datetime, timedelta, timezone

import pytest

from app.api.market_schemas import AwsSpotPrices, AwsSpotQuote
from app.database import Database
from app.market.history import AwsQuoteArchive, hourly_history


NOW = datetime(2026, 10, 25, 10, 5, tzinfo=timezone.utc)


def batch(at=NOW, price=2, zone='eu-north-1a'):
    return AwsSpotPrices(status='READY', fetched_at_utc=at, quotes=[AwsSpotQuote(
        region='eu-north-1', instance_type='p4d.24xlarge', gpu_type='A100',
        gpus_per_instance=8, cpu_architectures=['x86_64'], availability_zones=[zone],
        availability_zone=zone, product_description='Linux/UNIX',
        price_usd_per_instance_hour=price, price_usd_per_gpu_hour=price / 8,
        effective_at_utc=NOW - timedelta(days=1), observed_at_utc=at,
    )])


def test_restart_and_duplicate_poll_preserve_exact_vintages(tmp_path):
    path = tmp_path / 'history.sqlite3'
    archive = AwsQuoteArchive(Database(path))
    first = batch()
    archive.record(first, NOW)
    archive.record(first, NOW + timedelta(seconds=1))
    archive.record(batch(NOW + timedelta(minutes=10), price=4), NOW + timedelta(minutes=10))
    archive.record(batch(NOW + timedelta(hours=1), price=6), NOW + timedelta(hours=1))
    reopened = AwsQuoteArchive(Database(path))
    records = reopened.batches(NOW + timedelta(hours=2))
    assert len(records) == 3
    assert [b.quotes[0].price_usd_per_instance_hour for _, b in records] == [2, 4, 6]
    report = hourly_history(reopened, NOW + timedelta(hours=2))
    assert [r['priceUsdPerInstanceHour'] for r in report['samples']] == [2, 6]
    row = report['samples'][0]
    assert row['priceUsdPerGpuHour'] == .25
    assert row['instanceType'] == 'p4d.24xlarge' and row['gpusPerInstance'] == 8
    assert row['availableUnits'] is None and row['dataKind'] == 'OBSERVED'
    assert row['effectiveAtUtc'].startswith('2026-10-24')


def test_cutoff_uses_receipt_time_not_backdated_effective_or_request_start(tmp_path):
    archive = AwsQuoteArchive(Database(tmp_path / 'history.sqlite3'))
    archive.record(batch(), NOW + timedelta(seconds=30))
    archive.record(batch(NOW + timedelta(minutes=10), price=4), NOW + timedelta(minutes=10))
    assert hourly_history(archive, NOW + timedelta(seconds=10))['samples'] == []
    report = hourly_history(archive, NOW + timedelta(seconds=30))
    assert report['batchCount'] == 1
    assert report['samples'][0]['priceUsdPerInstanceHour'] == 2
    assert report['samples'][0]['availableAtUtc'] == (NOW + timedelta(seconds=30)).isoformat()


def test_gap_report_keeps_exact_series_and_never_fills_outages(tmp_path):
    archive = AwsQuoteArchive(Database(tmp_path / 'history.sqlite3'))
    for hours in (0, 1, 3):
        at = NOW + timedelta(hours=hours)
        archive.record(batch(at), at)
    archive.record(batch(NOW, price=8, zone='eu-north-1b'), NOW)
    report = hourly_history(archive, NOW + timedelta(hours=4))
    a, b = report['series']
    assert a['observedHourCount'] == 3 and a['longestConsecutiveHours'] == 2
    assert a['missingHoursWithinSpan'] == ['2026-10-25T12:00:00+00:00']
    assert b['observedHourCount'] == 1
    assert len(report['samples']) == 4


def test_failure_batches_remain_visible_without_fabricated_quotes(tmp_path):
    archive = AwsQuoteArchive(Database(tmp_path / 'history.sqlite3'))
    archive.record(AwsSpotPrices(status='UNAVAILABLE', fetched_at_utc=NOW), NOW)
    report = hourly_history(archive, NOW)
    assert report['batchCount'] == 1 and report['samples'] == []
    assert report['series'] == []
    invalid = batch()
    invalid.quotes[0].effective_at_utc = NOW + timedelta(hours=1)
    with pytest.raises(ValueError, match='timestamps'):
        archive.record(invalid, NOW)
    with pytest.raises(ValueError, match='timezone-aware'):
        archive.batches(datetime(2026, 10, 25))


def test_legacy_database_inspection_does_not_migrate_or_invent_history(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE market_observations (payload TEXT)')
    report = hourly_history(AwsQuoteArchive(Database(path)), NOW)
    assert report['batchCount'] == 0
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='aws_quote_batches'").fetchall() == []
