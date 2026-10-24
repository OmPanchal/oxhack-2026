# Compute Arbitrage Engine

An autonomous buy-side compute scheduler: forecast prices, allocate a firm's workloads
across regions and time, and minimize expenditure while respecting deadlines,
capacity, hardware, budgets and execution risk. Carbon is secondary.

This repository is a **work in progress**, not a completed engine. SQLite
persistence and the constrained portfolio optimizer are implemented. Forecast/API
integration, replay and execution remain to be built. Read
[AGENTS.md](AGENTS.md) for the project requirements and
[docs/TEAM_WORKFLOW.md](docs/TEAM_WORKFLOW.md) before splitting up work.

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
for readiness of the scaffold. Person 1 can install `'.[dev,ml]'`; Person 2 can
install `'.[dev,execution]'`. These extras are separate so forecasting and Docker
work do not change each other's dependencies. No Docker daemon is needed to start.
The ML libraries' Python support may be narrower than the core API; Python 3.11
or 3.12 is recommended for the shared team environment.

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
FastAPI. Replay controls are disabled until implemented.

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
- Empty market and forecast reads; explicit `501` responses for optimize,
  evaluation and execution features that have not been implemented.
- A Next.js/TypeScript/Tailwind terminal shell, component ownership boundaries,
  typed API client, and one shared simulated fixture.
- API/contract smoke checks and CI for the backend and frontend.

Jobs and recorded decisions survive restarts. The default database is
`backend/state/engine.sqlite3` (ignored by Git); set `COMPUTE_DB_PATH` to override
its location. `GET /api/decisions` reads persisted history, initially empty until
the scheduling service records decisions. No public status-update endpoint is
introduced. See [backend persistence](docs/BACKEND_PERSISTENCE.md) for store usage.

The optimizer has been exercised against test scenarios, not a real market
benchmark. No model has been trained, no historical replay benchmark has been
produced, and no local or cloud workload has executed. See the
[optimizer assumptions and integration guide](docs/BACKEND_OPTIMIZER.md) for the
Milestone 3 implementation and the remaining integration work.
