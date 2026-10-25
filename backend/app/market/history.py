"""Durable quote vintages, separate from the scheduler's mutable regional index."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import sqlite3

from app.api.market_schemas import AwsSpotPrices
from app.database import Database


def utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError('History timestamps must be timezone-aware')
    return value.astimezone(timezone.utc)


class AwsQuoteArchive:
    def __init__(self, database: Database):
        self.database = database

    def record(self, batch: AwsSpotPrices, recorded_at_utc: datetime):
        if batch.fetched_at_utc is None:
            raise ValueError('Archived AWS batches require a retrieval timestamp')
        fetched = utc(batch.fetched_at_utc)
        recorded = utc(recorded_at_utc)
        if fetched > recorded:
            raise ValueError('Batch retrieval timestamp cannot follow archival time')
        for quote in batch.quotes:
            observed, effective = utc(quote.observed_at_utc), utc(quote.effective_at_utc)
            if effective > observed or observed > fetched:
                raise ValueError('Quote timestamps violate effective <= observed <= fetched')
        payload = batch.model_dump_json(by_alias=True)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with self.database.transaction() as connection:
            connection.execute(
                'INSERT OR IGNORE INTO aws_quote_batches (fingerprint, recorded_at_utc, payload) VALUES (?, ?, ?)',
                (fingerprint, recorded.isoformat(), payload),
            )

    def batches(self, as_of: datetime) -> list[tuple[datetime, AwsSpotPrices]]:
        cutoff = utc(as_of)
        # Read-only inspection must not create a database or migrate one.
        uri = self.database.path.as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='aws_quote_batches'"
            ).fetchone()
            if not exists:
                return []
            rows = connection.execute(
                'SELECT recorded_at_utc, payload FROM aws_quote_batches WHERE recorded_at_utc <= ? ORDER BY recorded_at_utc, fingerprint',
                (cutoff.isoformat(),),
            ).fetchall()
        return [(datetime.fromisoformat(row[0]), AwsSpotPrices.model_validate_json(row[1])) for row in rows]


def hourly_history(archive: AwsQuoteArchive, as_of: datetime) -> dict:
    """First actually observed quote in each UTC hour; never fill missing hours.

    hourUtc identifies a bucket, not a claim the quote was known at hour start.
    availableAtUtc remains the final eligibility timestamp for inference.
    """
    cutoff = utc(as_of)
    selected = {}
    batches = archive.batches(cutoff)
    for recorded_at, batch in batches:
        for quote in batch.quotes:
            observed = utc(quote.observed_at_utc)
            if observed > cutoff:
                continue
            hour = observed.replace(minute=0, second=0, microsecond=0)
            series = (quote.region, quote.instance_type, quote.availability_zone,
                      quote.product_description, quote.gpu_type, quote.gpus_per_instance)
            key = series, hour
            candidate = dict(quote.model_dump(mode='json', by_alias=True),
                             hourUtc=hour.isoformat(), fetchedAtUtc=utc(batch.fetched_at_utc).isoformat(),
                             availableAtUtc=recorded_at.isoformat(),
                             batchStatus=batch.status)
            if key not in selected or observed < datetime.fromisoformat(selected[key]['observedAtUtc']):
                selected[key] = candidate
    rows = [row for _, row in sorted(selected.items())]
    grouped = {}
    for (series, hour), _ in selected.items():
        grouped.setdefault(series, []).append(hour)
    coverage = []
    for series, hours in sorted(grouped.items()):
        hours = sorted(hours)
        present = set(hours)
        missing = []
        cursor = hours[0]
        longest = consecutive = 0
        while cursor <= hours[-1]:
            if cursor in present:
                consecutive += 1
                longest = max(longest, consecutive)
            else:
                missing.append(cursor.isoformat())
                consecutive = 0
            cursor += timedelta(hours=1)
        region, instance, zone, product, gpu, count = series
        coverage.append(dict(region=region, instanceType=instance, availabilityZone=zone,
                             productDescription=product, gpuType=gpu, gpusPerInstance=count,
                             observedHourCount=len(hours), firstHourUtc=hours[0].isoformat(),
                             lastHourUtc=hours[-1].isoformat(), missingHoursWithinSpan=missing,
                             longestConsecutiveHours=longest))
    return dict(schemaVersion='aws-quote-history-v1', provider='AWS',
                source='Amazon EC2 DescribeSpotPriceHistory (normalized sampled quotes)', asOfUtc=cutoff.isoformat(),
                target='EXACT_INSTANCE_AZ_SPOT_QUOTE', sampling='FIRST_OBSERVED_PER_UTC_HOUR',
                batchCount=len(batches), hourlySampleCount=len(rows), series=coverage, samples=rows,
                limitations=[
                    'Collection starts when archival is enabled; old regional indices cannot reconstruct exact quotes.',
                    'Hours without observations remain missing; effectiveAtUtc is not a retrieval timestamp.',
                    'hourUtc is a bucket label; enforce availableAtUtc as well as observation/retrieval cutoffs for inference.',
                    'Unknown capacity remains null; this export is not an allocation or benchmark.',
                    'Model training target, history requirements and chronological splits are not yet agreed.',
                ])
