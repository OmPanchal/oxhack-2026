# Milestone 4b: read-only AWS ingestion

The GPU catalog, regional/AZ offerings, Spot prices and frontend capabilities
endpoint are implemented. All 124 tests pass, including real SDK request-shape
validation using botocore Stubber. The SDK credential chain returns no credentials
on this machine, so authenticated live AWS access is not verified. Test responses
are synthetic; no real prices, benchmark results or cloud execution are claimed.

## Activation

From backend on Windows, after configuring an AWS profile/SSO session or IAM role:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,aws]'
$env:COMPUTE_MARKET_SOURCE = 'aws'
$env:COMPUTE_AWS_REGIONS = 'eu-west-1,eu-central-1'
# Optional, using an already configured profile:
# $env:AWS_PROFILE = 'your-profile'
# Optional instance-type restriction:
# $env:COMPUTE_AWS_INSTANCE_TYPES = 'g5.xlarge,p4d.24xlarge'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The adapter uses boto3's standard credential chain. It accepts no frontend keys
and exposes no credentials, raw SDK errors or signed requests. The only required
IAM actions are ec2:DescribeInstanceTypes, ec2:DescribeInstanceTypeOfferings and
ec2:DescribeSpotPriceHistory. An example read permission document, not applied by
this application:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeInstanceTypeOfferings",
      "ec2:DescribeSpotPriceHistory"
    ],
    "Resource": "*"
  }]
}
```

AWS mode requires explicit regions and overrides a leftover COMPUTE_MARKET_FILE.
JSON mode remains available with COMPUTE_MARKET_SOURCE=json. The default remains
unconfigured; the app does not silently connect to AWS or substitute fixtures.
No provisioning operation is implemented.

## Frontend handoff — Person 3

GET /api/capabilities returns provider, status, fetchedAtUtc, configuredRegions,
**allowedGpuTypes**, allowedRegions, offerings, capacityStatus and regional errors.
The exact dropdown field is allowedGpuTypes; values come from AWS metadata.

Each offering includes region, instanceType, gpuType, gpusPerInstance,
gpuMemoryMib, vCpuCount, memoryMib, cpuArchitectures and availabilityZones.
Use offerings to filter GPU/region combinations. The catalog includes
Spot-supported, regionally offered homogeneous full-GPU types; CPU-only,
mixed-GPU and explicitly fractional-GPU types are excluded. GPU names remain
exact AWS names, without guessed aliases. Offering a type does not confirm
current Spot availability.

GET /api/market/aws/spot returns detailed quotes by instance type and AZ, with
productDescription=Linux/UNIX, priceUsdPerInstanceHour, priceUsdPerGpuHour,
gpusPerInstance, effectiveAtUtc and observedAtUtc. allocationUnit is
WHOLE_INSTANCE. Dividing an eight-GPU instance's hourly cost by eight gives an
equivalent comparison rate, not permission to buy an eighth of the instance.

Both endpoints expose READY, PARTIAL, UNAVAILABLE or NOT_CONFIGURED status.
Clients must inspect status/errors, including when HTTP 200 has an empty list.
Regional failures include a sanitized SDK error code. Non-AWS capabilities can
be derived from already-ingested configured market rows.

### Shared contract change

MarketSnapshot.availableUnits is now **number | null**. Existing nonnegative
integers retain their behavior; null means unknown, not zero or unlimited.

Person 3 should change frontend/lib/types.ts to `availableUnits: number | null`
and display an unknown state. Frontend-owned files are unchanged. Person 1 should
preserve missing capacity or handle it with documented missing-value features;
do not convert it into observed zero capacity or a calibrated risk estimate.
OpenAPI reflects the backend change. No actual team agreement is claimed here.

## Pricing and scheduling behavior

All three AWS reads are paginated. The adapter discovers GPU metadata and AZ
offerings, then retrieves the latest Spot price for each offered instance/AZ.
The one-hour price-change query ends at the observation time and also receives
AWS's preceding effective price. An unchanged old price remains valid; future
timestamps, non-Linux products and non-offered zones are excluded.

Catalog caching defaults to one hour and quote caching to 60 seconds, with
shorter retry windows for failures. Quotes from an earlier hour are refreshed
before a new scheduling slot is stamped. SDK connections/reads use bounded
timeouts and retries. The live source requires the requested slot to match the
current UTC hour relative to the persisted origin; accelerated or historical
manual time returns AWS_LIVE_SLOT_MISMATCH rather than relabeling current prices.

The existing region/GPU schema cannot represent an exact AWS instance/AZ
allocation. For display/forecasting it receives an explicitly labeled PRICE INDEX:
the cheapest normalized quote for each region/GPU, with the selected instance,
AZ and bundle size in source. This index may change underlying SKU/AZ between
observations; it is not a fixed-instance price series. The detailed quote
endpoint preserves individual alternatives.

These price observations are OBSERVED, carbon is null and availableUnits is null.
The optimizer returns WAIT / CAPACITY_UNKNOWN and cannot allocate from those
rows, including at the last start slot. Immediate policies also exclude unknown
capacity. Replay requires explicit realized capacity, so price-only AWS history
cannot silently become a capacity benchmark. Any synthetic capacity must be
documented/labeled as such.

Exact AWS dispatch would additionally require whole-instance bundle constraints,
instance/AZ commitments and meaningful capacity evidence. It is not part of this
read-only integration; the project's MVP execution adapter remains local Docker.

## Verification and references

Tests cover discovery, pagination, per-instance/GPU unit conversion, preceding
effective prices, future/product/location filtering, cache rollover, partial
failures, sanitized errors, invalid prices/timestamps, environment configuration,
API serialization, unknown-capacity waiting and replay rejection. CI installs
the AWS extra so the offline SDK Stubber test runs. The existing Starlette/httpx
warning remains. No authenticated AWS request was possible without credentials.

Official AWS references:

- [Instance metadata](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html)
- [GPU model/count metadata](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_GpuDeviceInfo.html)
- [Regional/AZ offerings](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html)
- [Spot history and effective preceding prices](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html)
- [Instance/AZ pools and whole-instance prices](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-spot-instances.html)
- [Placement scores do not guarantee capacity](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html)
