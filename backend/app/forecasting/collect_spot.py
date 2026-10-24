"""Read-only EC2 price-event collection; no capacity inference or unit conversion."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Callable

SOURCE = "https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html"
DEFAULT_REGIONS = ("us-east-1", "us-west-2", "eu-central-1")


def utc(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


def collect(
    client_factory: Callable,
    *,
    start: datetime,
    end: datetime,
    regions: tuple[str, ...] = DEFAULT_REGIONS,
    instance_types: tuple[str, ...] = ("g4dn.xlarge",),
    product: str = "Linux/UNIX",
    retrieved_at: datetime | None = None,
) -> tuple[list[dict], dict]:
    """Collect all pages, preserving the pre-start effective-price anchor.

    Clients must implement describe_spot_price_history. Returned reports describe
    event coverage, not proven market availability or hourly sampling density.
    """
    start, end = utc(start), utc(end)
    retrieved_at = utc(retrieved_at or datetime.now(timezone.utc))
    if not retrieved_at - timedelta(days=90) <= start < end <= retrieved_at:
        raise ValueError("Require a positive window within the preceding 90 days")
    if not regions or not instance_types or not product:
        raise ValueError("Regions, instance types and product must be nonempty")
    if len(set(regions)) != len(regions) or len(set(instance_types)) != len(instance_types):
        raise ValueError("Duplicate regions or instance types")

    unique: dict[tuple, dict] = {}
    duplicate_count = 0
    requests = []
    for region in regions:
        client = client_factory(region)
        token = None
        seen_tokens: set[str] = set()
        pages = 0
        while True:
            params = dict(StartTime=start, EndTime=end, InstanceTypes=list(instance_types),
                          ProductDescriptions=[product], MaxResults=1000)
            if token:
                params["NextToken"] = token
            response = client.describe_spot_price_history(**params)
            pages += 1
            for raw in response["SpotPriceHistory"]:
                timestamp = utc(raw["Timestamp"])
                try:
                    price = Decimal(str(raw["SpotPrice"]))
                except InvalidOperation as exc:
                    raise ValueError("Invalid Spot price") from exc
                if not price.is_finite() or price < 0:
                    raise ValueError("Spot price must be finite and nonnegative")
                if timestamp > end:
                    raise ValueError("AWS returned an event after the requested window")
                if raw["InstanceType"] not in instance_types or raw["ProductDescription"] != product:
                    raise ValueError("AWS returned an unexpected resource/product")
                zone = raw["AvailabilityZone"]
                if not isinstance(zone, str) or not zone:
                    raise ValueError("Missing Availability Zone")
                key = (region, zone, raw["InstanceType"], product, stamp(timestamp))
                row = dict(region=region, availabilityZone=zone,
                           instanceType=raw["InstanceType"], productDescription=product,
                           timestamp=stamp(timestamp), priceUsdPerInstanceHour=str(price),
                           retrievedAt=stamp(retrieved_at), dataKind="OBSERVED", source=SOURCE)
                if key in unique:
                    if Decimal(unique[key]["priceUsdPerInstanceHour"]) != price:
                        raise ValueError("Conflicting duplicate price event")
                    duplicate_count += 1
                else:
                    unique[key] = row
            token = response.get("NextToken")
            if not token:
                break
            if token in seen_tokens:
                raise ValueError("Repeated pagination token; collection is incomplete")
            seen_tokens.add(token)
        requests.append(dict(region=region, pages=pages, paginationComplete=True))

    rows = [unique[key] for key in sorted(unique)]
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["region"], row["availabilityZone"], row["instanceType"])].append(row)
    series = []
    for (region, zone, instance), events in sorted(grouped.items()):
        times = [utc(row["timestamp"]) for row in events]
        anchor = any(t <= start for t in times)
        covered_start = start if anchor else times[0]
        change_count = sum(Decimal(a["priceUsdPerInstanceHour"]) != Decimal(b["priceUsdPerInstanceHour"])
                           for a, b in zip(events, events[1:]))
        boundaries = [covered_start] + [t for t in times if start < t < end] + [end]
        series.append(dict(region=region, availabilityZone=zone, instanceType=instance,
                           eventCount=len(events), firstEvent=stamp(times[0]),
                           lastEvent=stamp(times[-1]), hasStartAnchor=anchor,
                           uncoveredLeadingHours=(covered_start-start).total_seconds()/3600,
                           effectiveCoverageDays=(end-covered_start).total_seconds()/86400,
                           priceChangeCount=change_count,
                           longestEventFreeHours=max((b-a).total_seconds()/3600
                                                     for a, b in zip(boundaries, boundaries[1:]))))
    missing = [dict(region=r, instanceType=i) for r in regions for i in instance_types
               if not any(s["region"] == r and s["instanceType"] == i for s in series)]
    report = dict(source=SOURCE, retrievedAt=stamp(retrieved_at), startTime=stamp(start),
                  endTime=stamp(end), currency="USD", unit="instance-hour",
                  dataKind="OBSERVED", productDescription=product,
                  requestedRegions=list(regions), requestedInstanceTypes=list(instance_types),
                  rowCount=len(rows), identicalDuplicatesRemoved=duplicate_count,
                  requests=requests, series=series, missingRegionInstances=missing,
                  limitations=["Prices do not establish capacity or interruption probabilities.",
                                "An event-free interval is not proof of missing data.",
                                "Effective coverage assumes complete provider price-change history.",
                                "Hardware compatibility and resource-unit mapping are not verified.",
                                "Usage terms require review before redistribution."],
                  transformations=["UTC normalization", "Exact duplicate removal", "Stable sorting"],
                  splitCutoffs=None)
    return rows, report


def save(output: Path, rows: list[dict], report: dict) -> None:
    """Create a new dataset directory; never replace an existing collection."""
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
    manifest = dict(report, sha256=hashlib.sha256(payload).hexdigest(), dataFile="prices.jsonl")
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    (output / "prices.jsonl").write_bytes(payload)
    (output / "manifest.json").write_bytes(manifest_bytes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", required=True, help="Fixed timezone-aware end timestamp")
    parser.add_argument("--days", type=int, default=89,
                        help="Default 89 leaves margin inside AWS's rolling 90-day limit")
    parser.add_argument("--regions", nargs="+", default=list(DEFAULT_REGIONS))
    parser.add_argument("--instance-types", nargs="+", default=["g4dn.xlarge"])
    parser.add_argument("--profile")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        end = utc(args.end)
        now = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        if not 1 <= args.days <= 90 or not now-timedelta(days=90) <= start < end <= now:
            raise ValueError("Window must be positive and within the preceding 90 days")
        if args.output.exists():
            raise ValueError("Output already exists; choose a new collection directory")
        import boto3
        from botocore.config import Config
        session = boto3.Session(profile_name=args.profile)
        def factory(region):
            return session.client("ec2", region_name=region,
                                  config=Config(retries={"mode": "standard", "max_attempts": 5}))
        rows, report = collect(factory, start=start, end=end, regions=tuple(args.regions),
                               instance_types=tuple(args.instance_types), retrieved_at=now)
        save(args.output, rows, report)
    except ImportError:
        parser.exit(1, "Collection requires boto3 in your environment; no data retrieved.\n")
    except ValueError as exc:
        parser.exit(1, f"Collection rejected: {exc}\n")
    print(f"Saved {len(rows)} observed price events to {args.output}")
    if report["missingRegionInstances"]:
        print("WARNING: some requested region/instance combinations returned no records; see manifest.")


if __name__ == "__main__":
    main()
