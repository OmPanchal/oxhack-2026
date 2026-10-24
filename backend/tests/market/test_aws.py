from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from app.engine.forecast_bridge import EngineUnavailable
from app.main import create_app
from app.market.aws import AwsSpotMarket

NOW = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)


def hardware(name="g5.xlarge", gpu="A10G", count=1, **extra):
    return {"InstanceType": name, "SupportedUsageClasses": ["spot", "on-demand"],
            "GpuInfo": {"Gpus": [{"Name": gpu, "Manufacturer": "NVIDIA", "Count": count,
                                   "MemoryInfo": {"SizeInMiB": 24576}, **extra}]},
            "VCpuInfo": {"DefaultVCpus": 4}, "MemoryInfo": {"SizeInMiB": 16384},
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]}}


def price(instance="g5.xlarge", value="1.60", at=None, **extra):
    return {"InstanceType": instance, "SpotPrice": value, "Timestamp": at or NOW - timedelta(minutes=10),
            "AvailabilityZone": "eu-west-1a", "ProductDescription": "Linux/UNIX", **extra}


class FakeEc2:
    """Only read methods exist; unexpected AWS writes cannot pass these tests."""
    def __init__(self):
        self.calls = []
        self.types = [hardware(), hardware("p4d.24xlarge", "A100", 8),
                      {"InstanceType": "m5.large", "SupportedUsageClasses": ["spot"]},
                      hardware("g6f.large", "L4", 1, GpuPartitionSize=.5)]
        self.quotes = [price(), price("p4d.24xlarge", "4.00"),
                       price(value="9", at=NOW - timedelta(days=1)),
                       price(value=".01", at=NOW + timedelta(hours=1)),
                       price(value=".01", ProductDescription="Windows"),
                       price(value=".01", AvailabilityZone="not-offered")]

    def describe_instance_types(self, **params):
        self.calls.append(("types", params))
        return {"InstanceTypes": self.types[2:]} if params.get("NextToken") else {
            "InstanceTypes": self.types[:2], "NextToken": "types-next"}

    def describe_instance_type_offerings(self, **params):
        self.calls.append(("offerings", params))
        if params.get("NextToken"):
            return {"InstanceTypeOfferings": [{"InstanceType": "p4d.24xlarge", "Location": "eu-west-1a"}]}
        return {"InstanceTypeOfferings": [{"InstanceType": "g5.xlarge", "Location": "eu-west-1a"}], "NextToken": "offer-next"}

    def describe_spot_price_history(self, **params):
        self.calls.append(("prices", params))
        return {"SpotPriceHistory": self.quotes[1:]} if params.get("NextToken") else {
            "SpotPriceHistory": self.quotes[:1], "NextToken": "prices-next"}


def source(client=None, **changes):
    client = client or FakeEc2()
    return AwsSpotMarket(["eu-west-1"], client_factory=lambda region: client, clock=lambda: NOW, **changes)


def test_catalog_gpu_names_are_discovered_and_paginated():
    client = FakeEc2()
    catalog = source(client).capabilities()
    assert catalog.status == "READY"
    assert catalog.allowed_gpu_types == ["A100", "A10G"]
    assert catalog.allowed_regions == ["eu-west-1"]
    assert [row.gpus_per_instance for row in catalog.offerings] == [1, 8]
    assert catalog.offerings[0].cpu_architectures == ["x86_64"]
    assert len([name for name, _ in client.calls if name == "types"]) == 2
    assert len([name for name, _ in client.calls if name == "offerings"]) == 2
    assert catalog.capacity_status == "UNKNOWN"


def test_spot_prices_keep_whole_instance_cost_and_normalize_gpu_units():
    client = FakeEc2()
    response = source(client).prices()
    assert response.status == "READY"
    assert len(response.quotes) == 2
    one, eight = response.quotes
    assert one.price_usd_per_instance_hour == one.price_usd_per_gpu_hour == 1.6
    assert eight.price_usd_per_instance_hour == 4
    assert eight.price_usd_per_gpu_hour == .5
    assert eight.gpus_per_instance == 8
    assert eight.allocation_unit == "WHOLE_INSTANCE"
    assert all(row.available_units is None for row in response.quotes)
    assert one.effective_at_utc == NOW - timedelta(minutes=10)
    params = next(params for name, params in client.calls if name == "prices")
    assert params["ProductDescriptions"] == ["Linux/UNIX"]
    assert params["EndTime"] == NOW
    assert params["StartTime"] == NOW - timedelta(hours=1)


def test_old_effective_price_is_retained_when_there_is_no_recent_change():
    client = FakeEc2()
    client.quotes = [price(at=NOW - timedelta(days=3))]
    quotes = source(client).prices().quotes
    assert len(quotes) == 1
    assert quotes[0].effective_at_utc == NOW - timedelta(days=3)


def test_instance_allowlist_and_nonspot_hardware_are_filtered():
    client = FakeEc2()
    client.types[0]["SupportedUsageClasses"] = ["on-demand"]
    assert source(client).capabilities().allowed_gpu_types == ["A100"]
    catalog = source(instance_types=["g5.xlarge"]).capabilities()
    assert catalog.allowed_gpu_types == ["A10G"]


def test_api_exposes_catalog_quotes_and_safe_unknown_capacity(tmp_path):
    aws = source()
    app = create_app(tmp_path / "api.sqlite3", aws_market=aws, clock=lambda: NOW)
    client = TestClient(app)
    catalog = client.get("/api/capabilities").json()
    assert catalog["allowedGpuTypes"] == ["A100", "A10G"]
    assert catalog["offerings"][1]["gpusPerInstance"] == 8
    assert client.get("/api/market/aws/spot").json()["quotes"][1]["priceUsdPerGpuHour"] == .5
    response = client.post("/api/jobs", json={"id": "a", "name": "a", "arrivalSlot": 0,
        "durationSlots": 1, "deadlineSlot": 1, "resourceType": "GPU", "gpuType": "A100",
        "resourceUnits": 1, "allowedRegions": ["eu-west-1"]})
    assert response.status_code == 201
    response = client.post("/api/optimize", json={"currentSlot": 0, "executionMode": "SIMULATED"})
    assert response.status_code == 200
    assert response.json()[0]["action"] == "WAIT"
    assert response.json()[0]["reasonCode"] == "CAPACITY_UNKNOWN"
    assert client.get("/api/jobs").json()[0]["status"] == "PENDING"
    rows = client.get("/api/market").json()
    assert all(row["availableUnits"] is None and row["dataKind"] == "OBSERVED" for row in rows)
    assert all("PRICE INDEX" in row["source"] for row in rows)
    assert len(client.get("/api/forecasts").json()) == 12
    future = client.post("/api/optimize", json={"currentSlot": 1})
    assert future.status_code == 503
    assert future.json()["detail"]["code"] == "AWS_LIVE_SLOT_MISMATCH"
    assert client.get("/api/engine/state").json()["currentSlot"] == 0


def test_cache_returns_copies_and_refreshes_prices_at_hour_boundary():
    client = FakeEc2()
    now = [NOW.replace(minute=59, second=50)]
    aws = AwsSpotMarket(["eu-west-1"], client_factory=lambda _: client, clock=lambda: now[0])
    catalog = aws.capabilities()
    catalog.allowed_gpu_types.clear()
    assert aws.capabilities().allowed_gpu_types == ["A100", "A10G"]
    before = len(client.calls)
    aws.capabilities()
    assert len(client.calls) == before
    origin = NOW.replace(minute=0)
    aws.poll_with_origin(0, origin)
    count = len([call for call in client.calls if call[0] == "prices"])
    now[0] += timedelta(seconds=15)
    rows = aws.poll_with_origin(1, origin)
    assert all(row.slot == 1 for row in rows)
    assert len([call for call in client.calls if call[0] == "prices"]) == count + 2


def test_errors_are_partial_or_unavailable_and_sanitized():
    class Denied(Exception):
        response = {"Error": {"Code": "UnauthorizedOperation", "Message": "SECRET"}}
    def factory(region):
        if region == "denied":
            raise Denied("SECRET signed request")
        return FakeEc2()
    aws = AwsSpotMarket(["eu-west-1", "denied"], client_factory=factory, clock=lambda: NOW)
    assert aws.capabilities().status == "PARTIAL"
    response = aws.prices()
    assert response.status == "PARTIAL"
    assert response.errors[0].code == "UnauthorizedOperation"
    assert "SECRET" not in response.model_dump_json()
    denied = AwsSpotMarket(["denied"], client_factory=factory, clock=lambda: NOW)
    assert denied.capabilities().status == "UNAVAILABLE"
    with pytest.raises(EngineUnavailable, match="AWS reads failed"):
        denied.poll_with_origin(0, NOW.replace(minute=0))


@pytest.mark.parametrize("bad_price", ["-1", "NaN"])
def test_invalid_prices_do_not_become_quotes(bad_price):
    client = FakeEc2()
    client.quotes = [price(value=bad_price)]
    response = source(client).prices()
    assert response.status == "UNAVAILABLE"
    assert response.quotes == []


def test_bad_pagination_and_timestamp_are_reported():
    client = FakeEc2()
    client.describe_instance_types = lambda **kwargs: {"InstanceTypes": [], "NextToken": "again"}
    assert source(client).capabilities().status == "UNAVAILABLE"
    client = FakeEc2()
    client.quotes = [price(at=NOW.replace(tzinfo=None))]
    assert source(client).prices().status == "UNAVAILABLE"


def test_unconfigured_endpoints_and_environment_selection(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / "none.sqlite3"))
    assert client.get("/api/capabilities").json()["status"] == "NOT_CONFIGURED"
    assert client.get("/api/market/aws/spot").json()["status"] == "NOT_CONFIGURED"
    monkeypatch.setenv("COMPUTE_MARKET_SOURCE", "aws")
    with pytest.raises(ValueError, match="at least one AWS region"):
        create_app(tmp_path / "missing-region.sqlite3")
    monkeypatch.setenv("COMPUTE_AWS_REGIONS", "eu-west-1,eu-central-1")
    app = create_app(tmp_path / "configured.sqlite3", clock=lambda: NOW)
    assert isinstance(app.state.engine.market_source, AwsSpotMarket)
    assert app.state.engine.market_source.regions == ["eu-central-1", "eu-west-1"]


def test_real_boto_sdk_parameters_with_official_stubber():
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import Stubber
    client = boto3.client("ec2", region_name="eu-west-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    with Stubber(client) as stub:
        stub.add_response("describe_instance_types", {"InstanceTypes": [hardware()]},
                          {"Filters": [{"Name": "supported-usage-class", "Values": ["spot"]}]})
        stub.add_response("describe_instance_type_offerings", {"InstanceTypeOfferings": [
            {"InstanceType": "g5.xlarge", "Location": "eu-west-1a", "LocationType": "availability-zone"}]},
            {"LocationType": "availability-zone", "Filters": [{"Name": "instance-type", "Values": ["g5.xlarge"]}]})
        stub.add_response("describe_spot_price_history", {"SpotPriceHistory": [price()]},
            {"InstanceTypes": ["g5.xlarge"], "ProductDescriptions": ["Linux/UNIX"],
             "StartTime": NOW - timedelta(hours=1), "EndTime": NOW})
        assert source(client).prices().quotes[0].price_usd_per_instance_hour == 1.6
        stub.assert_no_pending_responses()
