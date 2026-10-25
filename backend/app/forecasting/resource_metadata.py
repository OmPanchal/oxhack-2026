"""Read-only AWS hardware metadata and explicit instance-to-resource pricing."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from app.forecasting.collect_spot import DEFAULT_REGIONS, stamp

TYPE_SOURCE = "https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html"
OFFERING_SOURCE = "https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html"


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value.strip()


def _pages(operation: Callable, key: str, **params) -> Iterable[dict]:
    token = None
    seen = set()
    while True:
        response = operation(**params, **({"NextToken": token} if token else {}))
        if not isinstance(response.get(key), list):
            raise ValueError(f"Missing or invalid AWS response list: {key}")
        yield response
        token = response.get("NextToken")
        if not token:
            break
        if token in seen:
            raise ValueError("Repeated pagination token; metadata collection incomplete")
        seen.add(token)


def _hardware(raw: dict) -> dict:
    """Reject ambiguous accelerator mappings instead of calling them CPU pools."""
    instance = _text(raw["InstanceType"], "InstanceType")
    vcpus = _positive_integer(raw["VCpuInfo"]["DefaultVCpus"], "DefaultVCpus")
    memory = _positive_integer(raw["MemoryInfo"]["SizeInMiB"], "SizeInMiB")
    processor = raw.get("ProcessorInfo", {})
    architectures = processor.get("SupportedArchitectures")
    if architectures is not None:
        if not isinstance(architectures, list) or not architectures or any(
            not isinstance(value, str) or not value.strip() for value in architectures
        ) or len(set(architectures)) != len(architectures):
            raise ValueError("Invalid supported CPU architectures")
        architectures = sorted(architectures)
    manufacturer = processor.get("Manufacturer")
    if manufacturer is not None:
        manufacturer = _text(manufacturer, "Processor Manufacturer")
    for field in ("FpgaInfo", "InferenceAcceleratorInfo", "NeuronInfo"):
        if raw.get(field):
            raise ValueError(f"Unsupported accelerator mapping for {instance}: {field}")
    gpu_type, gpu_count, gpu_memory = None, 0, None
    if "GpuInfo" in raw:
        devices = raw["GpuInfo"].get("Gpus", [])
        if not devices:
            raise ValueError("GpuInfo is present without GPU devices")
        models = set()
        for device in devices:
            count = _positive_integer(device["Count"], "GPU Count")
            if device.get("GpuPartitionSize", 1) != 1 or device.get("LogicalGpuCount", count) != count:
                raise ValueError("Partitioned GPU mapping is not supported")
            manufacturer = _text(device["Manufacturer"], "GPU Manufacturer")
            name = _text(device["Name"], "GPU Name")
            memory_per_gpu = _positive_integer(device["MemoryInfo"]["SizeInMiB"], "GPU memory")
            models.add((manufacturer, name, memory_per_gpu))
            gpu_count += count
        if len(models) != 1:
            raise ValueError("Mixed GPU models or memory sizes cannot share a resource mapping")
        manufacturer, name, gpu_memory = models.pop()
        gpu_type = f"{manufacturer} {name}"
    units = gpu_count or vcpus
    return dict(instanceType=instance, vcpuCount=vcpus, memoryMiB=memory,
                supportedArchitectures=architectures, processorManufacturer=manufacturer,
                gpuCount=gpu_count, gpuType=gpu_type, gpuMemoryMiBPerDevice=gpu_memory,
                resourceType="GPU" if gpu_count else "CPU", resourceUnitsPerInstance=units,
                allocationGranularityUnits=units, unit="GPU-hour" if gpu_count else "vCPU-hour")


def collect_metadata(
    client_factory: Callable,
    *,
    regions: tuple[str, ...] = DEFAULT_REGIONS,
    instance_types: tuple[str, ...] = ("g4dn.xlarge", "m5.xlarge"),
    retrieved_at: datetime | None = None,
) -> tuple[list[dict], dict]:
    """One metadata record per offered (region, instance type), with provenance.

    Offerings describe current regional support, not free capacity, AZ support,
    historical support, or a promise of Spot fulfillment.
    """
    for values, name in ((regions, "regions"), (instance_types, "instance types")):
        if not values or len(set(values)) != len(values):
            raise ValueError(f"Nonempty unique {name} required")
        for value in values:
            _text(value, name)
    if len(instance_types) > 100:
        raise ValueError("Collect at most 100 instance types per invocation")
    retrieved = stamp(retrieved_at or datetime.now(timezone.utc))
    rows, requests, missing = [], [], []
    for region in sorted(regions):
        client = client_factory(region)
        offered = set()
        offering_pages = type_pages = 0
        for page in _pages(client.describe_instance_type_offerings, "InstanceTypeOfferings",
                           LocationType="region", MaxResults=1000,
                           Filters=[{"Name": "instance-type", "Values": list(instance_types)},
                                    {"Name": "location", "Values": [region]}]):
            offering_pages += 1
            for entry in page["InstanceTypeOfferings"]:
                if (entry["InstanceType"] not in instance_types or entry["Location"] != region
                        or entry["LocationType"] != "region"):
                    raise ValueError("Unexpected instance offering in provider response")
                offered.add(entry["InstanceType"])
        by_type = {}
        if offered:
            for page in _pages(client.describe_instance_types, "InstanceTypes",
                               InstanceTypes=sorted(offered)):
                type_pages += 1
                for raw in page["InstanceTypes"]:
                    hardware = _hardware(raw)
                    instance = hardware["instanceType"]
                    if instance not in offered or instance in by_type:
                        raise ValueError("Unexpected or duplicate instance metadata")
                    by_type[instance] = hardware
            if set(by_type) != offered:
                raise ValueError("Offered instance type has no hardware metadata")
        for instance in sorted(set(instance_types) - offered):
            missing.append(dict(region=region, instanceType=instance))
        for instance, hardware in sorted(by_type.items()):
            rows.append(dict(hardware, region=region, retrievedAt=retrieved,
                             dataKind="OBSERVED", source=TYPE_SOURCE,
                             offeringSource=OFFERING_SOURCE))
        requests.append(dict(region=region, offeringPages=offering_pages,
                             hardwarePages=type_pages, paginationComplete=True))
    for row in rows:
        row["supportedRegions"] = sorted(r["region"] for r in rows
                                         if r["instanceType"] == row["instanceType"])
    report = dict(schemaVersion="resource-metadata-v1", retrievedAt=retrieved,
                  requestedRegions=list(regions), requestedInstanceTypes=list(instance_types),
                  rowCount=len(rows), requests=requests, notOffered=missing,
                  dataKind="OBSERVED", sources=[TYPE_SOURCE, OFFERING_SOURCE],
                  limitations=["supportedRegions covers only the queried regions at retrieval time.",
                                "Regional offerings are not available capacity or historical AZ support.",
                                "Resource prices allocate the full instance bill to its primary resource.",
                                "Allocate/bill whole instances; unit prices do not imply fractional rentals.",
                                "Do not mix instance types solely because GPU names match."])
    return rows, report


def normalize_prices(prices: Iterable[dict], metadata: Iterable[dict]) -> list[dict]:
    """Join each price event exactly once; preserve instance and AZ identity.

    This returns price records, not MarketSnapshots: availableUnits is unknown.
    The original instance price remains authoritative for whole-instance billing.
    """
    index = {}
    for row in metadata:
        key = (row["region"], row["instanceType"])
        if key in index:
            raise ValueError(f"Duplicate metadata key: {key}")
        units = _positive_integer(row["resourceUnitsPerInstance"], "resourceUnitsPerInstance")
        if row["resourceType"] == "GPU":
            expected = _positive_integer(row["gpuCount"], "gpuCount")
            _text(row["gpuType"], "gpuType")
            unit = "GPU-hour"
        elif row["resourceType"] == "CPU" and row["gpuCount"] == 0 and row["gpuType"] is None:
            expected = _positive_integer(row["vcpuCount"], "vcpuCount")
            unit = "vCPU-hour"
        else:
            raise ValueError("Invalid resource mapping")
        if units != expected or row["allocationGranularityUnits"] != units or row["unit"] != unit:
            raise ValueError("Inconsistent billing unit mapping")
        index[key] = row
    result = []
    for price in prices:
        key = (price["region"], price["instanceType"])
        if key not in index:
            raise ValueError(f"Unmapped price series: {key}")
        meta = index[key]
        if price["dataKind"] != meta["dataKind"]:
            raise ValueError("Price and metadata provenance kinds differ")
        try:
            amount = Decimal(str(price["priceUsdPerInstanceHour"]))
        except InvalidOperation as exc:
            raise ValueError("Invalid instance price") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid instance price")
        with localcontext() as context:
            context.prec = 28
            per_unit = amount / Decimal(meta["resourceUnitsPerInstance"])
        result.append(dict(price, resourceType=meta["resourceType"], gpuType=meta["gpuType"],
                           resourceUnitsPerInstance=meta["resourceUnitsPerInstance"],
                           allocationGranularityUnits=meta["allocationGranularityUnits"],
                           priceUsdPerUnitHour=str(per_unit), unit=meta["unit"],
                           metadataRetrievedAt=meta["retrievedAt"], metadataSource=meta["source"]))
    return result


def save_metadata(output: Path, rows: list[dict], report: dict,
                  normalized: list[dict] | None = None) -> None:
    files = {"metadata.json": (json.dumps(rows, indent=2, sort_keys=True) + "\n").encode()}
    if normalized is not None:
        files["normalized-prices.jsonl"] = "".join(json.dumps(r, sort_keys=True) + "\n"
                                                   for r in normalized).encode()
    manifest = dict(report, sha256={name: hashlib.sha256(body).hexdigest()
                                   for name, body in files.items()})
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        (output / name).write_bytes(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="+", default=list(DEFAULT_REGIONS))
    parser.add_argument("--instance-types", nargs="+", default=["g4dn.xlarge", "m5.xlarge"])
    parser.add_argument("--profile")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--price-collection", type=Path,
                        help="Optional Step 1 directory; verify checksum and normalize every price")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output exists; select a new collection directory")
        prices = None
        input_hash = None
        input_window = None
        if args.price_collection:
            payload = (args.price_collection / "prices.jsonl").read_bytes()
            manifest = json.loads((args.price_collection / "manifest.json").read_text())
            input_hash = hashlib.sha256(payload).hexdigest()
            if input_hash != manifest["sha256"]:
                raise ValueError("Price collection checksum mismatch")
            prices = [json.loads(line) for line in payload.splitlines() if line.strip()]
            input_window = {"startTime": manifest["startTime"], "endTime": manifest["endTime"],
                            "paginationComplete": bool(manifest["requests"]) and all(
                                request["paginationComplete"] for request in manifest["requests"])}
        import boto3
        from botocore.config import Config
        session = boto3.Session(profile_name=args.profile)
        rows, report = collect_metadata(lambda region: session.client(
            "ec2", region_name=region, config=Config(retries={"mode": "standard", "max_attempts": 5})),
            regions=tuple(args.regions), instance_types=tuple(args.instance_types))
        normalized = normalize_prices(prices, rows) if prices is not None else None
        report["inputPricesSha256"] = input_hash
        report["inputPriceWindow"] = input_window
        save_metadata(args.output, rows, report, normalized)
    except ImportError:
        parser.exit(1, "Metadata collection requires boto3; no data retrieved.\n")
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Metadata collection rejected: {exc}\n")
    print(f"Saved {len(rows)} metadata records to {args.output}")
    if report["notOffered"]:
        print("Some requested region/instance combinations are not offered; see manifest.")


if __name__ == "__main__":
    main()
