# Frontend/backend integration checks

The frontend uses the relative `/api` client and Next.js proxy. Keep
`NEXT_PUBLIC_API_BASE_URL` unset for same-origin local use; the proxy destination
is `API_PROXY_TARGET` (default `http://127.0.0.1:8000`). A direct API base URL must
be a server origin without a trailing `/api`, with matching backend CORS origins.
The normal launcher supplies the live AWS profile and keeps its terminal open.

## Disposable integration fixture

This fixture uses real FastAPI, SQLite, the selected native models and the existing
optimiser, with explicitly SIMULATED prices/capacity. It never calls AWS or Docker,
never opens the application database, and removes its temporary database on exit.
It contains 42 configured pools across six regions, a CPU recommendation and a
capacity-blocked GPU workload. Its clock is fixed for reproducibility.

From the repository root, run these in separate terminals:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 backend/.venv/bin/python scripts/serve_integration_fixture.py
```

```sh
cd frontend
API_PROXY_TARGET=http://127.0.0.1:8011 npm run dev -- --hostname 127.0.0.1 --port 3011
```

Open `http://127.0.0.1:3011`, select Backend data, and inspect Overview, Workloads,
Timeline, Market, Replay, Policy comparison and Execution. The backend data label
identifies the transport; SIMULATED identifies this fixture's market observations.
No cloud execution or accuracy/savings benchmark is established by this check.

The opt-in HTTP contract test exercises the actual frontend client through the
Next.js proxy. It creates disposable jobs, pauses/resumes the fixture, replans,
resets/steps/shocks replay, and reads metrics/status. It deliberately requests a
missing execution ID to check error handling without running a task.

```sh
cd frontend
INTEGRATION_AUDIT_URL=http://127.0.0.1:3011 node --test --test-reporter=spec tests/http-contract.test.mjs
```

**Only point this opt-in test at the disposable fixture.** It verifies fixture
identity before performing mutations. Without the environment variable it skips.
Ctrl+C stops each test server. These test ports are independent of normal startup.

## Data contracts and display rules

- Jobs POST to `/api/jobs`; creation rebases relative windows using the backend's
  `wallClockSlot`. `currentSlot` still identifies the last processed engine state.
  A stalled data poll cannot silently shorten a newly submitted deadline.
- Market, forecasts, decisions and evidence read their backend endpoints. Explicit
  POST forecast inference does not replace official engine forecasts. CPU/GPU keys,
  zero prices, unknown capacity/risk, and model/fallback versions remain distinct.
- Market defaults to the available observation kind for its resource. Explicit
  selection remains possible; simulated prices are never relabelled observed.
- Portfolio spend uses `/api/metrics?scope=LIVE`. Replay comparisons use
  `scope=REPLAY`. Different snapshot clocks/scenarios/job counts suppress mismatched
  metrics with an explicit refresh warning. No browser calculation creates savings.
- Auxiliary outages can retain the last successful panel data with a stale warning.
  Forecasts from a different forecast mode are discarded. Core connection failure
  shows the last received state as disconnected and disables live controls.
- Delayed refreshes begun before a local replay mutation cannot overwrite its newer
  result. Replay's clock and controls are separate from the live engine; preloaded
  warmup history is not described as executed work.
- GPU alternatives survive creation, scheduling, persistence and replay charges.
  A job's requested alternatives are not confused with its allocated GPU model.
- Execution reads the allowlisted task catalog and execution records. Missing
  telemetry stays missing; PAPER recommendations do not become running jobs. Real
  Docker startup/monitoring has separate backend adapter tests and an optional
  genuine execution test. No new real Docker execution was performed by this audit.

## Verification commands

```sh
cd backend
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q
```

```sh
cd frontend
npm run typecheck
npm test
npm run build
```

Stop a frontend dev process before building into the same `.next` directory.
The audit also checks the browser-rendered queue, evidence modal, timeline,
regional price/forecast views, job creation/replanning, replay outcomes and policy
metrics against the disposable backend. Live AWS credentials, physical capacity
and real regional access remain environment-dependent; successful fixture tests
do not establish them.

## Recorded verification — 25 October 2026

408 backend tests and 53 subtests passed; one optional test skipped. Frontend type
checking/tests and the production build passed. The actual frontend client passed
the opt-in HTTP test through Next.js on port 3011 to the isolated FastAPI server
on port 8011. The saved fixture script also passed the HTTP test independently.
The existing Starlette/httpx TestClient deprecation warning remains. Local API
tests and builds needed execution outside this environment's socket/subprocess
sandbox; no AWS authentication or live allocation was involved.
