"""Synthetic API responses test collection mechanics, not real price outcomes."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.forecasting.collect_spot import collect, save, utc

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
START = NOW - timedelta(days=2)


def event(price="0.25", timestamp=None, zone="us-east-1a"):
    return dict(Timestamp=timestamp or START, SpotPrice=price,
                AvailabilityZone=zone, InstanceType="g4dn.xlarge",
                ProductDescription="Linux/UNIX")


class FakeClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def describe_spot_price_history(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pages)


class CollectionTests(unittest.TestCase):
    def run_collection(self, pages, **kwargs):
        client = FakeClient(pages)
        result = collect(lambda region: client, start=START, end=NOW,
                         retrieved_at=NOW, regions=("us-east-1",), **kwargs)
        return client, result

    def test_pages_anchor_duplicates_and_report(self):
        anchor = event(timestamp=START-timedelta(hours=1))
        client, (rows, report) = self.run_collection([
            dict(SpotPriceHistory=[event("0.50", START+timedelta(hours=12)), anchor], NextToken="page2"),
            dict(SpotPriceHistory=[anchor])])
        self.assertEqual(client.calls[1]["NextToken"], "page2")
        self.assertEqual(len(rows), 2)
        self.assertEqual(report["identicalDuplicatesRemoved"], 1)
        series = report["series"][0]
        self.assertTrue(series["hasStartAnchor"])
        self.assertEqual(series["effectiveCoverageDays"], 2)
        self.assertEqual(series["priceChangeCount"], 1)
        self.assertEqual(series["longestEventFreeHours"], 36)
        self.assertNotIn("availableUnits", rows[0])

    def test_conflicting_duplicates(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.run_collection([dict(SpotPriceHistory=[event(), event("0.3")])])

    def test_invalid_prices(self):
        for price in ["NaN", "Infinity", "-1", "invalid"]:
            with self.subTest(price=price), self.assertRaises(ValueError):
                self.run_collection([dict(SpotPriceHistory=[event(price)])])

    def test_repeated_token(self):
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.run_collection([dict(SpotPriceHistory=[], NextToken="x")]*2)

    def test_empty_response_is_missing_not_capacity_zero(self):
        _, (rows, report) = self.run_collection([dict(SpotPriceHistory=[])])
        self.assertEqual(rows, [])
        self.assertEqual(len(report["missingRegionInstances"]), 1)

    def test_missing_anchor_reports_uncovered_leading_period(self):
        _, (_, report) = self.run_collection([
            dict(SpotPriceHistory=[event(timestamp=START+timedelta(hours=6))])])
        self.assertEqual(report["series"][0]["uncoveredLeadingHours"], 6)
        self.assertFalse(report["series"][0]["hasStartAnchor"])

    def test_invalid_windows_and_naive_timestamps(self):
        with self.assertRaises(ValueError):
            utc("2026-10-24T00:00:00")
        for start, end in [(NOW, START), (NOW-timedelta(days=91), NOW),
                           (START, NOW+timedelta(hours=1))]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                collect(lambda r: None, start=start, end=end, retrieved_at=NOW)

    def test_unexpected_resource_and_future_event(self):
        wrong = event()
        wrong["InstanceType"] = "other"
        for row in [wrong, event(timestamp=NOW+timedelta(seconds=1))]:
            with self.assertRaises(ValueError):
                self.run_collection([dict(SpotPriceHistory=[row])])

    def test_save_checksum_and_no_overwrite(self):
        _, (rows, report) = self.run_collection([dict(SpotPriceHistory=[event()])])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/"dataset"
            save(output, rows, report)
            manifest = json.loads((output/"manifest.json").read_text())
            self.assertEqual(manifest["sha256"], hashlib.sha256((output/"prices.jsonl").read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                save(output, [], report)

    def test_collection_is_deterministic(self):
        pages = [dict(SpotPriceHistory=[event("0.5", NOW), event()])]
        self.assertEqual(self.run_collection(pages)[1], self.run_collection(pages)[1])


if __name__ == "__main__":
    unittest.main()
