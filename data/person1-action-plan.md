# Person 1 — ML Forecasting and Data Action Plan

## Simple guide to the sections

- **Your scope:** What you own and where you need to coordinate with teammates.
- **Datasets:** Where the information comes from and how to check that it is usable.
- **Hours 0–2 — Preparation:** Agree on data formats, collect prices, and define what your predictions mean.
- **Hours 2–7 — First model:** Build a simple baseline, train your ML model, and compare their accuracy.
- **Hours 7–11 — Integration:** Add uncertainty estimates, handle missing risk information honestly, and connect predictions to replay.
- **Hours 11–15 — Validation:** Check that predictions never use future information and that the complete system works together.
- **Hours 15–19 — Freeze and benchmark:** Stop adding features, run final comparisons, and save reproducible results.
- **Hours 19–24 — Demo:** Prepare evidence, rehearse the demonstration, and package your work.
- **Time-short priorities:** Identify what must work and which optional features to drop.

## Status and intended deliverable

This is an implementation plan, not a results report. Numerical thresholds below are proposed acceptance targets, not achieved measurements. At the time of planning, the forecasting modules are scaffold placeholders; no trained model, forecasting benchmark, scheduling savings, or execution outcome is established by this document.

Person 1's deliverable is a reproducible forecasting service providing 1–6-hour price predictions, uncertainty where supported, honest risk estimates, and model provenance. Evaluation must establish whether forecasts improve—or fail to improve—prediction accuracy and scheduling outcomes.

Requirements come from [AGENTS.md](../AGENTS.md) and the [team handoff](../docs/TEAM_WORKFLOW.md).

### Dataset implementation status

- Item 1: real AWS price export imported and checked: 1,085 records for `g4dn.xlarge` in Stockholm, covering 89 days across three Availability Zones. The original three-region target remains unmet.
- Item 2: real hardware metadata imported and checked: one NVIDIA T4 GPU per instance. Raw-to-normalized prices and manifest checksums match.
- Item 3: five reproducible simulated input datasets generated, with causal views and independent policy inputs. Replay integration and outcome benchmarks remain Person 2's work.
- Item 4: authorized-log import, provenance/label validation, cutoff-aware event and exposure summaries, and unknown-risk defaults implemented. The example is simulated; no genuine operational logs or calibrated risk model are available yet.

See [data provenance and commands](provenance.md) and the [simulation integration handoff](scenarios/README.md). Implementation tests do not establish prediction accuracy, scheduling savings, or real cloud execution.

## Your scope and integration boundary

Implement independently in:

- [Forecasting modules](../backend/app/forecasting/): `backend/app/forecasting/**`.
- [Feature builder](../backend/app/market/features.py).
- Forecasting tests: `backend/tests/forecasting/**` (to be created).
- [Data](./) and [model artifacts](../models/), as assigned by the handoff guide.

Preserve the existing [forecast service protocol](../backend/app/forecasting/interfaces.py):

```python
ForecastService.predict(ForecastRequest) -> list[Forecast]
```

Person 2 owns API routes, shared schemas, the market adapter, optimizer, replay, execution, and shared backend configuration/dependencies. Coordinate changes to those files. Person 3 consumes forecasts and metrics through Person 2's backend and owns the frontend. Preserve teammates' uncommitted work; do not silently edit their modules.

## Current implementation and serving handoff — 25 October 2026

This status update supersedes the initial-run status statements below; historical
milestone descriptions and targets remain as the original plan.

- **Steps 5–10:** persistence, causal features, chronological evaluation and the
  stronger CPU/GPU LightGBM models are delivered. The current model has 31 leaves,
  200 rounds and an L1/MAE objective. See [model results](error-model.md).
- **Steps 14–15:** the selected model is wrapped by
  `ErrorForecastService.predict(ForecastRequest) -> list[Forecast]`; the protocol
  and shared request/response schemas are unchanged. Native weight/metadata
  checksums, fixed source-pool identity, UTC origin, model-selection availability,
  finite output, explicit fallbacks and stale/future/conflicting history checks
  are enforced. The serving parity and latency evidence is in
  [forecast-serving-validation.json](forecast-serving-validation.json).
- **Step 16, backend handoff:** at the user's explicit request to connect the
  backend, the integration owner composition in `main.py` now wires this service
  through a thin `POST /api/forecasts` route, defaulting to ML. The existing GET
  returns the latest generated forecasts. `forecastMode=NAIVE` remains available.
  `/api/models/metrics` exposes the clock, model hashes, selected source identities
  and verified evaluation metrics. This is the scoped API integration handoff;
  optimizer, live market ingestion, replay, execution and frontend modules are
  not implemented or changed by this integration.
- **Steps 17 and 19:** evaluation reports, frozen selected weights, metadata,
  serving configuration and reproduction instructions are packaged. The original
  test and final extra day have now been evaluated; neither is untouched. No
  claim of a new blind test, guaranteed generalization or current-model scheduling
  savings follows from these forecast scores.
- **Still open:** empirical interval calibration (Step 11), genuine labeled risk
  evidence (Step 12; probabilities remain null), Person 2's production optimizer/
  replay and the new model's scheduling ablation (Steps 13/18), frontend chart
  tracing and complete demo rehearsals (Steps 16/20–22). Previous offline scheduler
  comparisons used the earlier model and cannot be attributed to this one.

Use [the current serving handoff](forecast-serving.md) rather than the original
Milestone 2 artifact/clock examples. With the existing API pool key, one fixed
CPU source and one source per GPU type/region are configured explicitly; the API
does not expose all 79 instance configurations simultaneously.

## Dataset plan

### 1. Required: historical cloud Spot prices

**Source:** AWS EC2 [DescribeSpotPriceHistory](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html). It supports up to 90 days of history, pagination, Availability Zone filtering, and the effective price immediately before the requested start.

**Initial collection specification:**

- Latest complete 90-day period ending at a fixed, recorded UTC timestamp.
- Three candidate regions: `us-east-1`, `us-west-2`, and `eu-central-1`.
- One common GPU instance type; initially investigate `g4dn.xlarge`.
- One optional CPU instance type; initially investigate `m5.xlarge`.
- One fixed Linux product description.
- Verify actual regional offerings and hardware specifications before freezing these choices.
- Use authenticated, read-only retrieval. Do not provision cloud resources.

Keep timestamp, region, Availability Zone, instance type, product description, price, and retrieval timestamp in raw data.

**Acceptance tests:**

- Consume all pagination tokens.
- Reject conflicting duplicate records.
- Require finite, nonnegative USD prices.
- Report coverage, missing periods, price-change counts, and constant-price stretches per series.
- Target at least 60 usable days across three comparable regional GPU series. If unavailable, document reduced scope instead of mixing incompatible hardware.
- Record source, retrieval time, checksum, usage terms, units, and transformations in [data provenance](provenance.md).

AWS prices are per instance-hour. Convert to GPU-hour or vCPU-hour only after verifying the hardware mapping. Equal GPU counts do not make different hardware interchangeable.

### 2. Required: resource metadata

**Source:** AWS instance-type metadata from read-only provider APIs or official specifications. See [DescribeInstanceTypes](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html) and [DescribeInstanceTypeOfferings](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html).

Required fields: instance type, GPU model/count, vCPU count, memory, supported regions, and chosen billing-unit conversion.

**Acceptance tests:**

- Every price series joins to exactly one metadata record.
- Hand-check one GPU and one CPU conversion if CPU support is included.
- Reject unmapped instance types.
- Confirm converted resource-unit costs reproduce the original instance-hour cost for the full instance.

### 3. Required: simulated capacity, interruptions, and workloads

Historical price data does not provide available GPU counts or historical interruption labels. Create a deterministic scenario dataset with capacity by slot/resource, exogenous interruption events, and workload arrivals, durations, deadlines, budgets, and compatibility. Record the seed and scenario version.

Include normal operation, price spikes, capacity shortage, interruption, and deadline pressure.

**Acceptance tests:**

- The same seed produces identical event files.
- Each strategy receives identical external events.
- Every synthetic field is documented as `SIMULATED`.
- Scenario generation does not inspect which strategy benefits.
- Include both feasible and deliberately infeasible workloads.

**Coordinate immediately:** `MarketSnapshot.availableUnits` is mandatory, but historical prices contain no capacity counts. Agree with Person 2 how observed prices and simulated capacity will be combined without presenting the combined record as entirely observed.

### 4. Optional: genuine capacity or interruption observations

Use existing, authorized operational logs only if available. Useful fields include request time, requested units, fulfillment outcome, instance type, region, execution duration, interruption time, and censoring status.

AWS [Spot placement scores](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-placement-score.html) are optional context. They do not guarantee capacity or interruption risk. Do not convert a score of 8 into an 80% probability.

**Acceptance tests:**

- Define label provenance and collection conditions.
- Count positive events and exposure duration.
- Separate fulfillment from interruption.
- If evidence is insufficient, retain null probabilities and documented scenario-based risk assumptions.

Do not add weather, electricity-price, or carbon datasets during the initial build. Their predictive value has not been established for this task.

## Milestone 1 — Hours 0–2: contracts and data readiness

**Outcome:** Person 2 can develop against your service while you prepare real data.

**Implementation status:** forecasting contract checks, a callable simulated service
fixture, hourly reconstruction, source validation, and quality reports are available.
See [the Milestone 1 handoff](forecasting-contract.md) for commands and conventions.
The first genuine export has been imported and converted to hourly data; see
[the collection record](provenance.md#real-collection-001--imported-24-october-2026).
Teammate confirmation of the documented defaults and expansion beyond one region
remain open.

### Step 1 — Freeze forecasting semantics with Person 2

Agree and document:

- UTC scenario origin and integer-hour mapping.
- Exactly what is observable at `currentSlot`.
- Resource identity and unit conversion.
- Whether a regional series represents a fixed Availability Zone or another documented aggregation.
- Missing/stale observation handling.
- Meaning of null uncertainty and risk fields.
- Unsupported-resource and insufficient-history behavior.
- Treatment of execution windows extending beyond the six-hour forecast horizon.

Do not define a region's price as the hindsight minimum across zones unless execution actually permits that choice.

**Test:** serialize a sample request/response through existing Pydantic models. Verify camelCase JSON and targets from `currentSlot + 1` through `currentSlot + horizonSlots`.

### Step 2 — Audit and acquire the initial dataset

Implement collection within your owned forecasting/data paths. Save immutable raw records and a retrieval manifest.

**Test:** produce a quality report containing row counts, time coverage, missingness, duplicates, and resource mappings.

**Time limit:** determine data-access feasibility within the first hour. If credentials are unavailable, request a teammate-provided export from the same source. Synthetic data may unblock integration but cannot substantiate real-world prediction claims.

### Step 3 — Define hourly reconstruction

Treat price history as price-change events. Reconstruct effective prices using preceding events and backward as-of matching; never backfill from future observations. Distinguish unchanged prices from ingestion failures.

Agree on prediction targets and replay charging together. A next-hour start-price prediction differs from a prediction of the time-weighted average paid during that hour.

**Test:** hand-calculate a tiny event sequence with a mid-hour change, then verify hourly reconstruction and cost accounting.

### Step 4 — Deliver a contract fixture

Provide representative forecast outputs with null unknown probabilities and explicit fixture provenance.

**Exit gate:** agreed semantics, documented data access, passing contract fixture, and no invented capacity observations.

## Milestone 2 — Hours 2–7: first working intelligence

**Outcome:** persistence and trained ML services with chronological evaluation.

**Implementation status:** persistence, causal features, horizon-purged chronological
partitions, three-candidate LightGBM training, model artifacts, inference fallbacks,
and validation metrics are implemented. The initial real-data run selected
`small-l1`, but its validation MAE is 8.54% higher than persistence, so `NAIVE` is
recommended. Calibration/final test remain reserved and unevaluated. See
[the Milestone 2 handoff](milestone2.md) and [measured validation report](milestone2-validation.json).

### Step 5 — Implement persistence first

In [baselines.py](../backend/app/forecasting/baselines.py), predict the latest available price at every requested horizon. Add a trailing-average baseline only after persistence works.

**Tests:**

- Exact expected outputs on hand-written examples.
- Unordered inputs and multiple resources.
- No mixing of regional/hardware histories.
- Explicit empty-history and stale-history behavior.
- Unknown risk remains null.

**Handoff:** deliver persistence to Person 2 before waiting for ML training.

### Step 6 — Implement causal features

Start with the latest known price; lags of 1, 2, 3, 6, 12, and 24 hours; trailing means/volatility over 3, 6, 12, and 24 hours; past price changes; time since last change; region/resource identity; hour/day; and forecast horizon.

Add capacity features only when provenance and decision-time availability are valid.

**Tests:**

- Hand-check selected feature rows.
- Changing observations after time `t` cannot change features at `t`.
- Full-history features at `t` equal features computed from history truncated at `t`.
- Training and inference produce identical feature columns/order.

### Step 7 — Establish chronological partitions

Use shared calendar boundaries across regions: first 60% training, next 15% model selection, next 10% uncertainty calibration, and final 15% untouched testing.

At each boundary, remove earlier-partition examples whose future target crosses into the next partition. Account for the maximum six-hour horizon. Earlier observations may supply lag features; future labels may not.

**Tests:**

- Training target timestamps precede the next partition.
- Encoders and learned transformations fit only permitted training data.
- Model training cutoff precedes every evaluated forecast origin.

### Step 8 — Train a small LightGBM model

Use the existing ML dependency group. Start with one pooled model using horizon and resource identity as features. Try only a few predefined depth, leaf-size, and learning-rate configurations.

**Tests:**

- Fix seeds and record package versions.
- Require finite, nonnegative predictions.
- Reloaded artifacts reproduce predictions within a stated tolerance.
- Unsupported categories use a documented fallback.

### Step 9 — Publish initial validation metrics

In [evaluate.py](../backend/app/forecasting/evaluate.py), report overall MAE/RMSE, metrics by horizon/region, persistence comparisons, sample counts, constant-price frequency, and errors during changing versus unchanged prices.

```text
MAE improvement (%) = 100 × (MAE_persistence − MAE_ML) / MAE_persistence
```

Handle zero persistence MAE explicitly.

**Proposed selection target:** at least 5% validation MAE improvement. This is a goal, not a guaranteed result or permission to change the test window.

**Exit gate:** a real trained model, passing causality tests, working persistence integration, and recorded validation results even if ML loses.

## Milestone 3 — Hours 7–11: uncertainty, risk, and replay integration

**Outcome:** both forecast modes operate inside the same replay.

### Step 10 — Improve demonstrated weaknesses only

Compare persistence, ML with basic lags, ML with rolling/change features, and optional calendar features. Keep additions only when validation supports them. Limit additional tuning to roughly one hour.

**Test:** use identical forecast origins/targets and report overall/per-horizon changes.

### Step 11 — Add empirical uncertainty

Estimate horizon-specific residual intervals from the separate calibration period, initially targeting 90% coverage. Return null bounds when calibration evidence is insufficient. Clip lower bounds at zero where necessary.

**Tests:**

- Bounds are finite and ordered.
- Report coverage and interval width by horizon.
- Aim for approximately 85–95% held-out coverage, with sample counts and temporal-dependence limitations disclosed.
- Do not claim guaranteed coverage during shocks.
- Never tune intervals on the final test period.

### Step 12 — Implement an honest risk fallback

Without genuine labels, keep empirical availability/interruption probabilities null, expose explicit scenario assumptions through an agreed integration mechanism, and document sensitivity cases.

If a per-slot interruption probability `p` is converted to duration risk using `1 − (1 − p)^d`, disclose constant-hazard and independence assumptions.

**Tests:** probabilities remain in `[0,1]`; unknown evidence never becomes zero risk; duration conversion handles zero/increasing durations correctly; observed and simulated evidence remain distinguishable.

### Step 13 — Integrate the forecast ablation with Person 2

Use the same optimizer, jobs, overheads, risk assumptions, and realized events. Change only the price provider between naive and ML modes.

**Tests:**

- No future prices enter forecast requests.
- Training predates replay evaluation.
- Repeated runs reproduce forecasts.
- Report spend alongside completed, failed, late, and unfinished workloads.
- Claim unconditional savings only when workload outcomes are comparable.

**Exit gate:** replay works with both providers, with risk and uncertainty limitations visible.

## Milestone 4 — Hours 11–15: end-to-end validation

**Outcome:** auditable integrated predictions with no known leakage.

### Step 14 — Run adversarial leakage tests

Verify that changing future prices leaves earlier forecasts unchanged, truncating data leaves earlier features unchanged, forecasts cannot re-enter history as observations, shocks affect predictions only after becoming observable, and artifact metadata identifies training cutoff.

Distinguish an observable announcement from an unannounced future shock.

**Acceptance:** all leakage tests pass before results are published.

### Step 15 — Verify inference and failure handling

Exercise missing history, cold-start resources, constant prices, large spikes, stale observations, missing/incompatible artifacts, and horizons one through six.

**Acceptance:** deterministic documented fallbacks, explicit fallback provenance, no invalid predictions, and no silent model failures.

**Proposed performance target:** after loading, p95 inference below 250 ms for the agreed demo portfolio on the demo machine. Record measurement conditions.

### Step 16 — Verify API and frontend presentation

Provide teammates with model version, training cutoff, forecast generation time, horizons/units, interval meaning, risk provenance, and predicted-versus-realized metric definitions.

**Acceptance:** trace one forecast from service output through API JSON to chart; values and units must match.

Person 2 owns Docker execution. Ensure local execution is not presented as evidence of regional cloud prediction accuracy.

## Milestone 5 — Hours 15–19: freeze and honest benchmarks

**Outcome:** frozen artifacts and reproducible evidence.

### Step 17 — Freeze selection, then evaluate the test period

Freeze features, hyperparameters, calibration, and model selection before opening final test results.

Deliver test MAE/RMSE against persistence, regional/horizon breakdowns, interval coverage/width, training/evaluation dates, hashes, seed, and limitations.

If the model changes because of test results, that period is no longer an untouched test.

### Step 18 — Complete scheduling benchmarks with Person 2

Run `FIFO`, `CHEAPEST_NOW`, `OPTIMIZER_WITH_NAIVE_FORECAST`, and `OPTIMIZER_WITH_ML` over a predefined workload set and seed list.

**Acceptance:** identical external inputs; independent strategy state; spend and outcome counts together; consistent recovery costs; multiple workload seeds where runtime permits; clear separation of historical prices from simulated operational outcomes.

Lower prediction MAE does not establish lower scheduling costs. Report both independently.

### Step 19 — Package reproducibility

Document commands for data preparation, training, forecast evaluation, forecasting tests, and Person 2's replay benchmark invocation. Store metadata, feature schema, training cutoff, data checksum, configuration, and evaluation outputs with the model artifact.

**Acceptance:** a clean-environment rerun using pinned inputs reproduces metrics within a documented tolerance.

**Exit gate:** stop optional feature work; fix correctness and integration issues only.

## Milestone 6 — Hours 19–24: demo readiness

**Outcome:** repeatable demonstration with defensible claims.

### Step 20 — Prepare forecasting evidence

Give Person 3 one representative, predefined forecast window; actual model-versus-persistence metrics; one decision with forecast inputs; realized outcome and benchmark comparison; and an explanation of simulated capacity/interruption assumptions.

Do not select the window retrospectively for maximum savings without disclosing that selection.

### Step 21 — Rehearse startup and reset

**Acceptance:**

- Three consecutive rehearsals with consistent results.
- Model loads without retraining.
- Cached, versioned data supports an offline demo without live AWS access.
- Reset reproduces the scenario.
- Simulated outage is labeled.
- Teammates verify genuine local Docker execution.

### Step 22 — Final handoff

Deliver forecasting modules/tests, frozen model/metadata, provenance/quality report, validation/test reports, integration instructions, known issues/fallback behavior, and authentic backup screenshots or recording.

## Priority if time runs short

Preserve real data, persistence, one trained model, causal validation, honest risk handling, and the naive-versus-ML replay comparison.

Cut optional CPU expansion, extra providers, extensive tuning, weather/carbon features, and supervised risk modeling without adequate labels.

Use only claims supported by the eventual evidence. An acceptable outcome may be: “The engine works, but persistence remains competitive on this dataset, and ML scheduling savings are not yet established.” This is an example of honest reporting, not a measured conclusion.
