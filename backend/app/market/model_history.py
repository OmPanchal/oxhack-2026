"""Automatic fixed-pool historical inputs, known at retrieval, for live ML only."""
from datetime import datetime, timedelta
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from threading import RLock

from app.api.schemas import MarketSnapshot
from app.market.history import utc


class AwsModelHistory:
    LOOKBACK = 168

    @staticmethod
    def units(quote):
        return getattr(quote, 'units_per_instance', None) or quote.gpus_per_instance

    def __init__(self, database, client_factory, clock):
        self.database, self.client_factory, self.clock = database, client_factory, clock
        self.lock = RLock()
        self.status_lock = RLock()
        self.keys = {}
        self.states = {}
        self.completed = {}
        self.retry_after = {}

    @staticmethod
    def identity_key(identity):
        return (identity.region, identity.instance_type, identity.availability_zone,
                identity.product_description, identity.gpu_type)

    @staticmethod
    def hours(boundary):
        return [boundary - timedelta(hours=offset) for offset in range(168, 0, -1)]

    def _read(self, key, hours, cutoff):
        with self.database.transaction() as connection:
            return {datetime.fromisoformat(row['hour_utc']): json.loads(row['payload']) for row in connection.execute(
                'SELECT hour_utc, payload FROM model_price_history WHERE series_key = ? '
                'AND hour_utc >= ? AND hour_utc <= ? AND available_at_utc <= ?',
                (key, hours[0].isoformat(), hours[-1].isoformat(), cutoff.isoformat()))}

    def ensure(self, identity, quote):
        """Fetch missing boundaries only. Failure leaves current prices usable."""
        now = utc(self.clock())
        boundary = now.replace(minute=0, second=0, microsecond=0)
        identity_key = self.identity_key(identity)
        key = json.dumps([*identity_key, self.units(quote)])
        with self.lock:
            self.keys[identity_key] = key
            if self.completed.get(key) == boundary or self.retry_after.get(key, now) > now:
                return
            hours = self.hours(boundary)
            present = self._read(key, hours, now)
            missing = [hour for hour in hours if hour not in present]
            error = None
            with self.status_lock:
                self.states[key] = dict(region=identity.region, instanceType=identity.instance_type,
                    availabilityZone=identity.availability_zone, gpuType=quote.gpu_type,
                    resourceType=getattr(identity, 'resource_type', 'GPU'), status='PARTIAL' if missing else 'READY',
                    requiredHours=self.LOOKBACK, availableHours=len(present),
                    missingHours=[h.isoformat() for h in missing], checkedAtUtc=now.isoformat(), errorCode=None)
            if missing:
                try:
                    self._fetch(identity, quote, key, missing)
                except Exception as exc:
                    # Keep quote ingestion alive, expose the failure and retry.
                    # Never turn a failed/incomplete fetch into fabricated inputs.
                    error = str(getattr(exc, 'response', {}).get('Error', {}).get('Code', type(exc).__name__))
                present = self._read(key, hours, utc(self.clock()))
                missing = [hour for hour in hours if hour not in present]
            with self.status_lock:
                self.states[key].update(status='READY' if not missing else 'PARTIAL',
                    availableHours=len(present), missingHours=[h.isoformat() for h in missing],
                    checkedAtUtc=utc(self.clock()).isoformat(), errorCode=error)
            if missing:
                self.retry_after[key] = utc(self.clock()) + timedelta(seconds=60)
            else:
                self.completed[key] = boundary
                self.retry_after.pop(key, None)

    def _fetch(self, identity, quote, key, missing):
        start, end = min(missing), max(missing) + timedelta(hours=1)
        zone = getattr(quote, 'availability_zone', identity.availability_zone)
        units = self.units(quote)
        resource = getattr(identity, 'resource_type', 'GPU')
        request = dict(InstanceTypes=[identity.instance_type], AvailabilityZone=zone,
                       ProductDescriptions=[identity.product_description], StartTime=start, EndTime=end)
        paginator = self.client_factory(identity.region).get_paginator('describe_spot_price_history')
        events = {}
        pages = 0
        for page in paginator.paginate(**request, PaginationConfig={'PageSize': 1000}):
            pages += 1
            for raw in page.get('SpotPriceHistory', []):
                if (raw['InstanceType'], raw['AvailabilityZone'], raw['ProductDescription']) != (
                        identity.instance_type, zone, identity.product_description):
                    raise ValueError('Historical response has a different source identity')
                at = utc(raw['Timestamp'])
                price = Decimal(str(raw['SpotPrice']))
                if at > end or not price.is_finite() or price < 0:
                    raise ValueError('Invalid historical price/time')
                if at in events and events[at] != price:
                    raise ValueError('Conflicting historical price events')
                events[at] = price
        received = utc(self.clock())
        ordered = sorted(events.items())
        samples = []
        for hour in missing:
            preceding = [(at, price) for at, price in ordered if at <= hour]
            if not preceding:
                continue
            at, price = preceding[-1]
            samples.append(dict(hourUtc=hour.isoformat(), effectiveAtUtc=at.isoformat(),
                retrievedAtUtc=received.isoformat(), priceUsdPerInstanceHour=str(price),
                priceUsdPerGpuHour=float(price / units) if resource == 'GPU' else None,
                priceUsdPerUnitHour=float(price / units), resourceType=resource,
                unitsPerInstance=units, gpusPerInstance=units if resource == 'GPU' else None, dataKind='OBSERVED',
                source='AWS DescribeSpotPriceHistory; reconstructed effective hourly boundary; retrieved retrospectively'))
        receipt = dict(region=identity.region, instanceType=identity.instance_type,
            availabilityZone=identity.availability_zone, productDescription=identity.product_description,
            providerAvailabilityZone=zone, resourceType=resource,
            gpuType=identity.gpu_type, unitsPerInstance=units, gpusPerInstance=units if resource == 'GPU' else None,
            startUtc=start.isoformat(), endUtc=end.isoformat(), receivedAtUtc=received.isoformat(),
            paginationComplete=True, pageCount=pages,
            source='https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html',
            dataKind='OBSERVED', currency='USD', rawUnit='instance-hour',
            events=[dict(effectiveAtUtc=at.isoformat(), priceUsdPerInstanceHour=str(price)) for at, price in ordered])
        payload = json.dumps(receipt, sort_keys=True)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        # Commit samples only after every page succeeds; no network under SQLite lock.
        with self.database.transaction() as connection:
            connection.execute('INSERT OR IGNORE INTO model_history_fetches VALUES (?, ?)', (fingerprint, payload))
            for sample in samples:
                connection.execute('INSERT OR IGNORE INTO model_price_history VALUES (?, ?, ?, ?)',
                    (key, sample['hourUtc'], received.isoformat(), json.dumps(sample)))

    def native_history(self, identity, model_origin, decision_boundary):
        """Read available-at-now history only for the actual live scheduling hour."""
        from app.engine.ml_integration import fixed_pool_source
        now = utc(self.clock())
        if decision_boundary != now.replace(minute=0, second=0, microsecond=0):
            raise ValueError('Live model history cannot be used for historical/replay decisions')
        with self.lock:
            key = self.keys.get(self.identity_key(identity))
            if key is None:
                return []
            values = self._read(key, self.hours(decision_boundary), now)
        rows = []
        for hour, sample in sorted(values.items()):
            slot = int((hour - model_origin).total_seconds() // 3600)
            if slot < 0:
                continue
            rows.append(MarketSnapshot(slot=slot, region=identity.region, resource_type=getattr(identity, 'resource_type', 'GPU'),
                gpu_type=identity.gpu_type or None, price_usd_per_unit_hour=sample.get('priceUsdPerUnitHour', sample.get('priceUsdPerGpuHour')),
                available_units=None, carbon_kg_per_unit_hour=None, data_kind='OBSERVED',
                source=fixed_pool_source(identity) + f'historical boundary; retrieved {sample["retrievedAtUtc"]}; capacity UNKNOWN'))
        return rows

    def status(self):
        with self.status_lock:
            pools = deepcopy(list(self.states.values()))
            return dict(status='WARMING' if not pools else 'READY' if all(p['status'] == 'READY' for p in pools) else 'PARTIAL',
                        lookbackHours=self.LOOKBACK, pools=pools)
