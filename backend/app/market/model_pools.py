"""Read selected CPU/GPU pools without guessing AZ identity or cloud capacity."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.api.schemas import MarketSnapshot
from app.engine.forecast_bridge import EngineUnavailable
from app.engine.ml_integration import fixed_pool_source, gpu_name


class FixedPoolReader:
    def __init__(self, market):
        self.market = market
        self.zones = {}
        self.cpu_cache = {}
        self.errors = []
        self.failures = {}

    def zone_name(self, identity):
        if '-az' not in identity.availability_zone:
            return identity.availability_zone
        key = identity.region, identity.availability_zone
        now = self.market._now()
        cached = self.zones.get(key)
        if cached and (now - cached[0]).total_seconds() < self.market.catalog_ttl:
            return cached[1]
        rows = list(self.market._pages(self.market._client(identity.region),
            'describe_availability_zones', 'AvailabilityZones', ZoneIds=[identity.availability_zone]))
        names = {r['ZoneName'] for r in rows if r.get('ZoneId') == identity.availability_zone
                 and r.get('RegionName', identity.region) == identity.region and r.get('State', 'available') == 'available'}
        if len(names) != 1:
            raise ValueError('Cannot verify global AZ ID against this project zone name')
        name = names.pop()
        self.zones[key] = now, name
        return name

    def cpu_quote(self, identity, zone):
        now = self.market._now()
        key = identity.region, identity.instance_type, zone, identity.product_description
        cached = self.cpu_cache.get(key)
        if cached and now.replace(minute=0, second=0, microsecond=0) == cached.observed_at_utc.replace(minute=0, second=0, microsecond=0) and (now - cached.observed_at_utc).total_seconds() < self.market.price_ttl:
            return cached
        client = self.market._client(identity.region)
        types = list(self.market._pages(client, 'describe_instance_types', 'InstanceTypes', InstanceTypes=[identity.instance_type]))
        metadata = next((r for r in types if r['InstanceType'] == identity.instance_type), None)
        if metadata is None or 'spot' not in metadata.get('SupportedUsageClasses', []) or metadata.get('GpuInfo', {}).get('Gpus'):
            raise ValueError('Selected CPU instance metadata is unavailable or incompatible')
        units = metadata.get('VCpuInfo', {}).get('DefaultVCpus')
        if type(units) is not int or units <= 0:
            raise ValueError('Selected CPU pool requires a verified vCPU count')
        events = {}
        for row in self.market._pages(client, 'describe_spot_price_history', 'SpotPriceHistory',
                InstanceTypes=[identity.instance_type], AvailabilityZone=zone,
                ProductDescriptions=[identity.product_description], StartTime=now - timedelta(hours=1), EndTime=now):
            if (row['InstanceType'], row['AvailabilityZone'], row['ProductDescription']) != (identity.instance_type, zone, identity.product_description):
                raise ValueError('CPU quote has a different source identity')
            at, price = row['Timestamp'], Decimal(str(row['SpotPrice']))
            if at.utcoffset() is None or not price.is_finite() or price < 0:
                raise ValueError('Invalid CPU quote price/time')
            if at > now:
                continue
            if at in events and events[at] != price:
                raise ValueError('Conflicting CPU quotes')
            events[at] = price
        if not events:
            raise ValueError('Selected CPU pool has no effective current Spot price')
        at = max(events)
        quote = SimpleNamespace(units_per_instance=units, gpu_type=None, availability_zone=zone,
            observed_at_utc=now, price_usd_per_unit_hour=float(events[at] / units))
        self.cpu_cache[key] = quote
        return quote

    def poll(self, response, slot, origin):
        self.errors = []
        selected = []
        indexed = {(q.region, q.instance_type, q.availability_zone, q.product_description, gpu_name(q.gpu_type)): q
                   for q in response.quotes}
        for identity in self.market.pool_selections:
            # Model coverage does not authorize reads in additional regions.
            if identity.region not in self.market.regions:
                continue
            resource = getattr(identity, 'resource_type', 'GPU')
            if resource == 'GPU' and not any(k[0] == identity.region and k[1] == identity.instance_type
                    and k[3] == identity.product_description and k[4] == gpu_name(identity.gpu_type) for k in indexed):
                continue
            failure_key = identity.region, identity.instance_type, identity.availability_zone
            prior = self.failures.get(failure_key)
            if prior and self.market._now() < prior[0]:
                self.errors.append(prior[1])
                continue
            try:
                zone = self.zone_name(identity)
                if resource == 'CPU':
                    quote = self.cpu_quote(identity, zone)
                    price, units, gpu = quote.price_usd_per_unit_hour, quote.units_per_instance, None
                else:
                    quote = indexed.get((identity.region, identity.instance_type, zone, identity.product_description, gpu_name(identity.gpu_type)))
                    if quote is None:
                        continue
                    price, units, gpu = quote.price_usd_per_gpu_hour, quote.gpus_per_instance, quote.gpu_type
                if int((quote.observed_at_utc - origin).total_seconds() // 3600) != slot:
                    raise ValueError('Fixed-pool quote belongs to a different scheduling hour')
                if self.market.model_history is not None:
                    self.market.model_history.ensure(identity, quote)
                selected.append(MarketSnapshot(slot=slot, region=identity.region, resource_type=resource,
                    gpu_type=gpu, price_usd_per_unit_hour=price, available_units=None,
                    source=fixed_pool_source(identity) + f'{units} {"vCPU" if resource == "CPU" else "GPU"}(s)/WHOLE_INSTANCE; '
                    f'provider AZ {zone}; observed {quote.observed_at_utc.isoformat()}; capacity UNKNOWN', data_kind='OBSERVED'))
                self.failures.pop(failure_key, None)
            except Exception as exc:
                error = dict(region=identity.region, instanceType=identity.instance_type,
                    resourceType=getattr(identity, 'resource_type', 'GPU'),
                    code=getattr(exc, 'response', {}).get('Error', {}).get('Code', type(exc).__name__))
                self.errors.append(error)
                self.failures[failure_key] = self.market._now() + timedelta(seconds=60), error
        if not selected:
            raise EngineUnavailable('AWS_MODEL_POOLS_UNAVAILABLE', 'No configured fixed CPU/GPU pool has a verified current quote; inspect model status for read errors')
        return selected
