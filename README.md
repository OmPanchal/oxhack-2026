# Arbitr

Arbitr schedules a firm's asynchronous compute workloads to reduce expenditure
while respecting deadlines, shared capacity, hardware requirements and budgets.
It is a buy-side scheduler, not a compute marketplace.

The merged application includes SQLite persistence, a portfolio optimizer,
read-only AWS Spot ingestion, detailed quote archival, deterministic simulated
replay, policy accounting, local Docker execution support, a trained LightGBM
provider and a connected Next.js terminal. Cloud provisioning is not implemented.

## Run locally

Python 3.11+ (3.11/3.12 recommended), Node.js 20.9+, and AWS CLI v2.32+ are required
for the live launcher. From the repository root on macOS/Linux:

```sh
./dev --setup --ml   # First run: install Python/frontend dependencies and enable ML
./dev --ml           # Later runs with the selected model enabled
```

On macOS, LightGBM also needs OpenMP. If loading reports `libomp.dylib` missing:

```sh
brew install libomp
```

Open http://127.0.0.1:3000, select **Backend data**, then use the engine forecast
selector to choose **ML**. Existing persisted forecast mode is retained; enabling
model availability does not silently change the scheduling policy. The Market
view reports model readiness and actual forecast model versions/fallbacks.
Ctrl+C stops both servers. Logs are in ignored `.arbitr/`.

Other shortcuts:

```sh
./dev                 # Live prices and persistence; no ML engine provider
./dev --login --ml     # Browser reauthentication, then start with ML enabled
./dev --check --ml     # Validate prerequisites, artifacts and AWS credentials only
```

The launcher uses profile `arbitr`, region `eu-north-1` and instance types
`g4dn.xlarge,g5.xlarge`. It does not start paid cloud resources or enable automatic
Docker dispatch. See [startup troubleshooting](docs/STARTUP.md).

## What the model actually receives

The saved CPU/GPU LightGBM artifacts live in `models/error-reduction-001/`; their
checksums and feature implementation are validated before use. The integration
maps the engine's persisted UTC origin to the model's July 28 origin and maps
AWS names such as `T4` to configured model names such as `NVIDIA T4`, returning
forecasts under the original API resource key.

With ML enabled, live GPU scheduling snapshots use the configured **fixed
instance/AZ pools**, rather than the cheapest quote across AZs. The detailed AWS
quote endpoint still returns all observed quotes. Without ML enabled, the
existing regional minimum-price index remains the live price source.

The model requires **168 prior consecutive hourly observations plus the current
observation**, from the matching source pool. With `--ml`, the app automatically
backfills missing historical prices, saves them, and fills new hours or downtime
gaps as it runs/restarts. No manual daily download or week-long wait is required.
Market's Forecast model details report historical-input readiness and pool counts.

Historical samples preserve when they were actually retrieved and are used only
for current live inference. They do not enter earlier replay decisions or replace
the runtime's observed market history. See [automatic history](docs/AUTOMATIC_HISTORY.md).
Missing anchors, unavailable pools and failed fetches remain missing and produce
explicit `persistence-v1:fallback-...` versions. They are never labeled as trained
predictions. A regional index is not silently used as fixed-AZ model history.

The source branch's API example demonstrates genuine saved-model inference on
explicitly SIMULATED inputs; it is not a live-accuracy test. Historical replay
and evaluation must respect model availability, source identity and observation
cutoffs. See [model serving and integration](data/forecast-serving.md).

## Forecast routes and provenance

- `GET /api/forecasts`: persisted engine forecasts for its current slot/mode.
- `POST /api/forecasts?forecastMode=ML|NAIVE`: isolated inference on supplied
  observations using the documented model clock. It does not change official
  engine forecasts, live market history, decisions or replay.
- `GET /api/models/status`: artifact readiness, serving identities/time/history
  requirements, experimental evaluation metadata and whether the engine is enabled.
- `GET /api/models/metrics`: the existing strict chronological evaluation contract.
  The packaged model report is exploratory post-holdout and is not promoted into
  a clean disjoint held-out evaluation. The original report remains available in
  model serving status and repository data files.

The experimental model can underperform persistence on some horizons/pools. No
live scheduling savings or fresh held-out improvement is claimed by this merge.

## Capacity, replay and execution

AWS Spot prices do not expose free GPU counts: `availableUnits` remains null, and
price-only pools cannot be allocated. ML does not change that limitation.

In **Replay & execution**, select **Capacity pressure · simulated**, reset with
seed 42, and step/play. All prices and capacity in that scenario are synthetic;
FIFO, cheapest-now and both optimizer policies see the same realized world.
ML before its availability date or without enough history is labeled as fallback.
Policy comparison shows actual model versions, spend and all job outcomes.
See [capacity scenarios](docs/CAPACITY_SCENARIOS.md).

Allowlisted LOCAL Docker tasks and monitoring are implemented. Earlier backend
smoke reports document actual CPU containers; current UI/Mac verification is a
separate demo task. No AWS workload has been launched. Automatic local dispatch
requires explicit deployment opt-in. See [execution](docs/BACKEND_EXECUTION.md)
and [dispatch](docs/BACKEND_DISPATCH.md).

Jobs, decisions, forecasts and detailed AWS quote batches survive restart in
`backend/state/engine.sqlite3`; override with `COMPUTE_DB_PATH`. Live and replay
portfolios/clocks remain independent. Design preview uses isolated hand-authored
examples; preview jobs never reach FastAPI. See [frontend operation](frontend/README.md).

## Run services independently

From `backend`, activate a Python environment and install the appropriate extras:

```sh
python -m pip install -e '.[dev,aws,ml]' 'botocore[crt]'
AWS_PROFILE=arbitr COMPUTE_ENABLE_ML=1 COMPUTE_MARKET_SOURCE=aws \
  COMPUTE_AWS_REGIONS=eu-north-1 COMPUTE_AWS_INSTANCE_TYPES=g4dn.xlarge,g5.xlarge \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Set `PRICE_FORECAST_CONFIG` or `PRICE_MODEL_DIR` for explicit alternative selected
artifacts. Missing/invalid artifacts fail ML activation visibly; persistence-only
operation can still run without the ML extra. No market source is assumed when
FastAPI is started without configuration. Swagger is at http://127.0.0.1:8000/docs.

From `frontend`, run `npm ci` and `npm run dev`. Its same-origin `/api` proxy targets
port 8000 by default; `API_PROXY_TARGET` customizes it.

## Verification and remaining work

```sh
cd backend
.venv/bin/python -m pytest -q
```

```sh
cd frontend
npm test
npm run build
```

Startup regressions: `python3 -m unittest discover -s scripts -p test_dev.py -v`.

Verified after automatic history integration on 25 October 2026: backend
**360 passed, 1 skipped, 53 subtests passed**; frontend **40 passed**; **5 startup tests passed**; frontend
production build passed. Live AWS backfill produced 168 prior hourly inputs for each T4/A10G pool and
12 genuine LightGBM forecasts through the frontend proxy. This verifies live
inference, not predictive accuracy or savings. Existing backend warnings remain.
Current integration evidence and remaining limitations are recorded in
[frontend/INTEGRATION.md](frontend/INTEGRATION.md). Earlier backend audits are
historical snapshots. The [milestone plan](docs/PRE_ML_MILESTONES.md) tracks the
baseline benchmark, current UI/local execution checks and final demo work.

## Remaining demo milestones

| Milestone | Status / completion check |
| --- | --- |
| 1. Automatic live model inputs | Complete for current T4/A10G demo pools: automatic backfill and persisted rolling history; 168/168 prior hours per pool and 12 genuine live forecasts verified. Gap/hour rollover covered by tests; real restart reused saved inputs without new history fetches. |
| 2. Meaningful ML replay | Pending: matching historical series, warm-up and valid model-availability dates, with clearly simulated capacity. The capacity-pressure fixture alone does not establish ML value. |
| 3. Saved fair benchmark | Pending: all four policies on identical inputs, with scenario/seed/configuration, spend, completions, failed/infeasible/missed/unfinished jobs and fallback versions saved. Disclose experimental/reused evaluation periods; fresh held-out evaluation is required for new accuracy claims. |
| 4. Current UI/local execution check | Pending: run an allowlisted Docker CPU task through the current UI and verify logs, completion/exit code and failures. Earlier backend smoke evidence is separate. |
| 5. Browser walkthrough | Pending: verify model inspection, workload/decision details, replay/reset/shocks, policy comparison and explicit loading/error states. |
| 6. Three-minute demo rehearsal | Pending: reliable reset → predict → decide → explain → outcome → baseline comparison, plus a backup recording and honest provenance labels. |

Actual AWS provisioning is outside this demo scope. Capacity remains explicitly
simulated in replay; Docker remains LOCAL. Passing tests does not establish cloud
capacity, real savings or live model quality. [AGENTS.md](AGENTS.md) defines
ownership and design rules.
