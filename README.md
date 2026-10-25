# Arbitr

An autonomous buy-side compute scheduler: forecast prices, allocate a firm's workloads
across regions and time, and minimize expenditure while respecting deadlines,
capacity, hardware, budgets and execution risk. Carbon is secondary.

This repository is a **work in progress**, not a completed engine. SQLite
persistence, the portfolio optimizer, forecast/API wiring and background
replanning, deterministic replay, scoped metrics/comparisons and read-only AWS Spot ingestion are implemented.
Manual allowlisted local Docker execution has earlier backend smoke-test evidence.
Frontend/backend API integration and live AWS reads in Stockholm are now verified;
the trained ML provider, current browser walkthrough and complete demo remain. Persistent dispatch pause/resume is
implemented, and automatic local execution is available with explicit opt-in.
See [final backend milestone](docs/MILESTONE_8.md) for operation and evidence. Read
[AGENTS.md](AGENTS.md) for the project requirements and
[docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md) before splitting up work.
The [pre-ML milestone plan](docs/PRE_ML_MILESTONES.md) tracks current work.
The [frontend integration audit](frontend/INTEGRATION.md) records API/restart checks
and live AWS verification. The [backend code audit](docs/FINAL_AUDIT.md) is an earlier
snapshot with backend fixes and execution evidence. The [pre-Milestone-6 audit](docs/PRE_M6_AUDIT.md) and older
milestone test counts are historical snapshots.

## Start everything

From the repository root on macOS/Linux:

```sh
./dev
```

First-time dependency installation: `./dev --setup`. Expired/missing AWS login:
`./dev --login`. Check prerequisites without starting servers: `./dev --check`.
Defaults use profile `arbitr` and region `eu-north-1`. Wait for `Arbitr ready`,
then open http://127.0.0.1:3000 and select Backend data. Ctrl+C stops both servers.
See [startup and troubleshooting](docs/STARTUP.md) for logs, port conflicts and
configuration. The manual backend/frontend commands below remain available.

## Start the backend

Python 3.11+:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the typed API and http://localhost:8000/api/health
for process health. The legacy health stage remains SCAFFOLD for compatibility;
use `/api/engine/state` for runtime state and integration failures.
Person 1 can install `'.[dev,ml]'`; Person 2 can
install `'.[dev,execution]'`. These extras are separate so forecasting and Docker
work do not change each other's dependencies. No Docker daemon is needed to start.
The ML libraries' Python support may be narrower than the core API; Python 3.11
or 3.12 is recommended for the shared team environment.

Configure a server-owned market source before optimizing. For the explicitly
SIMULATED fixture on Windows, run from `backend`:

```powershell
$env:COMPUTE_MARKET_FILE = (Resolve-Path ..\data\scenarios\demo.json).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The background scheduler polls every two seconds in PAPER mode and uses an
integration persistence-price provider. It does not load fixture jobs; submit
workloads through POST `/api/jobs`. This default configuration starts no real work. Set
`COMPUTE_TICK_SECONDS=0` to disable polling. ML mode returns HTTP 503 until Person
1's ForecastService is configured; it never silently uses naive forecasts.
See [rolling-horizon integration](docs/BACKEND_RUNTIME.md) for wiring and endpoints.

For live AWS prices on this Mac, use the project profile `arbitr` in Stockholm:

```sh
# From backend, with your Python environment active:
python -m pip install -e '.[dev,aws]'
python -m pip install 'botocore[crt]'
aws login --region eu-north-1 --profile arbitr
export AWS_PROFILE=arbitr
export COMPUTE_MARKET_SOURCE=aws
export COMPUTE_AWS_REGIONS=eu-north-1
export COMPUTE_AWS_INSTANCE_TYPES=g4dn.xlarge,g5.xlarge
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Stop any existing backend on port 8000 before starting its replacement. The
browser-login credential provider needs `botocore[crt]`; the existing `aws` extra
alone does not install that dependency. No credentials belong in frontend files.
See [AWS setup and verification](docs/AWS_MARKET.md) for the new project experience,
status endpoints and renewal. This project's selected region is `eu-north-1`;
additional-region access has not been verified.

AWS quotes report unknown capacity, so price-only pools cannot be allocated.
Forecasts currently use persistence, not the unconnected trained model. Replay
uses separate, explicitly simulated scenarios. The read-only adapter launches no
cloud resources.

## Start the frontend

Node.js 20.9+ and npm. The scripts use Next.js with Webpack to avoid
Turbopack CSS worker port restrictions in sandboxed environments:

```sh
cd frontend
npm ci
cp .env.local.example .env.local
npm run dev
```

Open http://127.0.0.1:3000 on the Mac running Next.js. The page starts in
**Design preview**. Select **Backend data** to use FastAPI and inspect live prices
in Market. Preview jobs stay in memory and are never submitted to FastAPI.

The example environment configures a same-origin `/api` proxy to port 8000.
Backend mode polls every five seconds, displays API errors, and never falls back
to examples. Replay/shock, policy comparison, dispatch and local execution
controls are connected; current browser interaction verification remains pending.
See [frontend operation](frontend/README.md).

## Checks

```sh
cd backend
python -m pytest
```

```sh
cd frontend
npm test
npm run typecheck
npm run build
```

## What exists

- Canonical camelCase JSON schemas and forecast/optimizer service protocols.
- All required API paths; working health and SQLite-backed job creation/listing.
- Persistent decision history, running reservations, validated job lifecycle
  updates, and transactional UTC audit events through internal store interfaces.
- A deterministic portfolio optimizer with region/time choices, shared capacity,
  hardware, deadline and budget constraints, and decision evidence. An internal
  scheduling service atomically records PAPER plans or SIMULATED starts.
- Observation ingestion, checked ForecastService integration, a temporary naive
  persistence provider, working market/forecast/optimize endpoints, persisted
  decision details and runtime state, and automatic replanning on relevant changes.
- Read-only AWS EC2 GPU catalog, Availability Zone offerings and Spot prices,
  cached with explicit partial/error status and unknown capacity handling.
- Durable exact AWS instance/AZ quote batches and a read-only hourly history/gap
  export with receipt-time cutoffs. See [price-history audit](docs/PRICE_HISTORY.md).
- Deterministic replay with FIFO, cheapest-now and the optimizer using naive or
  injected ML forecasts, independent policy state, seeded simulated shocks,
  realized hourly charges and visible failed/unfinished work. Missing ML is
  explicitly UNAVAILABLE rather than substituted.
- A selectable [Capacity pressure scenario](docs/CAPACITY_SCENARIOS.md) demonstrates
  explicitly simulated GPU pools, shortages/recovery and competing workloads.
  Live AWS capacity remains unknown.
- Official replay cost reconciliation and guarded policy comparisons through
  `/api/metrics`, separate live projections with `?scope=LIVE`, and an evaluated
  model-report adapter through `/api/models/metrics`. Missing model reports are
  explicitly UNAVAILABLE, never fabricated scores.
- Manual allowlisted Docker execution, persistent container associations/results,
  duplicate prevention and monitoring. See [local execution](docs/BACKEND_EXECUTION.md).
- Opt-in automatic LOCAL execution from fresh optimizer decisions, with final
  plan validation and a verified two-container background run. See [Milestone 8](docs/MILESTONE_8.md).
- Persistent pause/resume for new starts, continued monitoring/planning while
  paused and fresh replanning before resume. See [dispatch controls](docs/BACKEND_DISPATCH.md).
- Explicit `503` for unavailable Docker, market or forecast providers.
- A Next.js/TypeScript/Tailwind terminal with typed API integration, workload
  creation/inspection, live market views, replay/shocks, policy comparison, dispatch
  controls and execution monitoring; labeled preview data stays isolated.
- API/contract smoke checks and CI for the backend and frontend.

Jobs and recorded decisions survive restarts. The default database is
`backend/state/engine.sqlite3` (ignored by Git); set `COMPUTE_DB_PATH` to override
its location. `GET /api/decisions` reads persisted history, initially empty until
the scheduling service records decisions. No public status-update endpoint is
introduced. See [backend persistence](docs/BACKEND_PERSISTENCE.md) for store usage.

The optimizer/runtime have been exercised against test scenarios, not a real
market benchmark. A trained model is not connected on this branch, and no saved historical
ML-versus-baseline benchmark has been produced here. Work on other branches is not
assessed by these statements. A genuine local Docker CPU task completed successfully; no cloud
workload has executed. See the
[optimizer assumptions and integration guide](docs/BACKEND_OPTIMIZER.md) for the
Milestone 3 implementation and the remaining integration work. The
[replay integration guide](docs/BACKEND_REPLAY.md) describes Milestone 5 endpoints,
event payloads and the reproducibility contract.
See [metrics and comparison rules](docs/BACKEND_METRICS.md) for Milestone 6 and
the [Milestone 7 plan](docs/MILESTONE_7_PLAN.md) for completed backend execution and
pause controls. Current integration status supersedes its earlier frontend handoff.
