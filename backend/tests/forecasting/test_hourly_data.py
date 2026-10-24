from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.forecasting.hourly_data import prepare_collection, reconstruct_hourly, slot_cost
from app.forecasting.resource_metadata import save_metadata

FIXTURE = Path(__file__).resolve().parents[3] / "data/examples/hourly-price-events.simulated.json"
START, END = "2026-10-24T00:00:00Z", "2026-10-24T04:00:00Z"


def events():
    return json.loads(FIXTURE.read_text())["events"]


def reconstruct(rows=None, gaps=None):
    return reconstruct_hourly(events() if rows is None else rows, start=START, end=END, gaps=gaps)


class HourlyDataTests(unittest.TestCase):
    def test_hand_calculated_slot_start_and_mid_hour_averages(self):
        rows, report = reconstruct()
        gpu = [row for row in rows if row["resourceType"] == "GPU"]
        cpu = [row for row in rows if row["resourceType"] == "CPU"]
        self.assertEqual([Decimal(row["priceUsdPerUnitHour"]) for row in gpu],
                         list(map(Decimal, ("0.30", "0.60", "0.45", "0.45"))))
        self.assertEqual(Decimal(gpu[0]["timeWeightedAveragePriceUsdPerUnitHour"]), Decimal("0.45"))
        self.assertEqual(Decimal(cpu[1]["priceUsdPerUnitHour"]), Decimal("0.05"))
        self.assertEqual(Decimal(cpu[1]["timeWeightedAveragePriceUsdPerUnitHour"]), Decimal("0.075"))
        self.assertEqual(report["rowCount"], 8)
        self.assertFalse(report["hasCapacityObservations"])
        self.assertFalse(any(row["meets60DayCoverageTarget"] for row in report["series"]))
        self.assertTrue(all("availableUnits" not in row for row in rows))

    def test_future_event_does_not_change_earlier_point_price(self):
        original, _ = reconstruct()
        changed = events()
        changed[1].update(priceUsdPerUnitHour="0.90", priceUsdPerInstanceHour="0.90")
        actual, _ = reconstruct(changed)
        fields = ("priceUsdPerUnitHour", "effectivePriceTimestamp", "priceStatus")
        self.assertEqual([original[0][f] for f in fields], [actual[0][f] for f in fields])
        # A retrospective full-hour average may change; it is not an online feature.
        self.assertNotEqual(original[0]["timeWeightedAveragePriceUsdPerUnitHour"],
                            actual[0]["timeWeightedAveragePriceUsdPerUnitHour"])

    def test_missing_start_anchor_is_not_filled_using_future_event(self):
        rows, _ = reconstruct(events()[1:])
        first = rows[0]
        self.assertEqual(first["priceStatus"], "NO_PAST_PRICE")
        self.assertIsNone(first["priceUsdPerUnitHour"])
        self.assertIsNone(first["timeWeightedAveragePriceUsdPerUnitHour"])
        self.assertEqual(rows[1]["priceStatus"], "KNOWN")

    def test_known_ingestion_gap_requires_a_new_post_gap_observation(self):
        gap = {name: events()[0][name] for name in ("region", "availabilityZone", "instanceType", "productDescription")}
        gap.update(startTime="2026-10-24T00:45:00Z", endTime="2026-10-24T01:15:00Z")
        rows, _ = reconstruct(gaps=[gap])
        self.assertEqual(rows[0]["priceStatus"], "KNOWN")
        self.assertIsNone(rows[0]["timeWeightedAveragePriceUsdPerUnitHour"])
        self.assertEqual(rows[1]["priceStatus"], "INGESTION_GAP")
        self.assertIsNone(rows[1]["priceUsdPerUnitHour"])
        self.assertEqual(rows[2]["priceStatus"], "KNOWN")

    def test_unchanged_old_price_is_not_itself_an_ingestion_gap(self):
        old = events()[0]
        old["timestamp"] = "2026-09-01T00:00:00Z"
        rows, _ = reconstruct([old])
        self.assertTrue(all(row["priceStatus"] == "KNOWN" for row in rows))
        self.assertTrue(all(Decimal(row["priceUsdPerUnitHour"]) == Decimal("0.30") for row in rows))

    def test_az_series_remain_separate_instead_of_hindsight_minimum(self):
        alternative = deepcopy(events()[0])
        alternative.update(availabilityZone="us-east-1b", priceUsdPerUnitHour="0.90", priceUsdPerInstanceHour="0.90")
        rows, report = reconstruct(events() + [alternative])
        self.assertEqual(report["seriesCount"], 3)
        self.assertEqual(len(rows), 12)
        self.assertEqual({r["availabilityZone"] for r in rows if r["resourceType"] == "GPU"},
                         {"us-east-1a", "us-east-1b"})

    def test_duplicates_invalid_mappings_and_forecast_input(self):
        raw = events()
        _, report = reconstruct(raw + [deepcopy(raw[0])])
        self.assertEqual(report["identicalDuplicatesRemoved"], 1)
        conflict = dict(raw[0], priceUsdPerUnitHour="0.99", priceUsdPerInstanceHour="0.99")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            reconstruct(raw + [conflict])
        for update in ({"dataKind": "FORECAST"}, {"gpuType": None}, {"resourceUnitsPerInstance": True},
                       {"priceUsdPerUnitHour": "NaN"}, {"priceUsdPerUnitHour": "0.15"}):
            bad = deepcopy(raw)
            bad[0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                reconstruct(bad)

    def test_slot_cost_uses_original_whole_instance_bill(self):
        rows, _ = reconstruct()
        cpu = next(row for row in rows if row["resourceType"] == "CPU")
        self.assertEqual(slot_cost(cpu, 4), Decimal("0.20"))
        self.assertEqual(slot_cost(cpu, 8), Decimal("0.40"))
        with self.assertRaises(ValueError):
            slot_cost(cpu, 1)
        missing, _ = reconstruct(events()[1:])
        with self.assertRaises(ValueError):
            slot_cost(missing[0], 1)

    def test_preparation_fixture_hashes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/"prepared"
            report = prepare_collection(output, start=START, end=END, fixture=FIXTURE)
            payload = (output/"hourly-prices.jsonl").read_bytes()
            self.assertEqual(report["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(report["priceKinds"], ["SIMULATED"])
            self.assertTrue(all(json.loads(line)["dataKind"] == "SIMULATED" for line in payload.splitlines()))
            with self.assertRaises(ValueError):
                prepare_collection(output, start=START, end=END, fixture=FIXTURE)

    def test_step2_collection_bridge_checksum_and_window_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            collection = Path(tmp)/"metadata"
            report = {"inputPriceWindow": {"startTime": START, "endTime": END, "paginationComplete": True}}
            metadata = []
            for row in (events()[0], events()[-1]):
                meta = {name: row[name] for name in (
                    "region", "instanceType", "resourceType", "gpuType", "resourceUnitsPerInstance",
                    "allocationGranularityUnits", "unit", "dataKind", "retrievedAt")}
                meta.update(gpuCount=1 if row["resourceType"] == "GPU" else 0,
                            vcpuCount=4, source="SIMULATED metadata for the preparation bridge test")
                metadata.append(meta)
            save_metadata(collection, metadata, report, events())
            result = prepare_collection(Path(tmp)/"hourly", start=START, end=END, collection=collection)
            self.assertEqual(result["rowCount"], 8)
            with self.assertRaisesRegex(ValueError, "window"):
                prepare_collection(Path(tmp)/"out-of-window", start=START, end="2026-10-24T05:00:00Z", collection=collection)
            (collection/"normalized-prices.jsonl").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                prepare_collection(Path(tmp)/"tampered", start=START, end=END, collection=collection)

    def test_invalid_window_and_fixture_labels_rejected_without_output(self):
        with self.assertRaises(ValueError):
            reconstruct_hourly(events(), start=START, end=START)
        with self.assertRaises(ValueError):
            reconstruct_hourly(events(), start="2026-10-24T00:30:00Z", end=END)
        with tempfile.TemporaryDirectory() as tmp:
            bad_fixture, output = Path(tmp)/"bad.json", Path(tmp)/"output"
            document = json.loads(FIXTURE.read_text())
            document["dataKind"] = "OBSERVED"
            bad_fixture.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "SIMULATED"):
                prepare_collection(output, start=START, end=END, fixture=bad_fixture)
            self.assertFalse(output.exists())

    def test_checked_in_prepared_example_is_reproducible(self):
        checked = FIXTURE.parent / "prepared-hourly-simulated"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/"prepared"
            prepare_collection(output, start=START, end=END, fixture=FIXTURE)
            for name in ("hourly-prices.jsonl", "manifest.json"):
                self.assertEqual((output/name).read_bytes(), (checked/name).read_bytes())


if __name__ == "__main__":
    unittest.main()
