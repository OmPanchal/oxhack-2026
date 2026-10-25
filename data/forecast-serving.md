# Person 1 selected-model serving handoff

The backend now selects the saved, MAE-focused CPU/GPU LightGBM models by default
for forecast generation. The public `ForecastService.predict(ForecastRequest) ->
list[Forecast]` interface and shared camelCase request/response schemas are unchanged.
This delivers Person 1 action-plan Steps 14–16/19 for backend serving; uncertainty
calibration, new-model scheduling replay and frontend integration remain open.

## Start and call

Install the existing ML extra and start from `backend/`:

```sh
python -m pip install -e '.[dev,ml]'
uvicorn app.main:app --reload --port 8000
```

In another terminal, from the project root:

```sh
curl -sS http://localhost:8000/api/models/metrics
curl -sS -X POST http://localhost:8000/api/forecasts -H 'Content-Type: application/json' --data-binary @data/examples/ml-forecast-request.simulated.json
curl -sS http://localhost:8000/api/forecasts
```

The example contains explicitly **SIMULATED prices and capacity** for the fixed
m5.xlarge CPU and g4dn.xlarge T4 pools. It demonstrates model inference, not AWS
execution or a measured accuracy/savings claim. The POST returns twelve forecasts
(six horizons for each of the two pools). Use the returned `modelVersion` to
identify ML versus a persistence fallback. Unknown bounds/risk remain null.

`POST /api/forecasts?forecastMode=NAIVE` selects the independent persistence
service for comparison. The latest successful result is cached per app process
and read by `GET /api/forecasts`; it is empty before the first generation and
resets on restart. Invalid requests do not overwrite this cache. This generation
endpoint consumes supplied observations; live market ingestion and server-owned
optimizer/replay state remain Person 2's integration work. No data/capacity feed
is fabricated to populate the GET route automatically.

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

The scenario clock is **2026-07-28 00:00 UTC**. Request slots must use this origin;
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
