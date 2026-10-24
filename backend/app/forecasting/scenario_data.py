"""Seeded, explicitly simulated replay input datasets; never scheduling outcomes."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random

from app.forecasting.collect_spot import DEFAULT_REGIONS, stamp, utc

VERSION = "synthetic-market-v1"
KINDS = ("normal", "price-spike", "capacity-shortage", "interruption", "deadline-pressure")
STRATEGIES = ("FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML")


def _job(job_id: str, arrival: int, duration: int, deadline: int,
         resource: str = "GPU", gpu_type: str | None = "NVIDIA T4", units: int = 1) -> dict:
    return dict(id=job_id, name=job_id.replace("-", " "), arrivalSlot=arrival,
                durationSlots=duration, deadlineSlot=deadline, resourceType=resource,
                resourceUnits=units, gpuType=gpu_type, allowedRegions=list(DEFAULT_REGIONS),
                maxBudgetUsd=50.0, priority=1, status="PENDING", dockerTaskId=None)


def generate_scenario(kind: str = "normal", *, seed: int = 42, slots: int = 24,
                      origin: str | datetime = "2026-10-24T00:00:00Z") -> dict:
    if kind not in KINDS:
        raise ValueError(f"Unknown scenario: {kind}")
    if type(seed) is not int or type(slots) is not int or slots < 12:
        raise ValueError("Integer seed and at least 12 hourly slots required")
    origin_time = utc(origin)
    if origin_time.minute or origin_time.second or origin_time.microsecond:
        raise ValueError("Scenario origin must align to a UTC hour")
    # Separate local streams avoid global RNG state and changes caused by policy order.
    price_rng = random.Random(seed)
    workload_rng = random.Random(seed + 1)
    market = []
    for slot in range(slots):
        for region, gpu_base, cpu_base in zip(DEFAULT_REGIONS, (320, 390, 350), (45, 50, 48)):
            for resource, gpu_type, base, units in (("GPU", "NVIDIA T4", gpu_base, 2),
                                                    ("CPU", None, cpu_base, 8)):
                price = (base + price_rng.randint(-2, 2)) / 1000
                if kind == "price-spike" and resource == "GPU" and region == DEFAULT_REGIONS[0] and 4 <= slot < 7:
                    price = round(price * 3, 3)
                capacity = units
                if kind == "capacity-shortage" and resource == "GPU" and region == DEFAULT_REGIONS[0] and 6 <= slot < 9:
                    capacity = 0
                market.append(dict(slot=slot, region=region, resourceType=resource,
                                   gpuType=gpu_type, priceUsdPerUnitHour=price,
                                   availableUnits=capacity, carbonKgPerUnitHour=None,
                                   source=VERSION, dataKind="SIMULATED"))
    jobs = [_job("gpu-start", 0, 2, 6),
            _job("cpu-start", 0, 3, 8, "CPU", None, 2),
            _job("gpu-later", 3, workload_rng.randint(1, 3), 12),
            _job("impossible-time", 2, 3, 4),
            _job("impossible-hardware", 1, 1, 10, gpu_type="UNSUPPORTED_GPU")]
    events = []
    if kind in ("price-spike", "capacity-shortage", "interruption"):
        event_kind, slot, region = {
            "price-spike": ("PRICE_SPIKE", 4, DEFAULT_REGIONS[0]),
            "capacity-shortage": ("CAPACITY_SHORTAGE", 6, DEFAULT_REGIONS[0]),
            "interruption": ("INTERRUPTION", 9, DEFAULT_REGIONS[1]),
        }[kind]
        events.append(dict(kind=event_kind, slot=slot, region=region,
                           resourceType="GPU", gpuType="NVIDIA T4", dataKind="SIMULATED"))
    if kind == "deadline-pressure":
        urgent = _job("urgent-arrival", 6, 2, 8)
        urgent["priority"] = 10
        jobs.append(urgent)
        events.append(dict(kind="DEADLINE_PRESSURE", slot=6, jobId=urgent["id"], dataKind="SIMULATED"))
    for job in jobs:
        events.append(dict(kind="JOB_ARRIVAL", slot=job["arrivalSlot"],
                           jobId=job["id"], dataKind="SIMULATED"))
    return dict(schemaVersion=VERSION, scenarioId=kind, seed=seed,
                originUtc=stamp(origin_time), slotDurationSeconds=3600, slots=slots,
                dataKind="SIMULATED",
                provenance={"prices": "SIMULATED", "capacity": "SIMULATED",
                            "jobs": "SIMULATED", "interruptions": "SIMULATED"},
                market=market, jobs=sorted(jobs, key=lambda j: (j["arrivalSlot"], j["id"])),
                events=sorted(events, key=lambda e: (e["slot"], e["kind"], e.get("jobId", ""))),
                deliberatelyInfeasibleJobs={"impossible-time": "duration exceeds arrival-to-deadline window",
                                           "impossible-hardware": "no matching GPU pool"})


def observations_at(scenario: dict, current_slot: int) -> dict:
    """A fresh causal view for a forecaster/scheduler, excluding future events/jobs.

    Completed/failed job state still belongs to the replay engine, not this data
    function. Event annotations must not reapply shocks already in market rows.
    """
    if type(current_slot) is not int or not 0 <= current_slot < scenario["slots"]:
        raise ValueError("Current slot outside scenario")
    return deepcopy(dict(currentSlot=current_slot, originUtc=scenario["originUtc"],
                         dataKind="SIMULATED",
                         market=[r for r in scenario["market"] if r["slot"] <= current_slot],
                         jobs=[j for j in scenario["jobs"] if j["arrivalSlot"] <= current_slot],
                         events=[e for e in scenario["events"] if e["slot"] <= current_slot]))


def independent_strategy_inputs(scenario: dict, current_slot: int) -> dict[str, dict]:
    """Identical exogenous input, independently mutable for all four policies."""
    observation = observations_at(scenario, current_slot)
    return {strategy: deepcopy(observation) for strategy in STRATEGIES}


def save_suite(output: Path, *, seed: int = 42, slots: int = 24,
               origin: str = "2026-10-24T00:00:00Z") -> None:
    files = {}
    for kind in KINDS:
        scenario = generate_scenario(kind, seed=seed, slots=slots, origin=origin)
        files[f"{kind}.json"] = (json.dumps(scenario, indent=2, sort_keys=True) + "\n").encode()
    manifest = dict(schemaVersion=VERSION, seed=seed, dataKind="SIMULATED",
                    sha256={name: hashlib.sha256(body).hexdigest() for name, body in files.items()})
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        (output / name).write_bytes(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--slots", type=int, default=24)
    parser.add_argument("--origin", default="2026-10-24T00:00:00Z")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        save_suite(args.output, seed=args.seed, slots=args.slots, origin=args.origin)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Scenario generation rejected: {exc}\n")
    print(f"Saved {len(KINDS)} SIMULATED scenarios to {args.output}")


if __name__ == "__main__":
    main()
