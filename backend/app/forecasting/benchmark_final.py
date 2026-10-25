"""Replay frozen simulated workloads against observed final-test prices."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

from app.engine.forecast_benchmark import Workload, replay
from app.forecasting.collect_spot import utc
from app.forecasting.contracts import slot_for_timestamp
from app.forecasting.evaluate_final import DEFAULT_DESIGN
from app.forecasting.training_data import load_prepared_dataset


def pool_id(identity):
    return "|".join((identity.region, identity.availability_zone, identity.instance_type, identity.product_description))


def generate_workloads(instance, pools, units, start, end, design, seed):
    # Separate RNG per instance avoids policy order and scenario execution order.
    rng = random.Random(f"{seed}:{instance}")
    jobs = []
    for arrival in range(start+rng.randrange(4), end-design["deadlineAfterArrivalSlots"], design["arrivalIntervalSlots"]):
        for index in range(design["burstSize"]):
            jobs.append(Workload(id=f"{instance}:{arrival}:{index}", arrival=arrival,
                duration=rng.randint(*design["durationRangeSlots"]),
                deadline=arrival+design["deadlineAfterArrivalSlots"], allowed_pools=tuple(sorted(pools)),
                units=units, priority=rng.randint(1, 3)))
    return jobs


def run_benchmark(dataset_directory, forecast_directory, report_directory, metadata_path):
    if report_directory.exists():
        raise ValueError("Use a fresh replay output directory")
    design_payload = DEFAULT_DESIGN.read_bytes()
    design = json.loads(design_payload)
    final_bytes = (forecast_directory / "report.json").read_bytes()
    final = json.loads(final_bytes)
    if final["designSha256"] != hashlib.sha256(design_payload).hexdigest():
        raise ValueError("Forecasts do not match the frozen final/replay design")
    scenario = design["replay"]
    if (scenario["schemaVersion"] != "offline-compute-ablation-v1" or
            scenario["operationalDataKind"] != "SIMULATED" or scenario["priceDataKind"] != "OBSERVED" or
            scenario["startupAndTransferCostUsd"] != 0 or scenario["capacityInstancesPerPool"] != 1):
        raise ValueError("Unsupported frozen replay assumptions")
    dataset = load_prepared_dataset(dataset_directory)
    if dataset.sha256 != final["datasetSha256"]:
        raise ValueError("Replay prices differ from forecast evaluation prices")
    metadata_bytes = metadata_path.read_bytes()
    metadata = json.loads(metadata_bytes)
    hardware = {(m["region"], m["instanceType"]): m for m in metadata}
    if len(hardware) != len(metadata):
        raise ValueError("Duplicate hardware mappings")
    start = slot_for_timestamp(dataset.origin, design["testStartUtc"])
    test_end = slot_for_timestamp(dataset.origin, design["testEndUtcExclusive"])
    # Forecast examples require all six targets in the final partition. Restrict
    # arrivals further so every job's deadline falls before the last usable origin.
    end = test_end-6
    selected = [s for s in dataset.series if s.identity.instance_type in scenario["instanceTypes"]]
    forecasts = {}
    forecast_file = forecast_directory / "predictions.jsonl"
    with forecast_file.open() as stream:
        for line in stream:
            row = json.loads(line)
            identity = row["identity"]
            if identity["instance_type"] in scenario["instanceTypes"]:
                pool = "|".join(identity[key] for key in ("region", "availability_zone", "instance_type", "product_description"))
                forecasts.setdefault(row["originSlot"], {})[pool, row["targetSlot"]] = row["prediction"]
    results = []
    for seed in scenario["seeds"]:
        for instance in scenario["instanceTypes"]:
            series = [s for s in selected if s.identity.instance_type == instance]
            if not series:
                raise ValueError(f"Missing selected instance type: {instance}")
            hardware_rows = [hardware[s.identity.region, instance] for s in series]
            units_set = {m["allocationGranularityUnits"] for m in hardware_rows}
            if len(units_set) != 1:
                raise ValueError("Inconsistent whole-instance sizes across pools")
            units = units_set.pop()
            pools = {pool_id(s.identity): s for s in series}
            capacity = {pool: units for pool in pools}
            jobs = generate_workloads(instance, pools, units, start, end, scenario, seed)

            def observations(t):
                return {pool: s.prices[t] for pool, s in pools.items() if s.prices.get(t) is not None}

            def predictions(t):
                values = forecasts.get(t, {})
                missing = [(pool, target) for pool in pools for target in range(t+1, t+7) if (pool, target) not in values]
                if missing:
                    raise ValueError(f"Missing generated-at-current forecast coverage: {missing[0]}")
                return {key: price for key, price in values.items() if key[0] in pools}

            policies = [replay(jobs, pools, capacity, observations, predictions, start, end, strategy)
                        for strategy in scenario["strategies"]]
            baseline = next(p for p in policies if p["strategy"] == "OPTIMIZER_WITH_NAIVE_FORECAST")
            ml = next(p for p in policies if p["strategy"] == "OPTIMIZER_WITH_ML")
            comparable = (baseline["completedJobIds"] == ml["completedJobIds"] and
                baseline["missedJobIds"] == ml["missedJobIds"] and
                baseline["unfinishedJobIds"] == ml["unfinishedJobIds"] and baseline["failedJobs"] == ml["failedJobs"])
            results.append(dict(seed=seed, instanceType=instance, jobCount=len(jobs),
                resourceType=hardware_rows[0]["resourceType"], gpuType=hardware_rows[0].get("gpuType"),
                resourceUnitsPerInstance=units, comparableWorkloadOutcomes=comparable,
                mlSavingsVsNaivePct=100*(baseline["totalSpendUsd"]-ml["totalSpendUsd"])/baseline["totalSpendUsd"]
                    if comparable and baseline["totalSpendUsd"] else None, policies=policies))
        print(f"Replay seed {seed} complete", flush=True)
    totals = {}
    for strategy in scenario["strategies"]:
        policies = [p for r in results for p in r["policies"] if p["strategy"] == strategy]
        totals[strategy] = {field: sum(p[field] for p in policies) for field in
            ("totalSpendUsd", "completedJobs", "missedDeadlines", "failedJobs", "unfinishedJobs", "recoveryCostUsd")}
    baseline, ml = totals["OPTIMIZER_WITH_NAIVE_FORECAST"], totals["OPTIMIZER_WITH_ML"]
    comparable = all(r["comparableWorkloadOutcomes"] for r in results)
    report = dict(schemaVersion="offline-compute-ablation-results-v1", executionMode="SIMULATED",
        provenance=dict(prices="OBSERVED", capacity="SIMULATED", workloads="SIMULATED", interruptions="ASSUMED_NONE"),
        designSha256=hashlib.sha256(design_payload).hexdigest(), finalReportSha256=hashlib.sha256(final_bytes).hexdigest(),
        datasetSha256=dataset.sha256, metadataSha256=hashlib.sha256(metadata_bytes).hexdigest(),
        predictionsSha256=hashlib.sha256(forecast_file.read_bytes()).hexdigest(),
        startSlot=start, endSlotExclusive=end, configuration=scenario, totals=totals,
        comparableWorkloadOutcomes=comparable,
        mlSavingsVsNaivePct=100*(baseline["totalSpendUsd"]-ml["totalSpendUsd"])/baseline["totalSpendUsd"]
            if comparable and baseline["totalSpendUsd"] else None,
        implementationSha256={"benchmark_final.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "forecast_benchmark.py": hashlib.sha256((Path(__file__).parents[1]/"engine/forecast_benchmark.py").read_bytes()).hexdigest()},
        cases=results,
        limitations=["Observed AWS prices with synthetic jobs and static capacity; not actual cloud savings or execution.",
            "Small exact horizon scheduler, separate from unimplemented production API optimizer/replay.",
            "Nine frozen instance types, one region, three workload seeds; not every hardware pool or capacity regime.",
            "No interruptions, recovery/startup/transfer costs or calibrated reliability; these assumptions may materially affect results.",
            "Final test and replay results are now observed; future tuning requires a new evaluation period."])
    report_directory.mkdir(parents=True, exist_ok=False)
    (report_directory / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print("ML savings vs naive (%):", report["mlSavingsVsNaivePct"], "comparable:", comparable, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--forecast-run", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_benchmark(args.dataset, args.forecast_run, args.report_output, args.metadata)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Replay failed: {exc}\n")


if __name__ == "__main__":
    main()
