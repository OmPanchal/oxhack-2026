"""Causal hourly price reconstruction, separate from capacity and API adapters."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path

from app.forecasting.collect_spot import stamp, utc
from app.forecasting.contracts import timestamp_for_slot
from app.forecasting.resource_metadata import normalize_prices

SERIES_FIELDS = ("region", "availabilityZone", "instanceType", "productDescription")
MAPPING_FIELDS = ("resourceType", "gpuType", "resourceUnitsPerInstance", "allocationGranularityUnits", "unit", "dataKind", "source")


def _series(row: dict) -> tuple:
    key = tuple(row[field] for field in SERIES_FIELDS)
    if any(not isinstance(value, str) or not value.strip() for value in key):
        raise ValueError("Price series requires region, zone, instance and product identity")
    return key


def _price(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid price") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Prices must be finite and nonnegative")
    return result


def reconstruct_hourly(events: list[dict], *, start: str | datetime, end: str | datetime,
                       gaps: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Keep AZ/instance series separate. Hourly point prices use no future data.

    Full-hour averages are retrospective accounting diagnostics, not inputs
    available at the hour's start. Event-free periods carry forward only under
    the source's complete price-change-history assumption.
    """
    start, end = timestamp_for_slot(start, 0), timestamp_for_slot(end, 0)
    if end <= start:
        raise ValueError("End must follow start")
    grouped, mapping = defaultdict(dict), {}
    duplicates = 0
    for row in events:
        key = _series(row)
        metadata = tuple(row[field] for field in MAPPING_FIELDS)
        resource, gpu, units, granularity, unit, kind, source = metadata
        if (resource not in ("CPU", "GPU") or kind not in ("OBSERVED", "SIMULATED")
                or type(units) is not int or units <= 0 or type(granularity) is not int
                or granularity != units or not isinstance(source, str) or not source.strip()):
            raise ValueError("Invalid resource mapping or price provenance")
        if (resource == "GPU" and not (isinstance(gpu, str) and gpu.strip())) or (resource == "CPU" and gpu is not None):
            raise ValueError("Inconsistent GPU/CPU identity")
        if unit != ("GPU-hour" if resource == "GPU" else "vCPU-hour"):
            raise ValueError("Incorrect resource price unit")
        per_unit, per_instance = _price(row["priceUsdPerUnitHour"]), _price(row["priceUsdPerInstanceHour"])
        with localcontext() as context:
            context.prec = 28
            if per_instance / units != per_unit:
                raise ValueError("Unit price does not match its instance conversion")
        if key in mapping and mapping[key] != metadata:
            raise ValueError("Conflicting hardware/provenance within one price series")
        mapping[key] = metadata
        timestamp = utc(row["timestamp"])
        prices = (per_unit, per_instance)
        if timestamp in grouped[key]:
            if grouped[key][timestamp] != prices:
                raise ValueError("Conflicting duplicate price events")
            duplicates += 1
        grouped[key][timestamp] = prices

    gap_groups = defaultdict(list)
    for gap in gaps or []:
        key = _series(gap)
        lower, upper = utc(gap["startTime"]), utc(gap["endTime"])
        if key not in grouped or upper <= lower:
            raise ValueError("Gap must name an existing series and a positive interval")
        gap_groups[key].append((lower, upper))

    slots = (end - start) // timedelta(hours=1)
    hourly, series_report = [], []
    for key in sorted(grouped):
        times = sorted(grouped[key])
        values = [grouped[key][timestamp] for timestamp in times]
        resource, gpu, units, granularity, unit, kind, source = mapping[key]
        known_points = known_averages = 0
        for slot in range(slots):
            boundary = start + timedelta(hours=slot)
            following = boundary + timedelta(hours=1)
            index = bisect_right(times, boundary) - 1
            status = "KNOWN" if index >= 0 else "NO_PAST_PRICE"
            if any(lower <= boundary and (boundary < upper or index < 0 or times[index] < upper)
                   for lower, upper in gap_groups[key]):
                status = "INGESTION_GAP"
            point = values[index] if status == "KNOWN" else None
            average = None
            gap_in_hour = any(lower < following and upper > boundary for lower, upper in gap_groups[key])
            if point is not None and not gap_in_hour:
                cursor, current, total = boundary, point[0], Decimal(0)
                for change in range(index + 1, bisect_right(times, following)):
                    timestamp = times[change]
                    if timestamp >= following:
                        break
                    total += current * Decimal(str((timestamp - cursor).total_seconds()))
                    cursor, current = timestamp, values[change][0]
                total += current * Decimal(str((following - cursor).total_seconds()))
                average = total / Decimal(3600)
            known_points += point is not None
            known_averages += average is not None
            hourly.append(dict(zip(SERIES_FIELDS, key), slot=slot, slotStartUtc=stamp(boundary),
                               resourceType=resource, gpuType=gpu, resourceUnitsPerInstance=units,
                               allocationGranularityUnits=granularity, unit=unit, dataKind=kind,
                               source=source, priceStatus=status,
                               effectivePriceTimestamp=stamp(times[index]) if point is not None else None,
                               priceUsdPerUnitHour=str(point[0]) if point is not None else None,
                               priceUsdPerInstanceHour=str(point[1]) if point is not None else None,
                               timeWeightedAveragePriceUsdPerUnitHour=str(average) if average is not None else None))
        series_report.append(dict(zip(SERIES_FIELDS, key), resourceType=resource, gpuType=gpu,
                                  resourceUnitsPerInstance=units, allocationGranularityUnits=granularity,
                                  unit=unit, dataKind=kind, eventCount=len(times),
                                  firstEvent=stamp(times[0]), lastEvent=stamp(times[-1]),
                                  declaredGapCount=len(gap_groups[key]), knownSlotCount=known_points,
                                  missingStartPriceSlots=slots-known_points,
                                  missingAveragePriceSlots=slots-known_averages,
                                  meets60DayCoverageTarget=known_points >= 60 * 24))
    return hourly, dict(schemaVersion="hourly-price-data-v1", originUtc=stamp(start), endUtc=stamp(end),
                        slotDurationSeconds=3600, rowCount=len(hourly), seriesCount=len(grouped),
                        series=series_report, inputEventCount=len(events), identicalDuplicatesRemoved=duplicates,
                        hasCapacityObservations=False,
                        priceKinds=sorted({metadata[5] for metadata in mapping.values()}),
                        forecastTarget="Price effective at target slot start",
                        replayChargingDefault="Slot-start instance price held for the hour; whole-instance allocation",
                        limitations=["Complete source price-change history is assumed except declared gaps.",
                                     "Event timestamps are assumed to be historical price availability times.",
                                     "Hourly averages are retrospective; never use them at the slot start.",
                                     "No AZ aggregation, capacity counts, forecasts or model metrics are inferred."])


def slot_cost(row: dict, allocated_units: int) -> Decimal:
    """MVP slot-start charging convention using exact original instance prices."""
    granularity = row["allocationGranularityUnits"]
    if type(allocated_units) is not int or allocated_units <= 0 or allocated_units % granularity:
        raise ValueError("Allocated units must represent positive whole instances")
    if row["priceStatus"] != "KNOWN":
        raise ValueError("Cannot charge an unknown price")
    return _price(row["priceUsdPerInstanceHour"]) * (allocated_units // granularity)


def prepare_collection(output: Path, *, start: str, end: str,
                       collection: Path | None = None, fixture: Path | None = None,
                       gap_file: Path | None = None) -> dict:
    """Prepare a checksummed Step 2 collection or an explicitly simulated example."""
    if (collection is None) == (fixture is None):
        raise ValueError("Choose exactly one collection or simulated fixture")
    if output.exists():
        raise ValueError("Output exists; choose a new preparation directory")
    hashes = {}
    if collection is not None:
        raw_manifest = (collection / "manifest.json").read_bytes()
        manifest = json.loads(raw_manifest)
        payloads = {}
        for name in ("metadata.json", "normalized-prices.jsonl"):
            payloads[name] = (collection / name).read_bytes()
            actual = hashlib.sha256(payloads[name]).hexdigest()
            if manifest["sha256"][name] != actual:
                raise ValueError(f"Input checksum mismatch: {name}")
            hashes[name] = actual
        hashes["manifest.json"] = hashlib.sha256(raw_manifest).hexdigest()
        window = manifest["inputPriceWindow"]
        if not window["paginationComplete"] or not utc(window["startTime"]) <= utc(start) < utc(end) <= utc(window["endTime"]):
            raise ValueError("Requested hours exceed the complete price collection window")
        events = [json.loads(line) for line in payloads["normalized-prices.jsonl"].splitlines() if line.strip()]
        verified = normalize_prices(events, json.loads(payloads["metadata.json"]))
        for original, checked in zip(events, verified):
            if any(original[field] != checked[field] for field in MAPPING_FIELDS[:-2]) or (
                _price(original["priceUsdPerUnitHour"]) != _price(checked["priceUsdPerUnitHour"])
            ):
                raise ValueError("Normalized price mapping disagrees with hardware metadata")
        events = verified
        gaps = []
    else:
        raw = fixture.read_bytes()
        document = json.loads(raw)
        if document["dataKind"] != "SIMULATED" or any(row["dataKind"] != "SIMULATED" for row in document["events"]):
            raise ValueError("Fixture input must be explicitly SIMULATED")
        if not utc(document["startTime"]) <= utc(start) < utc(end) <= utc(document["endTime"]):
            raise ValueError("Requested hours exceed the fixture window")
        hashes["fixture"] = hashlib.sha256(raw).hexdigest()
        events, gaps = document["events"], document.get("gaps", [])
        window = {"startTime": document["startTime"], "endTime": document["endTime"], "paginationComplete": True}
    if gap_file is not None:
        raw_gaps = gap_file.read_bytes()
        gaps = gaps + json.loads(raw_gaps)
        hashes["gaps"] = hashlib.sha256(raw_gaps).hexdigest()
    if not events:
        raise ValueError("No price events available; do not create an empty training dataset")
    rows, report = reconstruct_hourly(events, start=start, end=end, gaps=gaps)
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
    report.update(inputSha256=hashes, inputPriceWindow=window, dataFile="hourly-prices.jsonl",
                  sha256=hashlib.sha256(payload).hexdigest())
    output.mkdir(parents=True, exist_ok=False)
    (output / "hourly-prices.jsonl").write_bytes(payload)
    (output / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--collection", type=Path, help="Checksummed Step 2 metadata/normalized-price directory")
    inputs.add_argument("--fixture", type=Path, help="Explicitly simulated example document")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--gaps", type=Path, help="Optional declared collection-gap JSON array")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = prepare_collection(args.output, start=args.start, end=args.end,
                                    collection=args.collection, fixture=args.fixture, gap_file=args.gaps)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Hourly preparation rejected: {exc}\n")
    print(f"Prepared {report['rowCount']} hourly price records from {report['seriesCount']} series. "
          f"Price kinds: {', '.join(report['priceKinds'])}; capacity remains unknown.")


if __name__ == "__main__":
    main()
