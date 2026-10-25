from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest

from app.forecasting.scenario_data import (
    KINDS, STRATEGIES, generate_scenario, independent_strategy_inputs, observations_at, save_suite,
)


class ScenarioTests(unittest.TestCase):
    def test_repeatable_and_seed_changes_data_without_global_rng_effects(self):
        state = random.getstate()
        for kind in KINDS:
            self.assertEqual(generate_scenario(kind), generate_scenario(kind))
        self.assertNotEqual(generate_scenario(seed=42)["market"], generate_scenario(seed=43)["market"])
        self.assertEqual(state, random.getstate())

    def test_all_rows_have_explicit_provenance_and_unique_market_keys(self):
        for kind in KINDS:
            scenario = generate_scenario(kind)
            self.assertEqual(set(scenario["provenance"].values()), {"SIMULATED"})
            keys = set()
            for row in scenario["market"]:
                self.assertEqual(row["dataKind"], "SIMULATED")
                self.assertGreaterEqual(row["availableUnits"], 0)
                self.assertGreater(row["priceUsdPerUnitHour"], 0)
                keys.add((row["slot"], row["region"], row["resourceType"], row["gpuType"]))
            self.assertEqual(len(keys), 24 * 3 * 2)
            for event in scenario["events"]:
                self.assertEqual(event["dataKind"], "SIMULATED")

    def test_causal_views_exclude_future_jobs_prices_and_events(self):
        scenario = generate_scenario("price-spike")
        before = observations_at(scenario, 2)
        changed = deepcopy(scenario)
        for row in changed["market"]:
            if row["slot"] > 2:
                row["priceUsdPerUnitHour"] = 999
        for job in changed["jobs"]:
            if job["arrivalSlot"] > 2:
                job["maxBudgetUsd"] = 999
        for event in changed["events"]:
            if event["slot"] > 2:
                event["kind"] = "changed-future-event"
        self.assertEqual(before, observations_at(changed, 2))
        self.assertTrue(all(row["slot"] <= 2 for row in before["market"]))
        self.assertTrue(all(job["arrivalSlot"] <= 2 for job in before["jobs"]))
        self.assertNotIn("PRICE_SPIKE", [e["kind"] for e in before["events"]])
        self.assertIn("PRICE_SPIKE", [e["kind"] for e in observations_at(scenario, 4)["events"]])

    def test_strategies_receive_equal_but_independent_inputs(self):
        scenario = generate_scenario("interruption")
        original = deepcopy(scenario)
        inputs = independent_strategy_inputs(scenario, 9)
        self.assertEqual(tuple(inputs), STRATEGIES)
        self.assertTrue(all(value == inputs["FIFO"] for value in inputs.values()))
        inputs["FIFO"]["jobs"][0]["status"] = "COMPLETED"
        inputs["FIFO"]["market"][0]["availableUnits"] = 0
        inputs["FIFO"]["events"].clear()
        self.assertEqual(scenario, original)
        self.assertEqual(inputs["CHEAPEST_NOW"], observations_at(scenario, 9))

    def test_shock_variants_change_only_intended_inputs(self):
        base = generate_scenario()
        spike = generate_scenario("price-spike")
        shortage = generate_scenario("capacity-shortage")
        for normal, spiked, scarce in zip(base["market"], spike["market"], shortage["market"]):
            target = normal["region"] == "us-east-1" and normal["resourceType"] == "GPU"
            multiplier = 3 if target and 4 <= normal["slot"] < 7 else 1
            self.assertEqual(Decimal(str(spiked["priceUsdPerUnitHour"])),
                             Decimal(str(normal["priceUsdPerUnitHour"])) * multiplier)
            self.assertEqual(scarce["availableUnits"],
                             0 if target and 6 <= normal["slot"] < 9 else normal["availableUnits"])
        interruption = generate_scenario("interruption")
        self.assertEqual(base["market"], interruption["market"])
        self.assertEqual(base["jobs"], interruption["jobs"])
        events = [e for e in interruption["events"] if e["kind"] == "INTERRUPTION"]
        self.assertEqual(len(events), 1)
        self.assertNotIn("jobId", events[0])  # Exogenous, never policy-specific victim selection.

    def test_feasible_witness_schedule_and_deliberate_infeasibility(self):
        # A hand-written witness validates inputs; it is not a replay benchmark.
        scenario = generate_scenario()
        jobs = {job["id"]: job for job in scenario["jobs"]}
        reservations = {}
        for job_id, start in (("gpu-start", 0), ("cpu-start", 0), ("gpu-later", 3)):
            job = jobs[job_id]
            end = start + job["durationSlots"]
            self.assertGreaterEqual(start, job["arrivalSlot"])
            self.assertLessEqual(end, job["deadlineSlot"])
            cost = 0
            for slot in range(start, end):
                row = next(r for r in scenario["market"] if r["slot"] == slot and
                           r["region"] == "us-east-1" and r["resourceType"] == job["resourceType"])
                key = (slot, row["region"], row["resourceType"])
                reservations[key] = reservations.get(key, 0) + job["resourceUnits"]
                self.assertLessEqual(reservations[key], row["availableUnits"])
                self.assertEqual(row["gpuType"], job["gpuType"])
                cost += row["priceUsdPerUnitHour"] * job["resourceUnits"]
            self.assertLessEqual(cost, job["maxBudgetUsd"])
        impossible = jobs["impossible-time"]
        self.assertGreater(impossible["arrivalSlot"] + impossible["durationSlots"], impossible["deadlineSlot"])
        self.assertNotIn(jobs["impossible-hardware"]["gpuType"], {r["gpuType"] for r in scenario["market"]})

    def test_pressure_job_arrives_with_zero_slack(self):
        scenario = generate_scenario("deadline-pressure")
        self.assertNotIn("urgent-arrival", [j["id"] for j in observations_at(scenario, 5)["jobs"]])
        urgent = next(j for j in observations_at(scenario, 6)["jobs"] if j["id"] == "urgent-arrival")
        self.assertEqual(urgent["arrivalSlot"] + urgent["durationSlots"], urgent["deadlineSlot"])

    def test_input_validation(self):
        for kwargs in ({"kind": "unknown"}, {"seed": True}, {"slots": 5},
                       {"origin": "2026-10-24T00:30:00Z"}, {"origin": "2026-10-24T00:00:00"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate_scenario(**kwargs)
        for slot in (-1, 24, True):
            with self.assertRaises(ValueError):
                observations_at(generate_scenario(), slot)

    def test_saved_suite_reproducible_hashes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/"a", Path(tmp)/"b"
            save_suite(a)
            save_suite(b)
            manifest = json.loads((a/"manifest.json").read_text())
            for name, expected in manifest["sha256"].items():
                payload = (a/name).read_bytes()
                self.assertEqual(payload, (b/name).read_bytes())
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected)
            with self.assertRaises(FileExistsError):
                save_suite(a)

    def test_generated_records_match_shared_api_schemas(self):
        try:
            from app.api.schemas import ForecastRequest, Job, MarketSnapshot
        except ModuleNotFoundError as exc:
            if exc.name == "pydantic":
                self.skipTest("Install backend dev dependencies for shared-schema validation")
            raise
        for kind in KINDS:
            scenario = generate_scenario(kind)
            for job in scenario["jobs"]:
                Job.model_validate(job)
            for row in scenario["market"]:
                MarketSnapshot.model_validate(row)
            view = observations_at(scenario, 3)
            ForecastRequest(currentSlot=3, history=view["market"])

    def test_checked_in_suite_matches_generator_and_manifest(self):
        directory = Path(__file__).resolve().parents[3] / "data/scenarios/generated-v1"
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(set(manifest["sha256"]), {f"{kind}.json" for kind in KINDS})
        for kind in KINDS:
            name = f"{kind}.json"
            payload = (directory / name).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["sha256"][name])
            self.assertEqual(json.loads(payload), generate_scenario(kind, seed=manifest["seed"]))


if __name__ == "__main__":
    unittest.main()
