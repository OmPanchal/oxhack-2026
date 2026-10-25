"""Synthetic provider responses; no claimed AWS hardware observations."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.forecasting.resource_metadata import collect_metadata, normalize_prices, save_metadata

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def hardware(instance="test.gpu", gpu=True):
    raw = {"InstanceType": instance, "VCpuInfo": {"DefaultVCpus": 4},
           "MemoryInfo": {"SizeInMiB": 16384}}
    if gpu:
        raw["GpuInfo"] = {"Gpus": [{"Name": "TestGPU", "Manufacturer": "TestVendor", "Count": 2,
                                    "MemoryInfo": {"SizeInMiB": 8192}}]}
    return raw


class Client:
    def __init__(self, region="r1", offering_pages=None, type_pages=None):
        self.calls = []
        self.offerings = iter(offering_pages if offering_pages is not None else [
            {"InstanceTypeOfferings": [{"InstanceType": i, "LocationType": "region", "Location": region}
                                       for i in ("test.cpu", "test.gpu")]}])
        self.types = iter(type_pages if type_pages is not None else [
            {"InstanceTypes": [hardware(), hardware("test.cpu", False)]}])

    def describe_instance_type_offerings(self, **kwargs):
        self.calls.append(("offerings", kwargs))
        return next(self.offerings)

    def describe_instance_types(self, **kwargs):
        self.calls.append(("types", kwargs))
        return next(self.types)


def collect(client=None, regions=("r1",)):
    return collect_metadata(lambda r: client or Client(r), regions=regions,
                            instance_types=("test.gpu", "test.cpu"), retrieved_at=NOW)


def price(instance="test.gpu", amount="1.20"):
    return dict(region="r1", instanceType=instance, availabilityZone="r1a",
                timestamp="2026-10-23T00:00:00Z", retrievedAt="2026-10-24T00:00:00Z",
                productDescription="Linux/UNIX", dataKind="OBSERVED",
                priceUsdPerInstanceHour=amount)


class MetadataTests(unittest.TestCase):
    def test_gpu_and_cpu_fields_and_supported_regions(self):
        rows, report = collect(regions=("r1", "r2"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(report["notOffered"], [])
        gpu = next(r for r in rows if r["instanceType"] == "test.gpu")
        self.assertEqual((gpu["gpuType"], gpu["gpuCount"], gpu["gpuMemoryMiBPerDevice"]),
                         ("TestVendor TestGPU", 2, 8192))
        self.assertEqual(gpu["supportedRegions"], ["r1", "r2"])
        cpu = next(r for r in rows if r["instanceType"] == "test.cpu")
        self.assertEqual((cpu["vcpuCount"], cpu["memoryMiB"], cpu["unit"]), (4, 16384, "vCPU-hour"))

    def test_hand_calculated_price_conversions_and_cost_roundtrip(self):
        rows, _ = collect()
        prices = [price(), price("test.cpu", "0.40")]
        original = deepcopy(prices)
        normalized = normalize_prices(prices, rows)
        self.assertEqual([Decimal(r["priceUsdPerUnitHour"]) for r in normalized],
                         [Decimal("0.60"), Decimal("0.10")])
        for row in normalized:
            self.assertEqual(Decimal(row["priceUsdPerUnitHour"]) * row["resourceUnitsPerInstance"],
                             Decimal(row["priceUsdPerInstanceHour"]))
            self.assertEqual(row["allocationGranularityUnits"], row["resourceUnitsPerInstance"])
            self.assertEqual(row["availabilityZone"], "r1a")
            self.assertNotIn("availableUnits", row)
        self.assertEqual(prices, original)

    def test_unmapped_and_duplicate_metadata_fail(self):
        rows, _ = collect()
        with self.assertRaisesRegex(ValueError, "Unmapped"):
            normalize_prices([price("missing")], rows)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            normalize_prices([price()], rows + [rows[0]])

    def test_invalid_conversion_and_mixed_provenance(self):
        rows, _ = collect()
        for amount in ("NaN", "Infinity", "-1", "not-a-price"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                normalize_prices([price(amount=amount)], rows)
        broken = deepcopy(rows)
        broken[0]["resourceUnitsPerInstance"] = 0
        with self.assertRaises(ValueError):
            normalize_prices([price()], broken)
        with self.assertRaisesRegex(ValueError, "provenance"):
            normalize_prices([dict(price(), dataKind="SIMULATED")], rows)

    def test_both_apis_paginate(self):
        offering = {"InstanceType": "test.gpu", "LocationType": "region", "Location": "r1"}
        client = Client(offering_pages=[{"InstanceTypeOfferings": [], "NextToken": "o2"},
                                       {"InstanceTypeOfferings": [offering]}],
                        type_pages=[{"InstanceTypes": [], "NextToken": "t2"},
                                    {"InstanceTypes": [hardware()]}])
        rows, report = collect(client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.calls[1][1]["NextToken"], "o2")
        self.assertEqual(client.calls[3][1]["NextToken"], "t2")
        self.assertEqual(report["requests"][0]["hardwarePages"], 2)
        self.assertEqual(report["notOffered"], [{"region": "r1", "instanceType": "test.cpu"}])

    def test_empty_offerings_do_not_invent_hardware_or_capacity(self):
        client = Client(offering_pages=[{"InstanceTypeOfferings": []}])
        rows, report = collect(client)
        self.assertEqual(rows, [])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(report["notOffered"]), 2)

    def test_pagination_loop_and_missing_hardware(self):
        with self.assertRaisesRegex(ValueError, "pagination"):
            collect(Client(offering_pages=[{"InstanceTypeOfferings": [], "NextToken": "x"}]*2))
        with self.assertRaisesRegex(ValueError, "no hardware"):
            collect(Client(type_pages=[{"InstanceTypes": []}]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            collect(Client(type_pages=[{"InstanceTypes": [hardware(), hardware()]}]))

    def test_unsupported_or_inconsistent_hardware_rejected(self):
        bad_rows = []
        mixed = hardware()
        mixed["GpuInfo"]["Gpus"].append(dict(mixed["GpuInfo"]["Gpus"][0], Name="DifferentGPU"))
        bad_rows.append(mixed)
        fractional = hardware()
        fractional["GpuInfo"]["Gpus"][0]["GpuPartitionSize"] = 0.5
        bad_rows.append(fractional)
        empty = hardware()
        empty["GpuInfo"]["Gpus"] = []
        bad_rows.append(empty)
        bad_rows.append(dict(hardware(), NeuronInfo={"NeuronDevices": [{}]}))
        for bad in bad_rows:
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                collect(Client(type_pages=[{"InstanceTypes": [bad]}]))

    def test_saved_files_hashes_and_no_overwrite(self):
        rows, report = collect()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "metadata"
            save_metadata(output, rows, report, normalize_prices([price()], rows))
            manifest = json.loads((output / "manifest.json").read_text())
            for name, expected in manifest["sha256"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), expected)
            with self.assertRaises(FileExistsError):
                save_metadata(output, rows, report)


if __name__ == "__main__":
    unittest.main()
