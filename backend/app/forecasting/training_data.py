"""Checksummed hourly inputs and chronological, horizon-purged examples."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path

from app.forecasting.collect_spot import utc
from app.forecasting.contracts import timestamp_for_slot
from app.market.features import (
    InsufficientHistoryError, LOOKBACK_SLOTS, MAX_HORIZON, SeriesIdentity, build_features,
)


@dataclass
class PriceSeries:
    identity: SeriesIdentity
    prices: dict[int, float | None]


@dataclass
class PriceDataset:
    origin: datetime
    end_slot: int
    series: list[PriceSeries]
    sha256: str
    data_kind: str


@dataclass(frozen=True)
class Partition:
    name: str
    start: int
    end: int

    def to_dict(self) -> dict:
        return {"name": self.name, "startSlot": self.start, "endSlotExclusive": self.end}


@dataclass
class Example:
    identity: SeriesIdentity
    origin_slot: int
    target_slot: int
    horizon: int
    current_price: float
    target_price: float
    features: dict[str, float | str]


def load_prepared_dataset(directory: Path, *, allow_simulated: bool = False) -> PriceDataset:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schemaVersion") != "hourly-price-data-v1" or manifest.get("slotDurationSeconds") != 3600:
        raise ValueError("Unsupported hourly dataset schema")
    payload = (directory / "hourly-prices.jsonl").read_bytes()
    fingerprint = hashlib.sha256(payload).hexdigest()
    if fingerprint != manifest["sha256"]:
        raise ValueError("Hourly dataset checksum mismatch")
    origin = timestamp_for_slot(manifest["originUtc"], 0)
    delta = utc(manifest["endUtc"]) - origin
    if delta <= timedelta(0) or delta % timedelta(hours=1):
        raise ValueError("Invalid hourly dataset window")
    end_slot = delta // timedelta(hours=1)
    groups, kinds = {}, set()
    rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    if not rows or len(rows) != manifest["rowCount"]:
        raise ValueError("Empty dataset or incorrect row count")
    for row in rows:
        identity = SeriesIdentity.from_row(row)
        slot = row["slot"]
        if type(slot) is not int or not 0 <= slot < end_slot:
            raise ValueError("Hourly slot is outside dataset bounds")
        if utc(row["slotStartUtc"]) != timestamp_for_slot(origin, slot):
            raise ValueError("Slot does not match its UTC timestamp")
        kinds.add(row["dataKind"])
        if row["dataKind"] not in ("OBSERVED", "SIMULATED"):
            raise ValueError("Forecasts are not observations")
        prices = groups.setdefault(identity, {})
        if slot in prices:
            raise ValueError("Duplicate source-series slot")
        value = row["priceUsdPerUnitHour"]
        if row["priceStatus"] == "KNOWN":
            if value is None or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("Invalid known hourly price")
            prices[slot] = float(value)
        elif row["priceStatus"] in ("NO_PAST_PRICE", "INGESTION_GAP") and value is None:
            prices[slot] = None
        else:
            raise ValueError("Unknown or inconsistent price status")
    if len(kinds) != 1 or (kinds != {"OBSERVED"} and not allow_simulated):
        raise ValueError("Training requires observed prices; synthetic tests must opt in explicitly")
    for prices in groups.values():
        if set(prices) != set(range(end_slot)):
            raise ValueError("Each series must have explicit rows for known and missing hours")
    return PriceDataset(origin, end_slot, [PriceSeries(key, groups[key]) for key in sorted(groups)],
                        fingerprint, kinds.pop())


def chronological_partitions(end_slot: int) -> dict[str, Partition]:
    if type(end_slot) is not int or end_slot <= 0:
        raise ValueError("Positive integer dataset length required")
    boundaries = (0, end_slot * 60 // 100, end_slot * 75 // 100, end_slot * 85 // 100, end_slot)
    names = ("train", "validation", "calibration", "test")
    partitions = {name: Partition(name, lower, upper)
                  for name, lower, upper in zip(names, boundaries, boundaries[1:])}
    if partitions["train"].end <= LOOKBACK_SLOTS + MAX_HORIZON or any(
        part.end - part.start <= MAX_HORIZON for part in partitions.values()
    ):
        raise ValueError("Insufficient chronological coverage for all four partitions")
    return partitions


def build_examples(dataset: PriceDataset, partition: Partition, *, feature_builder=build_features,
                   feature_lookback: int = LOOKBACK_SLOTS,
                   eligibility_lookback: int | None = None) -> tuple[list[Example], dict]:
    """A whole six-horizon origin stays in one partition; crossing labels are purged."""
    if not 0 <= partition.start < partition.end <= dataset.end_slot:
        raise ValueError("Partition outside dataset")
    eligibility = feature_lookback if eligibility_lookback is None else eligibility_lookback
    if type(eligibility) is not int or eligibility < feature_lookback or feature_lookback < LOOKBACK_SLOTS:
        raise ValueError("Invalid feature/eligibility lookback")
    examples, skipped = [], 0
    for series in dataset.series:
        for origin_slot in range(max(partition.start, eligibility), partition.end - MAX_HORIZON):
            if any(series.prices.get(slot) is None for slot in range(origin_slot-eligibility, origin_slot+1)):
                skipped += 1
                continue
            try:
                first = feature_builder(series.prices, series.identity, dataset.origin, origin_slot, 1)
            except InsufficientHistoryError:
                skipped += 1
                continue
            targets = [series.prices.get(origin_slot + horizon) for horizon in range(1, MAX_HORIZON + 1)]
            if any(value is None for value in targets):
                skipped += 1
                continue
            for horizon, value in enumerate(targets, 1):
                features = first if horizon == 1 else feature_builder(
                    series.prices, series.identity, dataset.origin, origin_slot, horizon)
                examples.append(Example(series.identity, origin_slot, origin_slot + horizon, horizon,
                                        float(series.prices[origin_slot]), float(value), features))
    if not examples:
        raise ValueError(f"No eligible examples for {partition.name}")
    return examples, {"partition": partition.name, "sampleCount": len(examples),
                      "originCount": len(examples) // MAX_HORIZON,
                      "skippedOriginsWithMissingHistoryOrLabels": skipped,
                      "firstOriginSlot": min(e.origin_slot for e in examples),
                      "lastOriginSlot": max(e.origin_slot for e in examples),
                      "lastTargetSlot": max(e.target_slot for e in examples),
                      "boundaryRule": "origin >= partition start and origin + 6 < partition end"}
