"""Synthetic metadata verifies architecture and whole-instance normalization."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.forecasting.collect_expanded import validate_config
from app.forecasting.resource_metadata import _hardware, normalize_prices
from app.forecasting.hourly_data import reconstruct_hourly, slot_cost


@pytest.mark.parametrize("filename,count,previous", [
    ("hardware-collection-v2.json", 32, "expanded-collection.json"),
    ("hardware-collection-v3.json", 96, "hardware-collection-v2.json"),
])
def test_expanded_profile_is_valid_and_keeps_original_candidates(filename, count, previous):
    root = Path(__file__).resolve().parents[3]
    config = json.loads((root / "data" / filename).read_text())
    validate_config(config)
    assert len(config["instanceTypes"]) == count
    assert set(json.loads((root / "data" / previous).read_text())["instanceTypes"]) <= set(config["instanceTypes"])


def test_architecture_is_observed_metadata_and_remains_unknown_when_absent():
    raw = dict(InstanceType="test.cpu", VCpuInfo={"DefaultVCpus": 8}, MemoryInfo={"SizeInMiB": 32768})
    assert _hardware(raw)["supportedArchitectures"] is None
    raw["ProcessorInfo"] = dict(SupportedArchitectures=["arm64"], Manufacturer="TestVendor")
    mapped = _hardware(raw)
    assert mapped["supportedArchitectures"] == ["arm64"]
    assert mapped["processorManufacturer"] == "TestVendor"
    assert mapped["resourceUnitsPerInstance"] == 8
    for value in ([], ["arm64", "arm64"], "arm64", [""]):
        broken = deepcopy(raw)
        broken["ProcessorInfo"]["SupportedArchitectures"] = value
        with pytest.raises(ValueError, match="architectures"):
            _hardware(broken)


@pytest.mark.parametrize("gpu_count,vcpu_count", [(1, 4), (4, 48), (8, 192), (0, 8), (0, 32)])
def test_gpu_counts_and_cpu_sizes_preserve_whole_instance_billing(gpu_count, vcpu_count):
    raw = dict(InstanceType="test.instance", VCpuInfo={"DefaultVCpus": vcpu_count}, MemoryInfo={"SizeInMiB": 65536},
               ProcessorInfo={"SupportedArchitectures": ["x86_64"]})
    if gpu_count:
        raw["GpuInfo"] = {"Gpus": [dict(Manufacturer="SyntheticVendor", Name="TestGPU", Count=gpu_count,
                                        MemoryInfo={"SizeInMiB": 8192})]}
    metadata = dict(_hardware(raw), region="test-region", dataKind="OBSERVED",
                    retrievedAt="2026-01-02T00:00:00Z", source="synthetic metadata")
    price = dict(region="test-region", availabilityZone="test-zone", instanceType="test.instance",
                 productDescription="Linux/UNIX", timestamp="2026-01-01T00:00:00Z",
                 retrievedAt="2026-01-02T00:00:00Z", priceUsdPerInstanceHour="8.00",
                 dataKind="OBSERVED", source="synthetic test input")
    normalized = normalize_prices([price], [metadata])
    units = gpu_count or vcpu_count
    assert Decimal(normalized[0]["priceUsdPerUnitHour"]) * units == Decimal("8.00")
    hourly, _ = reconstruct_hourly(normalized, start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z")
    assert slot_cost(hourly[0], units) == Decimal("8.00")
    assert slot_cost(hourly[0], units * 2) == Decimal("16.00")
    if units > 1:
        with pytest.raises(ValueError):
            slot_cost(hourly[0], units - 1)
