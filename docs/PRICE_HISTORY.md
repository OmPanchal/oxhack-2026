# Price history and model handoff

## Audit — 25 October 2026

The scheduler already persists one regional/resource/GPU index value per slot in
SQLite `market_observations`. Its upsert replaces same-hour observations, and
`/api/market` reads this history through the current slot. The persisted origin
and observations survive restarts. It does not fabricate intervening hours when
the backend was offline.

Before this change, exact instance/AZ quotes existed only in the AWS adapter's
cache. The regional index's source string names its selected instance/AZ, but
cannot reconstruct all underlying quotes or earlier same-hour values. Those
earlier detailed observations cannot be recovered from the existing database.

The checked-out forecasting modules are scaffolds and `models/` has no trained
artifacts. No historical raw/processed dataset is present. This does not assess
Person 1's work on another branch.

## Durable collection

When FastAPI composes an AWS source, it now attaches `AwsQuoteArchive` using the
same configured SQLite database as jobs/engine state. Each freshly fetched
`AwsSpotPrices` response is archived before the in-memory cache is updated.

- `aws_quote_batches` is additive: existing jobs, indices and forecasts remain.
- Full normalized quote payloads retain region, instance, AZ, exact GPU name,
  GPU count, whole-instance and per-GPU price, effective time, observation time,
  batch status and supplied errors. Capacity remains null.
- Batches also retain archival receipt time, after the AWS response is obtained.
  This matters because the adapter's observation/fetch timestamp is captured at
  request start. Receipt time gates point-in-time exports.
- Repeated identical cached payloads are deduplicated by fingerprint; refreshed
  observations remain separate even when prices stay flat. No existing batch is
  replaced. Partial/failed responses are recorded without inventing quotes.
- Existing roughly 60-second quote caching still applies. This stores samples
  the adapter actually retrieves, not every AWS price-change event. Collection
  requires the backend to be running and the live source to be polled.
- Storage failure prevents that refreshed batch from being accepted into cache;
  it is not silently treated as durably retained.

The scheduler and its forecast interface still consume regional index snapshots;
the detailed archive is a separate data source for inspection and a future agreed
model adapter. Archival does not automatically connect an exact-instance model.

## Inspect and export

From `backend`, with the project environment installed:

```sh
.venv/bin/python scripts/market_history.py
.venv/bin/python scripts/market_history.py --as-of 2026-10-25T12:00:00Z
.venv/bin/python scripts/market_history.py --output ../data/processed/aws-hourly.json
```

The first two commands print coverage without writing. The third creates a new
JSON dataset and refuses to overwrite an existing file. `data/processed/` remains
ignored. Use `--database PATH` if the server uses a custom `COMPUTE_DB_PATH`.
Export opens SQLite read-only, does not contact AWS, and never migrates a legacy
database just to inspect it. A legacy database has zero archived detailed quotes.

Sampling is `FIRST_OBSERVED_PER_UTC_HOUR` for each exact
`(region, instanceType, availabilityZone, productDescription, gpuType, gpusPerInstance)`.
It reports observed hours, gaps between first and last observation, and longest
consecutive coverage per series. It never mixes AZs, GPU bundles or product types.
Null capacity, supplied timestamps and price units remain explicit.

`hourUtc` is a bucket label, not a claim the sample was known at hour start.
`observedAtUtc` is when the adapter began observing; `availableAtUtc` is when the
response reached archival. An `--as-of` cutoff excludes responses not received
by that time. A multi-hour export is not automatically safe input for every
earlier decision: filter by each decision's cutoff again. An old `effectiveAtUtc`
does not authorize backfilling hours before the first actual receipt. Gaps are
neither zero prices nor forward-filled observations.

This sampling rule is an inspectable starting dataset, not a claim it matches
the existing model. It is not a time-weighted realized hourly billing series.

## Person 1 / Person 2 handoff still required

| Question | Current contract / unresolved choice |
| --- | --- |
| Prediction target | Runtime uses the lowest per-GPU regional index; detailed data now supports fixed instance/AZ quotes. Person 1 must identify the trained target before choosing an adapter. |
| Units | Runtime Forecast uses USD per GPU-hour for GPU rows. Exact AWS procurement is in whole-instance bundles; preserve the GPU count and both rates. |
| Identifiers | Exact AWS GPU names and regions are available; runtime Forecast has no instance/AZ identifiers. Coordinate an additive shared contract if the model requires those identities. |
| History | Person 1 supplies lag/window requirements, feature ordering, missing-hour policy and supported series. No minimum coverage is invented here. |
| Time and horizons | UTC hourly slots; forecasts generated at the decision slot for 1–6 future hours. Respect receipt cutoffs and map persisted origin to real UTC. |
| Artifacts | Supply model files/version, preprocessing configuration, dependencies, training date range and chronological validation/test cutoffs. |
| Unsupported inputs | Define insufficient-history, unseen-series and inference-failure behavior explicitly. Missing ML is currently unavailable, not a silent baseline substitution. |
| Evaluation | Compare against persistence on the same held-out targets and then through the same optimizer with identical replay inputs. Do not train/evaluate on later observations. |

Until those choices are agreed, archival readiness is complete but model-input
compatibility and training-data sufficiency are not established. Existing suitable
historical data can be supplied by Person 1; waiting for weeks of new collection
is not mandatory. Any retrospective AWS data retrieval must have separate
provenance and must not be relabeled as observations known to earlier decisions.

No public API schema, trained forecast provider, capacity model or cloud execution
adapter is changed by this work.

## Verification completed

- Backend suite: 180 passed / 1 skipped; existing Starlette/httpx warning remains.
- Six added regressions cover archive restart/deduplication, receipt-time cutoffs,
  exact-series gaps, failed responses/invalid times, legacy read-only inspection,
  and automatic archival through the real API composition.
- Live Stockholm feed archived five exact instance/AZ series. A real backend
  restart retained all original batch fingerprints and collected new batches.
- An export cutoff before collection returned zero samples. Actual JSON export
  succeeded and a second export to that path failed without changing its contents.
- Documentation links and `git diff --check` passed. No frontend implementation
  or public response schema changed; no frontend build was required.

These checks establish retention/export behavior, not model compatibility,
training sufficiency or a historical scheduling benchmark.
