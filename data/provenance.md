# Data provenance — Person 1

`scenarios/demo.json` is a hand-authored, SIMULATED UI/contract fixture.
It contains no historical cloud observations, trained predictions, execution outcomes,
or benchmark results. Prices are illustrative USD per resource unit-hour.

Before adding real datasets record source URL, retrieval time (UTC), license,
resource/unit mapping, observation interval, missing-data handling, and chronological
train/validation/test cutoffs. Do not commit credentials or large raw datasets.

## Historical AWS Spot price collection

The collector is [collect_spot.py](../backend/app/forecasting/collect_spot.py).
It calls only the read-only EC2 `DescribeSpotPriceHistory` operation. Required IAM
permission: `ec2:DescribeSpotPriceHistory`. No instances are launched.

Source: [AWS API documentation](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html).
AWS data is subject to applicable provider terms; this repository does not assert
a redistribution license. Review usage terms before redistributing a collection.

### Run

Install `boto3` into your chosen Python environment and configure an authorized AWS
profile. It is an optional collection prerequisite, not a change to shared backend
dependencies. From `backend/`, run:

```sh
python3 -m app.forecasting.collect_spot \
  --end <FIXED-UTC-TIMESTAMP> \
  --days 89 \
  --profile <AWS-PROFILE> \
  --output ../data/raw/spot-collection-001
```

Replace the timestamp placeholder with a recent completed UTC hour in ISO 8601,
such as `YYYY-MM-DDTHH:00:00Z`. The start must remain within the preceding 90 days
when retrieval begins. The 89-day default leaves retrieval-time margin. Optional
`--regions` and `--instance-types` accept space-separated lists. Defaults are
`us-east-1 us-west-2 eu-central-1` and `g4dn.xlarge`; these are candidates, not a
claim that offerings or hardware mappings have already been verified. Omit
`--profile` to use the normal SDK credential chain. Never put credentials in data.

### Outputs and interpretation

- `prices.jsonl`: UTC price-change events with region, Availability Zone, instance
  type, product, retrieval timestamp, source, and exact decimal USD/instance-hour
  prices. These are provider observations, not forecasts or capacity measurements.
- `manifest.json`: request window, per-region page counts, completion flags,
  checksum, duplicates removed, empty region/instance combinations, and per-series
  effective coverage, leading uncovered hours, price changes, and longest
  event-free interval.
- Pre-window effective-price anchors are retained. No hourly interpolation,
  future backfill, regional aggregation, or GPU/vCPU conversion is performed.
- Event-free intervals do not prove ingestion gaps: prices can stay unchanged.
  Coverage assumes provider history is complete. Missing start anchors are
  reported, not filled with future values. Empty responses are not zero capacity.
- Conflicting duplicate events, invalid prices, out-of-window future events, and
  pagination loops fail collection. Identical duplicates are removed. An existing
  collection directory is never overwritten. Failed regional API calls abort
  before saving a dataset; infrastructure/filesystem failures during saving can
  leave a partial directory, so verify both files and their checksum before use.
- Hardware metadata/mapping, observed capacity, risk labels, and chronological
  split cutoffs are not supplied by this step. `splitCutoffs` remains null until
  evaluation partitions are defined.

The first user-supplied real export is recorded in
[Real collection 001](#real-collection-001--imported-24-october-2026) below. The
synthetic examples elsewhere remain explicitly simulated.

### Offline verification

From `backend/`, with the project's existing backend dependencies installed:

```sh
python3 -m unittest discover -s tests/forecasting -v
```

Tests use synthetic AWS responses solely to validate pagination, duplicates,
timestamps, prices, coverage reporting, determinism, checksums, and preservation
of existing collections. They are also discoverable by pytest when installed.

## Step 2: resource metadata and price conversion

Implementation: [resource_metadata.py](../backend/app/forecasting/resource_metadata.py).
Sources: [DescribeInstanceTypes](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html)
and [DescribeInstanceTypeOfferings](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html).
The caller needs `ec2:DescribeInstanceTypes` and `ec2:DescribeInstanceTypeOfferings`.
Both calls are read-only. As with price data, provider terms apply; no new
redistribution license is asserted here.

From `backend/`, with `boto3` and authorized credentials configured:

```sh
python3 -m app.forecasting.resource_metadata \
  --profile YOUR_PROFILE \
  --instance-types g4dn.xlarge m5.xlarge \
  --price-collection ../data/raw/spot-collection-001 \
  --output ../data/raw/resource-metadata-001
```

Omit `--price-collection` to collect metadata alone. If normalizing a non-default
price collection, pass the same `--regions` and `--instance-types` used in Step 1.
The optional Step 1 input checksum is verified before collection. Every input
price must map to exactly one `(region, instanceType)` metadata row; missing or
duplicate mappings fail rather than discarding prices. No GPU mapping is guessed
from an instance name.

The output contains `metadata.json`, `manifest.json`, and optionally
`normalized-prices.jsonl`. The manifest includes per-operation pagination counts,
unsupported requested combinations, source URLs, retrieval time, and file hashes.
Existing output directories are never overwritten. Verify all manifest hashes
before using an interrupted collection.

Metadata records retain vCPU count, RAM in MiB, GPU manufacturer/model/count,
GPU memory per device, resource type, conversion units, and supported regions
within the queried region set. The collector rejects mixed GPU models/memory,
partitioned GPUs, and unsupported accelerator mappings. Current regional
offerings do not prove historical support, zone-level offerings, free capacity,
or the probability of obtaining Spot instances.

Conversion allocates the full instance-hour price to its primary resource:

- GPU instances: divide by GPU count; retain the GPU manufacturer/model.
- CPU instances: divide by default vCPU count.
- Preserve original instance price, instance type, Availability Zone, timestamp,
  and price provenance in the normalized record.
- `resourceUnitsPerInstance` and `allocationGranularityUnits` record the whole
  instance allocation size. A per-unit price does not permit fractional rentals.
- Decimal division uses 28 significant digits, without currency quantization.
  Repeating fractions can round; the original instance price is authoritative
  when calculating a full-instance bill.

Normalized records are not API `MarketSnapshot` objects: they deliberately lack
`availableUnits`. They also retain instance identity and hardware detail that the
current API cannot fully express. Person 2 should select one compatible instance
pool per API resource key or coordinate a schema extension before mixing pools.
CPU counts and GPU names alone do not guarantee workload compatibility.

Real hardware metadata is now available in collection 001 below. Automated tests
still use synthetic provider responses and hand-calculated conversion examples.

## Step 3: reproducible simulation datasets

Implementation: [scenario_data.py](../backend/app/forecasting/scenario_data.py).
The checked-in [generated-v1 suite](scenarios/generated-v1/manifest.json) contains
five 24-hour scenarios with seed 42. All prices, capacities, jobs, and interruptions
are simulated. These are implementation fixtures, not trained-model evaluations
or benchmark results. Their fixed origin is a scenario clock, not a retrieval date.

From `backend/`, create a new suite without AWS access or additional dependencies:

```sh
python3 -m app.forecasting.scenario_data \
  --seed 42 --slots 24 --origin 2026-10-24T00:00:00Z \
  --output ../data/scenarios/my-run
```

The five cases are normal operation, price spike, capacity shortage, interruption,
and deadline pressure. All include arriving jobs, an impossible deadline, and an
unsupported GPU requirement. Baseline market/workload generation uses separate
local random streams. Changing scenario kind changes only that scenario's shock
or urgent arrival; there is no optimizer input or policy-dependent randomness.

Each file includes `schemaVersion`, seed, UTC origin, slot duration, separate
provenance for each data category, API-compatible jobs/market rows, and simulation
event annotations. `manifest.json` records file checksums. No risk probability is
inferred from these synthetic events.

See the [replay integration handoff](scenarios/README.md) for event timing,
capacity semantics, causal input helpers, and the observed/simulated data boundary.
The suite does not modify `demo.json`, which remains the shared frontend fixture.

Run all Person 1 tests with the earlier unittest command. With the project's
existing dev dependencies installed, use `python3 -m pytest tests/forecasting -q`;
this also validates generated jobs/market rows against the actual API schemas.
The stdlib-only run skips that schema test if Pydantic is absent.

## Step 4: optional operational evidence

[Operational evidence instructions](operational-observations.md) define the input
format, label meanings, provenance requirements, causal cutoff behavior, and
commands for the importer in
[operational_data.py](../backend/app/forecasting/operational_data.py).

No genuine capacity or interruption logs have been imported. The supplied
[example](examples/operational-observations.simulated.json) is hand-authored and
marked `SIMULATED`. An authorized real export is required to report empirical
cloud observations. The importer counts requests, outcomes, and observed runtime,
preserves censored/error cases, and keeps uncalibrated risk probabilities null.

The Step 4 importer and its tests use Pydantic from the existing backend dependency
set. To run every forecasting test, install the backend dev dependencies and use
`python3 -m pytest tests/forecasting -q`. Steps 1–3 collectors/generator themselves
remain usable as documented above.

## Milestone 1: hourly prices and forecasting handoff

The [forecasting contract](forecasting-contract.md) records implemented Person 1
defaults, example commands, clock/price definitions, and the pending team review.
The [forecast contract example](examples/forecast-contract.simulated.json) and
[hourly price-event example](examples/hourly-price-events.simulated.json) are
hand-authored `SIMULATED` fixtures with no cloud measurements or trained outputs.

The [prepared hourly example](examples/prepared-hourly-simulated/manifest.json)
contains eight hourly records from two simulated source series. Its manifest
records source/output hashes, missingness, duplicate counts, resource mappings,
and insufficient coverage for the real-data target. It is not a training result.

The [hourly preparation tool](../backend/app/forecasting/hourly_data.py) reads
checksummed normalized prices from Step 2, preserves instance/AZ identity, and
reconstructs slot-start prices without future backfill. It reports declared
ingestion gaps separately from unchanged prices and computes retrospective
hourly-average diagnostics in a distinct field. It adds no capacity observations.

Milestone 1's acquisition tooling has now been used in the user's AWS CloudShell
session, and the resulting real export has been imported locally. A local AWS
profile was not needed. Team confirmation of the documented integration defaults
is pending.

## Real collection 001 — imported 24 October 2026

The user supplied `spot-data.zip` after running the read-only collectors in AWS
CloudShell. That original run recorded the archive at `data/raw/spot-data.zip`.
It and the extracted/processed data are covered by the existing Git ignore rules
and are not present in this checkout. The historical import receipt at
`data/raw/spot-data-import-receipt.json` recorded archive and price
hashes and the checks performed. Checksums establish integrity relative to the
export manifests; they are not independent AWS signatures.

### Source and scope

- Prices: AWS `DescribeSpotPriceHistory`, retrieved at `2026-10-24T20:11:23.964184Z`.
- Hardware/offerings: AWS `DescribeInstanceTypes` and `DescribeInstanceTypeOfferings`,
  retrieved at `2026-10-24T20:11:46.369488Z`.
- Requested interval: `[2026-07-27T00:00:00Z, 2026-10-24T00:00:00Z)`, 89 days.
- Region: Stockholm (`eu-north-1`), with `eu-north-1a`, `eu-north-1b`, and `eu-north-1c`.
- Instance/product: `g4dn.xlarge`, `Linux/UNIX`.
- Hardware: one NVIDIA T4 GPU with 16,384 MiB GPU memory, four vCPUs, and
  16,384 MiB instance RAM. Prices per instance-hour equal prices per GPU-hour
  because there is one GPU per instance. Allocation remains a whole instance.
- Usage terms: AWS provider terms apply; no independent redistribution license
  is asserted by this repository.

The original plan targeted three regions. This export covers one region and
three zones; those are not interchangeable claims. Current account restrictions
prevented the original multi-region collection. Regional expansion remains open.

### Validation and preparation

- Raw price records: 1,085. Normalized records: 1,085. Hardware records: one.
- ZIP integrity, all manifest hashes, unique event identities, pagination
  declarations, hardware mapping, and timestamps passed checks.
- Recomputing normalized prices from raw events and metadata exactly matches
  the exported normalized records.
- Raw price SHA-256: `566d7d5d2a30e63908cb61e266be5c6c9490e9a0e959bf4f042dba3c6081c349`.
- Archive SHA-256: `ab04ae656b5ef7be673fcfce40ca999e520183a644a223775cb97dbbcf2f7d4f`.

The historical prepared dataset path is
`data/processed/hourly-prices-001/hourly-prices.jsonl`, with its quality report
and hashes in `data/processed/hourly-prices-001/manifest.json` (also ignored and
not included in this checkout).
It contains 6,408 hourly rows across the three source series, including 6,407
known start prices and one missing start price.

`eu-north-1a` has no effective-price anchor at the start of the requested interval;
its first known event is `2026-07-27T01:00:00Z`. Slot 0 is left null, with status
`NO_PAST_PRICE`, instead of using a future observation to fill it. The other two
zones have 2,136 known hours each; zone `1a` has 2,135. All three exceed 60 usable
days individually. No collection gaps were declared; as elsewhere, completeness
of the provider's price-change history is an assumption.

No capacity counts, interruption labels, workloads, model predictions, or benchmark
results are present in this real price dataset. Hourly-average diagnostics remain
retrospective. Milestone 2 now uses common chronological boundaries across the zones, recorded
in the training artifacts and below.

## Milestone 2: first chronological model evaluation

Training consumed the checksummed `hourly-prices-001` dataset with SHA-256
`b286afcaaf18c76736c959f14b46617442bb2ebf44cddb30c45abc12d58669f8`.
No new AWS calls were made. The three AZ source series remain distinct, and all
price labels are observed. Feature inputs exclude retrospective hourly averages
and capacity assumptions.

Common UTC partitions, all relative to `2026-07-27T00:00:00Z`, are:

- Training `[0, 1281)`; 22,512 samples after warmup and six-hour boundary purging.
- Validation `[1281, 1602)`; 5,670 samples used for model selection.
- Calibration `[1602, 1815)`; reserved, unused by this training run.
- Final test `[1815, 2136)`; reserved, not scored by this training run.

The feature encoder fits training examples only. The selected model is available
for historical deployment from slot 1602 because validation outcomes were used
to select it. Earlier inference uses explicitly labeled persistence fallback.

Three LightGBM candidates were predefined before validation. Seed 42 selected
`small-l1`, artifact `lightgbm-delta-v1-3310f6a9f1d7`. Validation MAE is
`0.0006831376269117395` USD/GPU-hour against persistence's
`0.0006293827160493826`, an improvement of `-8.540894036584763%`.
The recommendation is `NAIVE`; no predictive benefit or scheduling savings is
claimed. Model-selection performance is not final held-out test performance.

The [tracked report](milestone2-validation.json) preserves candidate and group
results; [Milestone 2 instructions](milestone2.md) explain reproduction and
integration. Full weights and per-sample predictions remain in ignored
`models/price-model-001/` and `data/processed/forecast-run-001/`. The package
versions, feature-code hash, dataset hash, and model/encoder hashes are stored in
the artifact. No forecast API response schema changed.

## Controlled forecasting improvements

The [experiment design](forecast-experiment-design.json) and
[complete measured results](forecast-experiment-results.json) record 40 variants
on the same checksummed observed dataset, seed 42. No additional data was
collected. Eight setups cross 24-/168-hour features, pooled/separate-horizon
models, and original/stronger regularization; correction weights produce the
40 variants. All share the 168-hour eligibility rule and identical evaluation
cohorts. Three earlier chronological folds select the winner before its later
development comparison. Protected calibration/test rows are excluded before
example building and remain unscored.

The frozen winner improved earlier MAE 3.3207% but lost the later check by
0.0383%; recommendation stays `NAIVE`. Extended-history/separate-horizon/strong
regularization with a 50% correction improved earlier aggregate MAE 3.1683% and
later MAE 1.8885%, an exploratory candidate rather than a promoted winner.
The original later validation period had already been inspected: these are
development results, not final-test or scheduling-savings claims. See
[the experiment notes](forecast-experiments.md) for limitations and reproduction.
The ignored local bundle is `models/price-experiment-001/`; full predictions and
report are in `data/processed/forecast-experiments-001/`. All 40 outcomes,
including failures, are retained in the tracked results.

## Alternative model families

The [alternative-model design](alternative-model-design.json) compares Ridge,
Extra Trees, histogram gradient boosting and two-stage price-change prediction
with the existing extended-history LightGBM reference. Fourteen prespecified
variants use the same observed dataset, seed 42, eligibility and chronological
windows as the earlier experiment. No AWS calls or new data were needed.

The frozen earlier-window selection remains the half-correction LightGBM
reference: 3.1683% earlier aggregate and 1.8885% later development MAE improvement.
Two-stage prediction with half correction and a 0.5 gate improved later MAE
2.0375% but won only one earlier window. Histogram gradient boosting with half
correction improved earlier MAE 0.9566% and later MAE 0.6110%, winning two earlier
windows. These are development results from repeatedly inspected periods, not
independent confirmation or final-test evidence. Calibration and test remain
unused. The price-change classifier uses genuine observed price-change labels
and supplies no interruption-risk estimate.

See [all measured results](alternative-model-results.json) and
[reproduction/limitations](alternative-models.md). The ignored local run is
`data/processed/alternative-models-001/`. The default service was not changed;
there is no new claim of scheduling savings or final predictive superiority.

## Automatic live model inputs — 25 October 2026

`model_history_fetches` stores complete paginated EC2 Spot price-event responses
for each selected instance/AZ/product, request window, source URL and receipt time.
`model_price_history` stores the effective price at each required historical UTC
boundary, original whole-instance USD/hour, normalization by verified GPU count,
and actual retrieval time. Unchanged prices use the last preceding provider event;
missing anchors are not backfilled from a later value. Data is OBSERVED, capacity
is unknown. Values retrieved today are available today only, never to earlier
replay decisions. The live provider alone reads this store.

Live verification populated 168 prior hours for g4dn.xlarge / eu-north-1a (T4)
and g5.xlarge / eu-north-1b (A10G), both in eu-north-1. No training data, clean
held-out evaluation, capacity labels or cloud execution was created. See
[automatic history](../docs/AUTOMATIC_HISTORY.md).
