"""All evidence here is a synthetic test fixture, including OBSERVED-gate tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from app.forecasting.operational_data import import_observations, summarize_evidence
from app.forecasting.operational_schemas import OperationalDataset
from app.forecasting.risk_model import unknown_risk

EXAMPLE = Path(__file__).resolve().parents[3] / "data/examples/operational-observations.simulated.json"


def example():
    return json.loads(EXAMPLE.read_text())


class OperationalDataTests(unittest.TestCase):
    def test_counts_separate_fulfillment_errors_censoring_and_interruptions(self):
        report = summarize_evidence(OperationalDataset.model_validate(example()))
        self.assertEqual(report["fulfillment"]["requestCount"], 5)
        self.assertEqual(report["fulfillment"]["resolvedCapacityLabels"], 3)
        self.assertEqual(report["fulfillment"]["fullFulfillmentEvents"], 1)
        self.assertEqual(report["fulfillment"]["incompleteFulfillmentEvents"], 2)
        self.assertEqual(report["execution"]["interruptionEvents"], 1)
        self.assertEqual(report["execution"]["executionCount"], 4)
        self.assertEqual(report["execution"]["outcomeCounts"]["FAILED"], 1)

    def test_hand_calculated_exposure_includes_observed_censored_time(self):
        report = summarize_evidence(OperationalDataset.model_validate(example()))
        self.assertEqual(report["execution"]["observedEpisodeHours"], 6.5)
        self.assertEqual(report["execution"]["censoredEpisodeHours"], 3)
        groups = {g["resourceUnits"]: g for g in report["executionGroups"]}
        self.assertEqual(groups[1]["resourceUnitHours"], 3.5)
        self.assertEqual(groups[2]["resourceUnitHours"], 6)

    def test_probabilities_unknown_with_no_simulated_or_uncalibrated_observed_data(self):
        for kind, status in (("SIMULATED", "SIMULATED_ONLY"), ("OBSERVED", "OBSERVED_UNCALIBRATED")):
            data = example()
            data["provenance"]["dataKind"] = kind
            risk = summarize_evidence(OperationalDataset.model_validate(data))["risk"]
            self.assertEqual(risk["evidenceStatus"], status)
            self.assertIsNone(risk["availabilityProbability"])
            self.assertIsNone(risk["interruptionProbability"])
        data["fulfillmentObservations"] = []
        data["executionObservations"] = []
        report = summarize_evidence(OperationalDataset.model_validate(data))
        self.assertEqual(report["risk"], unknown_risk())
        self.assertEqual(report["execution"]["observedEpisodeHours"], 0)

    def test_zero_interruptions_do_not_mean_zero_risk(self):
        data = example()
        data["provenance"]["dataKind"] = "OBSERVED"
        data["executionObservations"] = [data["executionObservations"][0]]
        report = summarize_evidence(OperationalDataset.model_validate(data))
        self.assertEqual(report["execution"]["interruptionEvents"], 0)
        self.assertIsNone(report["risk"]["interruptionProbability"])

    def test_cutoff_uses_record_availability_not_execution_start_or_end(self):
        data = OperationalDataset.model_validate(example())
        report = summarize_evidence(data, as_of="2026-10-24T10:00:00Z")
        self.assertEqual(report["execution"]["executionCount"], 1)
        self.assertEqual(report["execution"]["interruptionEvents"], 0)
        self.assertEqual(report["execution"]["observedEpisodeHours"], 2)
        early = summarize_evidence(data, as_of="2026-10-24T08:05:00Z")
        self.assertEqual(early["risk"]["evidenceStatus"], "NO_OBSERVATIONS")
        with self.assertRaises(ValueError):
            summarize_evidence(data, as_of="2026-10-24T13:00:00Z")

    def test_future_outcome_changes_do_not_change_earlier_summary(self):
        data = example()
        original = summarize_evidence(OperationalDataset.model_validate(data), as_of="2026-10-24T09:30:00Z")
        data["executionObservations"][1]["outcome"] = "COMPLETED"
        data["executionObservations"][1]["interruptedAt"] = None
        data["executionObservations"].pop()
        changed = summarize_evidence(OperationalDataset.model_validate(data), as_of="2026-10-24T09:30:00Z")
        self.assertEqual(original, changed)

    def test_timezone_normalization_and_naive_or_numeric_rejection(self):
        data = example()
        data["executionObservations"][0]["startedAt"] = "2026-10-24T08:00:00+01:00"
        normalized = OperationalDataset.model_validate(data).model_dump(mode="json", by_alias=True)
        self.assertEqual(normalized["executionObservations"][0]["startedAt"], "2026-10-24T07:00:00Z")
        for timestamp in ("2026-10-24T07:00:00", 1792825200):
            data["executionObservations"][0]["startedAt"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(ValidationError):
                OperationalDataset.model_validate(data)

    def test_invalid_outcomes_and_chronology_rejected(self):
        changes = [
            ("fulfillmentObservations", 0, {"fulfilledUnits": 1}),
            ("fulfillmentObservations", 1, {"fulfilledUnits": 0}),
            ("fulfillmentObservations", 2, {"fulfilledUnits": 1}),
            ("fulfillmentObservations", 4, {"fulfilledUnits": 2}),
            ("fulfillmentObservations", 0, {"requestedUnits": True}),
            ("fulfillmentObservations", 0, {"requestedAt": "2026-10-24T09:00:00Z"}),
            ("executionObservations", 1, {"interruptedAt": None}),
            ("executionObservations", 1, {"interruptedAt": "2026-10-24T09:59:00Z"}),
            ("executionObservations", 0, {"interruptedAt": "2026-10-24T09:00:00Z"}),
            ("executionObservations", 0, {"resourceUnits": 0}),
            ("executionObservations", 0, {"observedUntil": "2026-10-24T06:00:00Z"}),
            ("executionObservations", 0, {"recordedAt": "2026-10-24T08:00:00Z"}),
            ("executionObservations", 0, {"recordedAt": "2026-10-24T13:00:00Z"}),
            ("executionObservations", 0, {"gpuType": None}),
            ("executionObservations", 0, {"resourceType": "CPU"}),
        ]
        for category, index, change in changes:
            data = example()
            data[category][index].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                OperationalDataset.model_validate(data)

    def test_duplicate_ids_and_missing_provenance_rejected(self):
        for category in ("fulfillmentObservations", "executionObservations"):
            data = example()
            data[category].append(deepcopy(data[category][0]))
            with self.assertRaises(ValidationError):
                OperationalDataset.model_validate(data)
        for change in ({"authorizedForUse": False}, {"authorizedForUse": "true"},
                       {"source": " "}, {"labelDefinitions": {}}, {"dataKind": "FORECAST"}):
            data = example()
            data["provenance"].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                OperationalDataset.model_validate(data)

    def test_placement_scores_cannot_be_imported_as_labels(self):
        data = example()
        data["fulfillmentObservations"][0]["placementScore"] = 8
        with self.assertRaises(ValidationError):
            OperationalDataset.model_validate(data)

    def test_grouping_keeps_sizes_hardware_and_locations_separate(self):
        data = example()
        more = deepcopy(data["fulfillmentObservations"][0])
        more.update(id="different-size", requestedUnits=1, fulfilledUnits=1)
        data["fulfillmentObservations"].append(more)
        more = deepcopy(more)
        more.update(id="different-zone", availabilityZone="us-east-1b")
        data["fulfillmentObservations"].append(more)
        more = deepcopy(more)
        more.update(id="different-hardware", instanceType="test.other", gpuType="TestGPU")
        data["fulfillmentObservations"].append(more)
        report = summarize_evidence(OperationalDataset.model_validate(data))
        self.assertEqual(len(report["fulfillmentGroups"]), 4)

    def test_cpu_and_gpu_exposure_units_are_not_added_together(self):
        data = example()
        cpu = deepcopy(data["executionObservations"][0])
        cpu.update(id="cpu-episode", resourceType="CPU", gpuType=None,
                   instanceType="test.cpu", resourceUnits=4)
        data["executionObservations"].append(cpu)
        report = summarize_evidence(OperationalDataset.model_validate(data))
        group = next(g for g in report["executionGroups"] if g["resourceType"] == "CPU")
        self.assertEqual(group["resourceUnitHours"], 8)
        self.assertEqual(group["exposureUnit"], "vCPU-hour")
        self.assertNotIn("resourceUnitHours", report["execution"])

    def test_import_hashes_simulation_label_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/"imported"
            summary = import_observations(EXAMPLE, output)
            manifest = json.loads((output/"manifest.json").read_text())
            self.assertEqual(manifest["inputSha256"], hashlib.sha256(EXAMPLE.read_bytes()).hexdigest())
            for name, expected in manifest["sha256"].items():
                self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(), expected)
            self.assertEqual(summary["dataKind"], "SIMULATED")
            with self.assertRaises(ValueError):
                import_observations(EXAMPLE, output)

    def test_invalid_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/"bad.json", Path(tmp)/"output"
            data = example()
            data["executionObservations"][1]["interruptedAt"] = None
            source.write_text(json.dumps(data))
            with self.assertRaises(ValidationError):
                import_observations(source, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
