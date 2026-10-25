"""Read-only EC2 catalog/Spot integration. No provisioning operations exist here."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import isfinite
from threading import RLock
from typing import Callable

from app.api.market_schemas import AwsSpotPrices, AwsSpotQuote, GpuOffering, MarketCapabilities, ProviderError
from app.api.schemas import MarketSnapshot
from app.engine.forecast_bridge import EngineUnavailable
from app.market.history import AwsQuoteArchive


class AwsSpotMarket:
    def __init__(self, regions: list[str], *, client_factory: Callable | None = None,
                 instance_types: list[str] | None = None, clock: Callable | None = None,
                 catalog_ttl_seconds: float = 3600, price_ttl_seconds: float = 60,
                 quote_archive: AwsQuoteArchive | None = None, pool_selections=None):
        self.regions = sorted(set(region.strip() for region in regions if region.strip()))
        if not self.regions:
            raise ValueError("Configure at least one AWS region")
        if any(not isfinite(value) or value <= 0 for value in [catalog_ttl_seconds, price_ttl_seconds]):
            raise ValueError("AWS cache durations must be finite and positive")
        self.instance_types = sorted(set(instance_types or []))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.factory = client_factory or self._boto_client
        self.clients = {}
        self.catalog_ttl = catalog_ttl_seconds
        self.price_ttl = price_ttl_seconds
        self.catalog_cache = None
        self.price_cache = None
        self.lock = RLock()
        self.quote_archive = quote_archive
        self.pool_selections = pool_selections
        self.model_history = None

    @staticmethod
    def _boto_client(region):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise EngineUnavailable("AWS_SDK_UNAVAILABLE", "Install backend with the aws extra: pip install -e '.[dev,aws]'") from exc
        return boto3.Session().client("ec2", region_name=region,
            config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"}))

    def _now(self):
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("AWS clock must be timezone-aware")
        return now.astimezone(timezone.utc)

    def _client(self, region):
        if region not in self.clients:
            self.clients[region] = self.factory(region)
        return self.clients[region]

    @staticmethod
    def _pages(client, operation, result_key, **params):
        token = None
        seen = set()
        while True:
            response = getattr(client, operation)(**params, **({"NextToken": token} if token else {}))
            yield from response.get(result_key, [])
            token = response.get("NextToken")
            if not token:
                return
            if token in seen:
                raise ValueError("AWS returned a repeated pagination token")
            seen.add(token)

    @staticmethod
    def _error(region, exc):
        response = getattr(exc, "response", {})
        code = response.get("Error", {}).get("Code", getattr(exc, "code", type(exc).__name__))
        # Never return credentials, SDK response bodies or signed requests.
        return ProviderError(region=region, code=code, message=f"AWS read failed ({code}); check credentials, permissions and regional access")

    @staticmethod
    def _status(errors, has_data):
        return "PARTIAL" if errors and has_data else "UNAVAILABLE" if errors else "READY"

    def capabilities(self) -> MarketCapabilities:
        with self.lock:
            now = self._now()
            ttl = min(self.catalog_ttl, 30) if self.catalog_cache and self.catalog_cache.errors else self.catalog_ttl
            if self.catalog_cache and 0 <= (now - self.catalog_cache.fetched_at_utc).total_seconds() < ttl:
                return self.catalog_cache.model_copy(deep=True)
            offerings, errors = [], []
            for region in self.regions:
                try:
                    client = self._client(region)
                    descriptions = list(self._pages(client, "describe_instance_types", "InstanceTypes",
                        Filters=[{"Name": "supported-usage-class", "Values": ["spot"]}]))
                    supported = {}
                    for info in descriptions:
                        name = info["InstanceType"]
                        if self.instance_types and name not in self.instance_types:
                            continue
                        devices = info.get("GpuInfo", {}).get("Gpus", [])
                        if (not devices or "spot" not in info.get("SupportedUsageClasses", [])
                                or any(not row.get("Name") or row.get("Count", 0) <= 0
                                       or row.get("GpuPartitionSize", 1) != 1 for row in devices)
                                or len({row["Name"].strip() for row in devices}) != 1):
                            continue
                        supported[name] = info
                    if not supported:
                        continue
                    locations = {}
                    names = sorted(supported)
                    for offset in range(0, len(names), 100):
                        rows = self._pages(client, "describe_instance_type_offerings", "InstanceTypeOfferings",
                            LocationType="availability-zone", Filters=[{"Name": "instance-type", "Values": names[offset:offset + 100]}])
                        for row in rows:
                            if row["InstanceType"] in supported:
                                locations.setdefault(row["InstanceType"], set()).add(row["Location"])
                    regional = []
                    for name, info in supported.items():
                        if not locations.get(name):
                            continue
                        devices = info["GpuInfo"]["Gpus"]
                        memory = {row.get("MemoryInfo", {}).get("SizeInMiB") for row in devices}
                        regional.append(GpuOffering(region=region, instance_type=name, gpu_type=devices[0]["Name"].strip(),
                            gpus_per_instance=sum(row["Count"] for row in devices),
                            gpu_memory_mib=next(iter(memory)) if len(memory) == 1 else None,
                            v_cpu_count=info.get("VCpuInfo", {}).get("DefaultVCpus"), memory_mib=info.get("MemoryInfo", {}).get("SizeInMiB"),
                            cpu_architectures=sorted(info.get("ProcessorInfo", {}).get("SupportedArchitectures", [])),
                            availability_zones=sorted(locations[name])))
                    offerings.extend(regional)
                except Exception as exc:
                    errors.append(self._error(region, exc))
            self.catalog_cache = MarketCapabilities(provider="AWS", status=self._status(errors, bool(offerings)),
                fetched_at_utc=now, configured_regions=self.regions, offerings=sorted(offerings, key=lambda row: (row.region, row.instance_type)),
                allowed_gpu_types=sorted({row.gpu_type for row in offerings}), allowed_regions=sorted({row.region for row in offerings}), errors=errors)
            return self.catalog_cache.model_copy(deep=True)

    def prices(self) -> AwsSpotPrices:
        with self.lock:
            now = self._now()
            ttl = min(self.price_ttl, 15) if self.price_cache and self.price_cache.errors else self.price_ttl
            if self.price_cache and 0 <= (now - self.price_cache.fetched_at_utc).total_seconds() < ttl:
                return self.price_cache.model_copy(deep=True)
            catalog = self.capabilities()
            errors = list(catalog.errors)
            quotes = []
            for region in self.regions:
                hardware = {row.instance_type: row for row in catalog.offerings if row.region == region}
                if not hardware:
                    continue
                try:
                    latest = {}
                    names = sorted(hardware)
                    for offset in range(0, len(names), 100):
                        rows = self._pages(self._client(region), "describe_spot_price_history", "SpotPriceHistory",
                            InstanceTypes=names[offset:offset + 100], ProductDescriptions=["Linux/UNIX"],
                            StartTime=now - timedelta(hours=1), EndTime=now)
                        for row in rows:
                            name = row["InstanceType"]
                            if name not in hardware or row.get("ProductDescription") != "Linux/UNIX":
                                continue
                            if row["AvailabilityZone"] not in hardware[name].availability_zones:
                                continue
                            timestamp = row["Timestamp"]
                            if timestamp.utcoffset() is None:
                                raise ValueError("AWS Spot timestamp is not timezone-aware")
                            timestamp = timestamp.astimezone(timezone.utc)
                            if timestamp > now:
                                continue
                            key = name, row["AvailabilityZone"]
                            price = Decimal(row["SpotPrice"])
                            if not price.is_finite() or price < 0:
                                raise ValueError("Invalid AWS Spot price")
                            if key in latest and latest[key][0] == timestamp and latest[key][1] != price:
                                raise ValueError("Conflicting AWS Spot prices at one timestamp")
                            if key not in latest or latest[key][0] < timestamp:
                                latest[key] = timestamp, price
                    regional = []
                    for (name, zone), (timestamp, price) in sorted(latest.items()):
                        offer = hardware[name]
                        regional.append(AwsSpotQuote(**offer.model_dump(), availability_zone=zone, product_description="Linux/UNIX",
                            price_usd_per_instance_hour=float(price), price_usd_per_gpu_hour=float(price / offer.gpus_per_instance),
                            effective_at_utc=timestamp, observed_at_utc=now))
                    quotes.extend(regional)
                except Exception as exc:
                    errors.append(self._error(region, exc))
            batch = AwsSpotPrices(status=self._status(errors, bool(quotes)), fetched_at_utc=now, quotes=quotes, errors=errors)
            if self.quote_archive is not None:
                self.quote_archive.record(batch, self._now())
            self.price_cache = batch
            return self.price_cache.model_copy(deep=True)

    def poll(self, current_slot: int) -> list[MarketSnapshot]:
        raise EngineUnavailable("AWS_SLOT_ORIGIN_REQUIRED", "Use the runtime's persisted UTC origin with AWS observations")

    def poll_with_origin(self, current_slot: int, origin_utc: datetime) -> list[MarketSnapshot]:
        self.validate_slot(current_slot, origin_utc)
        response = self.prices()
        if self.pool_selections is not None:
            if any(int((q.observed_at_utc - origin_utc).total_seconds() // 3600) != current_slot for q in response.quotes):
                self.price_cache = None
                response = self.prices()
            from app.market.model_pools import FixedPoolReader
            if not hasattr(self, 'fixed_pool_reader'):
                self.fixed_pool_reader = FixedPoolReader(self)
            return self.fixed_pool_reader.poll(response, current_slot, origin_utc)
        if response.status == "UNAVAILABLE":
            raise EngineUnavailable("AWS_MARKET_UNAVAILABLE", "AWS reads failed; inspect /api/capabilities and /api/market/aws/spot for regional error codes")
        cheapest = {}
        for quote in response.quotes:
            # Do not stamp last hour's cached observation into a new hour.
            if int((quote.observed_at_utc - origin_utc).total_seconds() // 3600) != current_slot:
                self.price_cache = None
                return self.poll_with_origin(current_slot, origin_utc)
            key = quote.region, quote.gpu_type
            tie = quote.price_usd_per_gpu_hour, quote.instance_type, quote.availability_zone
            if key not in cheapest or tie < cheapest[key][0]:
                cheapest[key] = tie, quote
        return [MarketSnapshot(slot=current_slot, region=region, resource_type="GPU", gpu_type=gpu,
            price_usd_per_unit_hour=quote.price_usd_per_gpu_hour, available_units=None, carbon_kg_per_unit_hour=None,
            source=(f"AWS EC2 OBSERVED PRICE INDEX; {quote.instance_type}; {quote.availability_zone}; "
                    f"{quote.gpus_per_instance} GPU(s)/WHOLE_INSTANCE; ${quote.price_usd_per_instance_hour}/instance-hour; "
                    f"observed {quote.observed_at_utc.isoformat()}; capacity UNKNOWN; not an executable allocation"),
            data_kind="OBSERVED") for (region, gpu), (_, quote) in sorted(cheapest.items())]

    def validate_slot(self, current_slot: int, origin_utc: datetime):
        if origin_utc.utcoffset() is None or current_slot != int((self._now() - origin_utc).total_seconds() // 3600):
            raise EngineUnavailable("AWS_LIVE_SLOT_MISMATCH", "Live AWS observations require the current UTC hour; use replay for historical or accelerated time")
