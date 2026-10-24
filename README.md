# Arbitr

An autonomous buy-side compute scheduler: forecast prices, allocate a firm's workloads
across regions and time, and minimize expenditure while respecting deadlines,
capacity, hardware, budgets and execution risk. Carbon is secondary.

This repository is a **development skeleton**, not a completed engine. Read
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
- All required API paths; working health and process-local job creation/listing.
- Empty market, forecast and decision reads; explicit `501` responses for engine,
  evaluation and execution features that have not been implemented.
- A Next.js/TypeScript/Tailwind terminal shell, component ownership boundaries,
  typed API client, and one shared simulated fixture.
- API/contract smoke checks and CI for the backend and frontend.

Jobs are held in memory and disappear on restart. Person 2 replaces this with SQLite.
No model has been trained, no optimizer or replay has run, no benchmarks have been
produced, and no local or cloud workload has executed. Those are the team's next
implementation tasks, listed in the handoff guide.
