"""Synthetic AWS responses only: never real price/coverage evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest

from app.forecasting.collect_expanded import collect_expanded, validate_config
from app.forecasting.hourly_data import prepare_collection

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
CONFIG = dict(schemaVersion="expanded-spot-collection-config-v1", days=2,
              product="Linux/UNIX", regions=["r1", "r2"], instanceTypes=["test.gpu", "test.cpu"])


class Denied(Exception):
    response = {"Error": {"Code": "UnauthorizedOperation", "Message": "private SDK details"}}


class Client:
    def __init__(self, region, *, denied=False, empty=False, not_offered=False):
        self.region, self.denied, self.empty, self.not_offered = region, denied, empty, not_offered

    def describe_instance_type_offerings(self, **kwargs):
        if self.denied:
            raise Denied("private SDK details")
        instance = next(f["Values"][0] for f in kwargs["Filters"] if f["Name"] == "instance-type")
        return dict(InstanceTypeOfferings=[] if self.not_offered else [
            dict(InstanceType=instance, LocationType="region", Location=self.region)])

    def describe_instance_types(self, **kwargs):
        instance = kwargs["InstanceTypes"][0]
        raw = dict(InstanceType=instance, VCpuInfo={"DefaultVCpus": 4}, MemoryInfo={"SizeInMiB": 16384})
        if instance == "test.gpu":
            raw["GpuInfo"] = {"Gpus": [dict(Name="TestGPU", Manufacturer="TestVendor", Count=2,
                                            MemoryInfo={"SizeInMiB": 8192})]}
        return {"InstanceTypes": [raw]}

    def describe_spot_price_history(self, **kwargs):
        return {"SpotPriceHistory": [] if self.empty else [dict(InstanceType=kwargs["InstanceTypes"][0],
            ProductDescription="Linux/UNIX", AvailabilityZone=self.region+"a",
            Timestamp=kwargs["StartTime"], SpotPrice="0.40")]}


def test_full_export_is_checksummed_and_prepares_cpu_gpu_data(tmp_path):
    receipt = collect_expanded(lambda r: Client(r), CONFIG, tmp_path / "run", retrieved_at=NOW)
    assert receipt["status"] == "COMPLETE"
    assert receipt["collectedPairCount"] == 4
    assert receipt["startTime"] == "2026-10-23T12:00:00Z"
    for name, expected in receipt["combinedFilesSha256"].items():
        assert hashlib.sha256((tmp_path / "run" / name).read_bytes()).hexdigest() == expected
    quality = prepare_collection(tmp_path / "hourly", collection=tmp_path / "run/resource-metadata",
                                 start=receipt["startTime"], end=receipt["endTime"])
    assert quality["rowCount"] == 4 * 48
    rows = [json.loads(line) for line in (tmp_path / "hourly/hourly-prices.jsonl").read_text().splitlines()]
    assert {r["resourceType"] for r in rows} == {"CPU", "GPU"}
    assert {r["availabilityZone"] for r in rows} == {"r1a", "r2a"}
    assert all("availableUnits" not in r for r in rows)
    with pytest.raises(ValueError, match="fresh"):
        collect_expanded(lambda r: Client(r), CONFIG, tmp_path / "run", retrieved_at=NOW)


def test_denied_region_does_not_discard_other_regions_and_error_is_redacted(tmp_path):
    receipt = collect_expanded(lambda r: Client(r, denied=r == "r2"), CONFIG, tmp_path / "run", retrieved_at=NOW)
    assert receipt["status"] == "PARTIAL"
    assert receipt["collectedPairCount"] == 2
    assert len(receipt["excludedPairs"]) == 2
    assert all(p["errorCode"] == "UnauthorizedOperation" for p in receipt["excludedPairs"])
    assert "private SDK details" not in (tmp_path / "run/receipt.json").read_text()
    manifest = json.loads((tmp_path / "run/resource-metadata/manifest.json").read_text())
    assert manifest["scopeStatus"] == "PARTIAL"
    assert manifest["excludedPairs"] == receipt["excludedPairs"]


@pytest.mark.parametrize("mode,status", [("empty", "EMPTY_PRICE_HISTORY"), ("not_offered", "NOT_OFFERED")])
def test_missing_price_history_and_unsupported_hardware_are_explicit(tmp_path, mode, status):
    receipt = collect_expanded(lambda r: Client(r, **{mode: True}), CONFIG, tmp_path / "run", retrieved_at=NOW)
    assert receipt["status"] == "NO_DATA"
    assert receipt["collectedPairCount"] == 0
    assert all(p["status"] == status for p in receipt["pairs"])
    assert not (tmp_path / "run/resource-metadata").exists()


def test_invalid_configuration_and_times_do_not_create_output(tmp_path):
    for key, value in (("regions", ["../escape"]), ("days", 90), ("instanceTypes", ["x", "x"])):
        config = deepcopy(CONFIG)
        config[key] = value
        with pytest.raises(ValueError):
            validate_config(config)
    with pytest.raises(ValueError, match="align"):
        collect_expanded(lambda _: None, CONFIG, tmp_path / "bad", retrieved_at=NOW,
                         end="2026-10-25T11:30:00Z")
    assert not (tmp_path / "bad").exists()


def test_completed_shards_remain_if_local_storage_fails(tmp_path, monkeypatch):
    import app.forecasting.collect_expanded as module
    original = module.save
    calls = []

    def failing_save(output, rows, report):
        calls.append(output)
        if len(calls) == 2:
            raise OSError("Disk full")
        original(output, rows, report)

    monkeypatch.setattr(module, "save", failing_save)
    with pytest.raises(OSError):
        collect_expanded(lambda r: Client(r), CONFIG, tmp_path / "run", retrieved_at=NOW)
    assert (tmp_path / "run/shards/r1/test.gpu/spot-collection/prices.jsonl").exists()
    assert json.loads((tmp_path / "run/receipt.json").read_text())["status"] == "FILESYSTEM_ERROR"
