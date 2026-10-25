# Person 1 selected-model serving handoff

## Implemented routing — 25 October 2026

The backend's existing `ModelLoader` now loads the fixed v2 router from
[forecast-serving.json](forecast-serving.json). Its selected LightGBM models use
31 leaves, 200 rounds, an L1/MAE objective and separate CPU/GPU residual models.
The public forecast protocol and API schemas are unchanged.

- Stockholm CPU: `models/public-region-001/CPU-model.json`.
- Stockholm GPU: `models/error-reduction-001/GPU-model.json`.
- CPU and GPU in us-east-1, us-west-2, eu-west-1, eu-west-2 and eu-central-1:
  the corresponding model in `models/public-region-001/`.
- Unknown keys, unsupported hardware/source pools, incomplete history and zero
  current prices: explicit persistence fallback. Stockholm B200 is unsupported.

The configuration selects 42 fixed source pools: one CPU source and one source
per available GPU type in each region. This does not expose all 353 training
pools or all 79 instance configurations simultaneously. Existing Stockholm source
choices are preserved. Added CPU sources use m5.xlarge; added GPU choices use
fixed instance types and lexically first recorded global AZ IDs, never hindsight
cheapest prices. Supported types vary by region; see the full config/status.

## Start and inspect

Run `./dev --setup --ml` on first setup, then `./dev --ml`. Direct FastAPI startup
uses `COMPUTE_ENABLE_ML=1` to enable the engine ML provider. Plain startup retains
persistence. Select ML in the engine controls. No retraining or cloud provisioning
is required. Existing read-only AWS history collection remains unchanged.

```sh
curl -sS http://localhost:8000/api/models/status
curl -sS -X POST http://localhost:8000/api/forecasts -H 'Content-Type: application/json' --data-binary @data/examples/ml-forecast-request.simulated.json
curl -sS http://localhost:8000/api/forecasts
```

The packaged example uses explicitly SIMULATED input at native slot 2200; it is
an inference example, not measured accuracy or execution. Explicit POST inference
is isolated and never replaces official engine forecasts. GET returns persisted
engine forecasts, initially empty. `forecastMode=NAIVE` remains available.

The pulled backend's SQLite state, live history backfill, clock/GPU-name adapter,
rolling scheduler, replay isolation and execution modules are preserved. Replay
never receives retrospective live-history backfill. Risk probabilities and price
intervals remain null because calibrated evidence is unavailable.

## Clock and leakage prevention

Native UTC origin: **2026-07-28 00:00 UTC**. Explicit POST slots use this origin.
The engine adapter maps its own UTC origin to this clock. Training labels stop
before slot 1257. The new choice of routes used existing October diagnostics
through slot 2135; therefore v2 inference is available only from **slot 2136,
2026-10-25 00:00 UTC**. Earlier requests/replay fall back to persistence. Moving a
SIMULATED test fixture beyond this cutoff does not create new observed outcomes.
The original v1 config remains in [forecast-serving-stockholm-v1.json](forecast-serving-stockholm-v1.json)
for reproducibility of the previous selection and its earlier availability date.

Every inference needs 168 prior consecutive hourly prices plus the current price
from the configured source, with its original resource units. Future, stale,
conflicting and forecast-as-history inputs are rejected. Models are frozen; no
online fitting or adaptive blending is performed.

## Live source limitations

Stockholm selections use account-specific AZ names, matching the existing live
GPU feed. Public regional selections use **global AZ IDs**, such as `use1-az1`.
These are not interchangeable with names such as `us-east-1a`. The fixed-pool
reader now verifies global IDs with AWS `DescribeAvailabilityZones`, then queries
and validates prices using the returned project-specific zone name. It keeps the
model's global source identity in inference history and records the provider AZ
name in provenance. Missing/denied mappings are never guessed.

With ML enabled, selected CPU pools are also read using verified EC2 vCPU counts.
Instance-hour prices are divided by that count; CPU requests and persisted history
use per-vCPU-hour prices. The existing GPU quote API remains unchanged. Missing
CPU/GPU backfill is retrieved and persisted automatically, using only the actual
live hour. The fixed reader caches successful reads and backs off failed reads.
`/api/models/status` reports per-pool read errors; Market shows these errors.

Reads are limited to the AWS regions explicitly configured by the operator.
`./dev --ml` retains its Stockholm default and now includes all configured model
GPU instance types in that region, rather than limiting ML to T4/A10G. Additional
model regions do not grant project permissions. Failed regional reads remain
visible; supported pools can continue. No paid resources are provisioned.
Live capacity stays unknown and the optimiser cannot dispatch against it.

The **All model regions · CPU/GPU · simulated** replay preset exercises all 42
configured pools, independently of AWS access. It includes 168 explicitly
SIMULATED prior hours; workload arrivals occur only after that warmup. It starts
at slot 168, exposes no later observations, and uses a post-selection UTC origin.
All four strategies share the same prices/capacity and retain separate state.
This is an integration fixture, not historical accuracy or measured savings.

## Artifacts, status and evaluation

Both bundles' four native text/metadata files are checksum-verified against their
original receipts, and inference verifies the feature implementation hash. The
selected files are exempted from Git ignore so fresh checkouts can load them.
Original experiment receipts retain their historical experimental status; the
serving config is the record of selection. Selection evidence files also have
pinned checksums. No pickle loading is used.

`GET /api/models/status` exposes the twelve resource/region routes, per-route
weight/dataset hashes, global/account AZ identity kind, availability cutoff and
selection-evidence references. The compatibility `models` summary describes
Stockholm; `routes` is authoritative for other regions. There is no combined
held-out evaluation object for this mixed router. `GET /api/models/metrics`
correctly remains UNAVAILABLE without a genuinely disjoint metrics report.

Previously reported comparisons motivating this selection are **exploratory**:
Stockholm CPU MAE was 11.40% below persistence with the augmented model; original
Stockholm GPU MAE was 10.70% below persistence. Added-region September diagnostics
were 4.00% lower for CPU and 6.52% lower for GPU. These aggregate research scores
cover their original full cohorts, not just the 42 configured serving sources.
They are not a new test of the router or guarantees of future gains. See
[public-region comparison](public-region-comparison.md), [original model results](error-model.md)
and [rejected policy experiment](regional-policy-experiment.md).

Next acceptance work: freeze this router, evaluate fresh chronological outcomes
without retuning, calibrate intervals if justified, and run the same-optimizer
ML-versus-persistence scheduling ablation. No scheduling savings are claimed here.

Optional overrides: `PRICE_FORECAST_CONFIG` selects a JSON config;
`PRICE_MODEL_DIR` with v2 points to a parent containing `error-reduction-001/`
and `public-region-001/`. With legacy v1 it points directly to its one bundle.
Relative artifact directories resolve from the project root. Missing/corrupt
artifacts yield MODEL_UNAVAILABLE/503; explicit NAIVE mode still works.

## Verification of this integration

The full backend suite passed 386 tests and 53 subtests, with two skips. After
the final history-grouping optimization, all 29 affected serving/API/replay tests
passed again; all five launcher tests passed. AWS was mocked. The tests cover
every configured route's parity with its exact saved native model, corrupt
artifacts/evidence, pre-selection fallback, source mismatch, clock rebasing,
SQLite restart and replay warmup/isolation.

Thirty warm SIMULATED inference runs measured p95 36.1 ms for the nine Stockholm
pools and 225.0 ms for all 42 pools (252 forecasts, including six unsupported
Stockholm B200 persistence forecasts). Model loading is excluded. Conditions and
hashes are recorded in [best-model-serving-validation.json](best-model-serving-validation.json).
