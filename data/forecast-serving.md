# Person 1 selected-model serving handoff

The selected CPU/GPU LightGBM models are now integrated with the persistent
backend. Enable them with `./dev --setup --ml` on first setup, then `./dev --ml`.
Use the engine's forecast selector to choose ML; the persisted mode is retained.
The public `ForecastService.predict(ForecastRequest) -> list[Forecast]` contract
remains unchanged; the integration adapter additionally receives the engine or
replay UTC origin and maps slots without changing the model's training clock.

## Start and call

Install `.[dev,aws,ml]` and `botocore[crt]` in the backend environment. macOS also
requires OpenMP (`brew install libomp`). `COMPUTE_ENABLE_ML=1` enables the selected
provider for engine/replay when launching FastAPI directly. Without that setting,
normal server planning uses persistence and explicit inference remains available.

```sh
curl -sS http://localhost:8000/api/models/status
curl -sS -X POST http://localhost:8000/api/forecasts -H 'Content-Type: application/json' --data-binary @data/examples/ml-forecast-request.simulated.json
curl -sS http://localhost:8000/api/forecasts
```

The packaged example is explicitly SIMULATED and exercises saved-model inference,
not real execution or measured accuracy/savings. Its twelve forecasts use the
native model clock. `POST /api/forecasts?forecastMode=NAIVE` selects persistence.
POST inference does not mutate official live/replay state or replace GET results.
`GET /api/forecasts` reads persisted engine forecasts, initially empty before its
first tick. Generated forecasts now survive restart with the rest of engine state.

`GET /api/models/status` preserves the native serving/evaluation metadata and adds
engine availability/mode. `GET /api/models/metrics` retains the strict backend
held-out evaluation shape; the exploratory post-holdout report is not relabeled
as a clean chronological test. It remains available in status and the original
report file. This separates inference readiness from evaluation strength.

Live ML uses the configured fixed instance/AZ sources, with explicit alias mapping
between AWS hardware names and model identifiers. A regional minimum-price index
is rejected as fixed-pool model history and receives a labeled persistence
fallback. Existing index history is not retrospectively relabeled. Collection of
169 consecutive matching observations is required before genuine live inference.

## Configuration, identities and time

The versioned [serving configuration](forecast-serving.json) loads
`models/error-reduction-001/` and verifies both text weights and metadata against
[the artifact receipt](error-model-artifacts.json). Only these four selected
weight/metadata files are exempted from the model Git-ignore rule so a fresh
checkout can load the default. Other datasets/models remain ignored. No pickle,
retraining, live AWS access or cloud provisioning is needed for inference.

Optional environment overrides:

- `PRICE_FORECAST_CONFIG`: serving-config JSON path (absolute, or relative to the
  process working directory).
- `PRICE_MODEL_DIR`: relocated directory containing the exact selected artifacts
  (absolute, or relative to the project root).

The scenario clock is **2026-07-28 00:00 UTC**. Explicit POST request slots must use this origin;
the schema does not carry a separate origin. Model training ends before slot
1257; selection uses labels through slot 1577. ML is permitted from slot 1578.
Earlier historical requests return explicit `model-not-available` persistence.
The metadata/status endpoint exposes these cutoffs and identities for Person 2
and Person 3. All API history for a configured key must come from its one source
instance, AZ and Linux product. Do not merge zones, substitute another CPU type,
or reinterpret per-vCPU prices as whole-instance prices. Hardware compatibility
and whole-instance allocation remain the optimizer/market adapter's responsibility.

The shared schema has only `(region, resourceType, gpuType)`, so the explicit
configuration selects m5.xlarge in eu-north-1a for CPU, plus one source for each
of T4, A10G, L4, L40S, A100, H100, H200 and B200 in Stockholm. The B200 source lacks
training support and is intentionally persistence fallback. This schema cannot
serve all 208 distinct source pools simultaneously without a coordinated contract
extension. Selections are fixed configuration choices, not hindsight cheapest zones.

## Failure handling and provenance

- 169 consecutive hourly prices are required (current plus 168 prior hours).
- Cold history, unknown API pools, unsupported source pools, pre-selection
  requests and zero current prices have explicit `persistence-v1:fallback-*`
  versions. A supported pool uses `lightgbm-price-l1-v1-<resource>-<weight hash>`.
- Stale/conflicting history yields HTTP 422. Future observations, forecast-as-
  history, invalid horizons and unsupported mode values are rejected with 422.
- Missing ML dependencies, missing/corrupt/incompatible artifacts, and invalid
  serving configuration yield HTTP 503 `MODEL_UNAVAILABLE`. Such load failures
  are never disguised as successful ML. Explicit NAIVE mode still works.
- Model/feature-code hashes, UTC origin, selected source identities, dataset hash
  and training/selection cutoffs are validated. Training and inference reuse the
  same causal matrix builder; all requested horizons are inferred in one batch.
- Price-only history does not supply capacity or interruption labels. Genuine
  capacity observations are needed for an entirely OBSERVED market record;
  hybrid observed-price/synthetic-capacity examples must be SIMULATED.

The `/api/models/metrics` response includes recorded evaluation metrics checked
against these serving artifacts. These are previously evaluated test scores plus
one forward day, not live performance or an untouched test. One-hour MAE remains
slightly worse than persistence, seven CPU pools worsen on the original test, and
no scheduling benefit for this new model is established.

## Validation and remaining ownership

[Serving validation](forecast-serving-validation.json) reconciles all 54 forecasts
for nine fixed pool keys at slot 2000 against archived evaluation outputs at
absolute tolerance 1e-13. This includes six B200 fallback outputs. Thirty sequential
warm inference runs (1,521 history rows, 54 forecasts, one process, CPU-only)
measured p95 about 38 ms on this machine, below the plan's 250 ms target. Loading,
source-data reads, HTTP overhead and concurrent traffic are excluded.

```sh
cd backend
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest tests/forecasting tests/engine tests/api -q
```

Validation completed with **170 tests plus 53 subtests passing**, including the
packaged CPU/GPU example traced from service output to API JSON. The API tests
ran outside the sandbox because FastAPI TestClient timed out inside it.

Forecasting behavior resides in Person 1's modules/tests/data/artifacts. The small
`main.py` integration and API tests are explicitly documented integration-owner
changes requested by the user. No shared-schema or frontend edits were needed;
existing GET response shapes are preserved. Person 2 still owns production
optimizer/replay/execution/market state; Person 3 still owns frontend presentation.
