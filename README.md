# Arbitr

An autonomous buy-side compute scheduler: forecast prices, allocate a firm's workloads
across regions and time, and minimize expenditure while respecting deadlines,
capacity, hardware, budgets and execution risk. Carbon is secondary.

This repository is a **work in progress**, not a completed engine. SQLite
persistence, the portfolio optimizer, forecast/API wiring and background
replanning, deterministic replay, scoped metrics/comparisons and read-only AWS Spot ingestion are implemented.
Manual allowlisted local Docker execution is implemented and verified. The trained
ML provider and frontend integration remain. Persistent dispatch pause/resume is
implemented, and automatic local execution is available with explicit opt-in.
See [final backend milestone](docs/MILESTONE_8.md) for operation and evidence. Read
[AGENTS.md](AGENTS.md) for the project requirements and
[docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md) before splitting up work.
The [current code audit](docs/FINAL_AUDIT.md) records verification, fixes and
remaining handoffs. The [pre-Milestone-6 audit](docs/PRE_M6_AUDIT.md) and older
milestone test counts are historical snapshots.

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

For AWS, install `'.[dev,aws]'`, configure credentials through the normal AWS
profile/SSO or IAM-role chain, and set `COMPUTE_MARKET_SOURCE=aws` and
`COMPUTE_AWS_REGIONS=eu-west-1,eu-central-1`. GET `/api/capabilities` returns dynamic
`allowedGpuTypes`, regions and instance offerings; GET `/api/market/aws/spot`
returns whole-instance and normalized GPU quotes. Unknown capacity is null and
blocks allocation. See [AWS integration and frontend handoff](docs/AWS_MARKET.md).

## Start the frontend

Node.js 20.9+ and npm. The scripts use Next.js with Webpack to avoid
Turbopack CSS worker port restrictions in sandboxed environments:

```sh
cd frontend
npm ci
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000. The example environment explicitly enables read-only
**SIMULATED** fixtures. Set `NEXT_PUBLIC_USE_MOCKS=false` and restart Next.js to
read FastAPI. Without an environment file, backend mode is the default. API errors
are displayed; there is no silent fallback to mock data. Mutations always target
FastAPI. Frontend replay controls still require Person 3's integration with the
implemented backend replay endpoints.

## Checks

```sh
cd backend
python -m pytest
```

```sh
cd frontend
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
- Deterministic replay with FIFO, cheapest-now and the optimizer using naive or
  injected ML forecasts, independent policy state, seeded simulated shocks,
  realized hourly charges and visible failed/unfinished work. Missing ML is
  explicitly UNAVAILABLE rather than substituted.
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
- A Next.js/TypeScript/Tailwind terminal shell, component ownership boundaries,
  typed API client, and one shared simulated fixture.
- API/contract smoke checks and CI for the backend and frontend.

Jobs and recorded decisions survive restarts. The default database is
`backend/state/engine.sqlite3` (ignored by Git); set `COMPUTE_DB_PATH` to override
its location. `GET /api/decisions` reads persisted history, initially empty until
the scheduling service records decisions. No public status-update endpoint is
introduced. See [backend persistence](docs/BACKEND_PERSISTENCE.md) for store usage.

The optimizer/runtime have been exercised against test scenarios, not a real
market benchmark. No model has been trained, no historical replay benchmark has
been produced. A genuine local Docker CPU task completed successfully; no cloud
workload has executed. See the
[optimizer assumptions and integration guide](docs/BACKEND_OPTIMIZER.md) for the
Milestone 3 implementation and the remaining integration work. The
[replay integration guide](docs/BACKEND_REPLAY.md) describes Milestone 5 endpoints,
event payloads and the reproducibility contract.
See [metrics and comparison rules](docs/BACKEND_METRICS.md) for Milestone 6 and
the [Milestone 7 plan](docs/MILESTONE_7_PLAN.md) for completed backend execution and
pause controls plus the remaining frontend handoff.
