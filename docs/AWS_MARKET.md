# Milestone 4b: read-only AWS ingestion

The GPU catalog, regional/AZ offerings, Spot prices and frontend capabilities
endpoint are implemented. Authenticated live reads were verified on 25 October
2026 through the actual Next.js API proxy: AWS reported READY, two offerings
(T4/A10G), five instance/AZ quotes, two OBSERVED regional price indices and twelve
persistence forecasts. Engine state had no source error. This is price-feed
verification, not cloud execution, capacity evidence or ML evaluation.

## Activation on macOS — current project

For normal use, run `./dev` from the repository root. First-time setup is
`./dev --setup`; reauthentication is `./dev --login`. See
[the startup guide](STARTUP.md). Manual commands follow for independent operation.

The new AWS experience uses project browser login, not the Identity Center setup
for a conventional organization. Profile `arbitr` has selected region `eu-north-1`.
The AWS Agent Toolkit was installed and its MCP entries configured to use that
profile. Toolkit installation is separate from running the application backend.

From `backend`, with your Python environment active:

```sh
python -m pip install -e '.[dev,aws]'
python -m pip install 'botocore[crt]'
aws login --region eu-north-1 --profile arbitr
aws sts get-caller-identity --profile arbitr
export AWS_PROFILE=arbitr
export COMPUTE_MARKET_SOURCE=aws
export COMPUTE_AWS_REGIONS=eu-north-1
export COMPUTE_AWS_INSTANCE_TYPES=g4dn.xlarge,g5.xlarge
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Stop any existing server using port 8000 before replacing it. The current `aws`
extra installs boto3 but not its optional browser-login dependency. Without
`botocore[crt]`, the backend reports `MissingDependencyException` even when CLI
login works. This dependency was installed and the successful live read repeated.

Open the frontend at http://127.0.0.1:3000, select Backend data, then Market.
`GET /api/capabilities` and `GET /api/market/aws/spot` expose READY/PARTIAL/error
status. The backend must be running for these local URLs to work.

Renew an expired session with `aws login --region eu-north-1 --profile arbitr`.
AWS documents 12-hour credentials with renewal for up to 90 days before browser
reauthorization. Do not copy keys, tokens or login URLs into source or chat.
The selected region can be checked in AWS Settings → View all projects → Overview
→ Additional Info → Region. Additional-region access must be checked before
expanding this project's live configuration; a comma-separated setting alone
does not grant regional permissions.

For Windows, activate the appropriate environment and set the same variables
with PowerShell's `$env:NAME = 'value'` syntax. Conventional AWS profiles, SSO
sessions and IAM roles can also be supplied through the normal credential chain.

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

## Frontend integration

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

The frontend now mirrors `availableUnits: number | null`, displays unknown
capacity and excludes it from current-opportunity ranking. OpenAPI reflects the
backend contract. Forecasting must preserve missing capacity or handle it with
documented missing-value features; do not convert it into observed zero capacity
or a calibrated risk estimate.

## Durable detailed history

FastAPI now archives freshly fetched exact instance/AZ quote batches in SQLite
`aws_quote_batches`, including response status/errors and archival receipt time.
Cached repeats are not new observations; refreshed flat prices are retained.
Existing scheduler indices remain separate and still upsert per region/GPU/hour.
See [PRICE_HISTORY.md](PRICE_HISTORY.md) for the read-only export command, gap
coverage, receipt-time cutoffs and outstanding model-target agreement. Earlier
cached quotes cannot be reconstructed retrospectively from regional indices.

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
allocation. With `./dev --ml`, live snapshots instead track the model-selected
fixed instance/AZ for each GPU key, explicitly named FIXED POOL in source; unknown
capacity still blocks allocation. The following minimum-index behavior applies
to persistence-only startup without the selected ML provider. For display/forecasting it receives an explicitly labeled PRICE INDEX:
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
warning remains in the earlier recorded suite. The original 124-test result was
a milestone snapshot, not a new test run. Current integration evidence and its
recorded checks are in [frontend/INTEGRATION.md](../frontend/INTEGRATION.md).
No tests were rerun for this documentation update.

Official AWS references:

- [New-experience project connection](https://docs.aws.amazon.com/accounts/latest/reference/connect-ai-coding-tool.html)
- [CLI browser sign-in](https://docs.aws.amazon.com/signin/latest/userguide/command-line-sign-in.html)

- [Instance metadata](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html)
- [GPU model/count metadata](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_GpuDeviceInfo.html)
- [Regional/AZ offerings](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html)
- [Spot history and effective preceding prices](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html)
- [Instance/AZ pools and whole-instance prices](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-spot-instances.html)
- [Placement scores do not guarantee capacity](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html)
