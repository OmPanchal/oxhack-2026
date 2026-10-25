# Working version without paid compute

Run from the project root:

```sh
./dev --setup --demo
```

On subsequent starts:

```sh
./dev --demo
```

Open the printed URL (normally `http://127.0.0.1:3000`), select **Backend data**,
and use **Overview** and **Workloads**. This runs the actual backend, SQLite,
selected ML models and existing constrained optimiser. Prices, finite capacity,
acquisition and execution are explicitly SIMULATED. No AWS CLI, credentials or cloud resources are required. Docker is optional
for the separate real LOCAL CPU task; ordinary demo CPU/GPU jobs remain simulated. Python, Node/npm and the ML
runtime are required; macOS LightGBM also requires `brew install libomp`.

## What now works

The demo seeds three clearly labelled sample jobs on its first run. Add your own
CPU or GPU job normally. A one-hour urgent job can start immediately when a
compatible pool has room; a flexible job can deliberately wait for its planned
window. The queue updates RUNNING/COMPLETED, and Overview shows the acquisition
stages and the exact chosen resource/region.

The flow is:

1. The optimiser recommends a feasible window using causal model predictions.
2. Dispatch asks the simulated provider to acquire the chosen resource units.
3. The provider rechecks its finite pool and existing reservations transactionally.
4. Only successful acquisition marks the job RUNNING and creates its reservation.
5. When its simulated duration ends, a durable completion observation updates the
   job and releases the reservation. Rejected acquisition leaves it PENDING.

A recommendation is not an acquisition. Admission never ignores hardware,
shared pool capacity or dispatch pause. Pausing stops new starts while running
jobs continue to complete. Requests/outcomes survive restart without double starts.
The simulated acquisition adapter cannot provision AWS instances or run Docker.
The separate LOCAL execution control can run the allowlisted CPU task using a
real local Docker engine; those jobs are never handled by simulated acquisition.

## Clock, limits and state

One scheduling hour takes **10 real seconds** by default. Set
`COMPUTE_DEMO_SLOT_SECONDS=30` before launching for a slower demonstration.
The first slot is 168, with 168 earlier simulated observations supplied for ML
warmup. Forecasts retain their model/fallback identifiers; unsupported Stockholm
B200 remains explicit persistence. Simulation time pauses across process shutdown
and resumes from the persisted slot on restart.

The default profile has 32 CPU units and eight GPU units **per configured pool**
across the 42 selected sources/six model regions. These are finite demonstration
limits, not observations of AWS inventory. User budgets, deadlines, compatibility
and shared reservations still apply. An oversized or expired request can remain
blocked or become infeasible; demo mode does not guarantee every submitted job.

Demo state lives in `backend/state/demo.sqlite3`, separately from the live database.
`COMPUTE_DEMO_DB_PATH` can select another demo file. An existing non-demo portfolio
is rejected rather than relabelled or overwritten. Starting plain `./dev --ml`
retains its live read-only prices/PAPER behavior and never enables this simulation.
Reported portfolio costs remain projections; this is not a cloud savings benchmark.

If your usual app is already running, leave it intact and use separate ports:

```sh
./dev --demo --backend-port 8014 --frontend-port 3014
```

Open `http://127.0.0.1:3014`. The launcher uses a separate Next.js output directory
for the alternate frontend port. Ctrl+C in the launching terminal stops only the
processes that launcher owns.

## API and future real acquisition

`GET /api/acquisitions` returns durable receipts with the requested pool, units,
lease window, status and stages. Engine state identifies `acquisitionMode` and
`simulationSlotSeconds`; the frontend displays these explicitly.

Real AWS acquisition remains unimplemented and disabled. A future real adapter
must perform authorised instance acquisition, handle rejection/timeouts, confirm
worker readiness and report real execution outcomes. Spot placement scores must
not be converted into inventory counts. This working version intentionally makes
no real cloud-capacity or execution claims and incurs no compute provisioning fees.

Demo logs are isolated under `.arbitr/demo-<frontend-port>/`, so a concurrent live
launcher keeps its own logs. Verification covered the normal Add job API/UI,
successful acquisition/completion, rejected acquisition without a running job,
finite shared capacity, pause behavior, restart/idempotency, and protection of
non-demo databases. The full backend run passed 413 tests and 53 subtests (one
skip); the final six demo API tests passed afterward. Frontend checks/build and
six launcher tests passed. A browser-created urgent H100 job acquired simulated
capacity and completed; no physical GPU computation is claimed.

## Routing versus execution status

The Workloads queue separates execution status, confirmed location and current
activity. A ROUTE recommendation is followed by admission and RUNNING at the
confirmed destination, then COMPLETED there. Before acquisition, a planned
destination is explicitly unconfirmed. The original routing decision remains
in job details as history; it is not rewritten into a fabricated RUN decision.

Job details show the destination/acquisition/running/completed stages before the
original scheduling recommendation. Overview also distinguishes capacity state
(acquired/released/rejected) from the job's execution status. Location is taken
from the matching acquisition or started local execution record, not guessed
from the allowed-region list or a price forecast.

## Real Docker task inside demo mode

Run `./dev --setup --demo` again once to install the Docker SDK. Start Docker
Desktop (or the local Linux Docker daemon), then create a job with **Execution
task → Deterministic SHA-256 CPU demonstration · LOCAL**. Allow at least six
scheduling hours in its completion window (60 real seconds at the default demo
speed), especially on the first run when the image may need downloading.

Go to **Replay & execution → Execution → Run local task**. This creates an actual
restricted container named `compute-<execution-id>`, visible in Docker Desktop.
The monitor shows real container status, timestamps, exit code and SHA-256 output.
The container is kept after exit for inspection. Ordinary scheduling workloads
remain SIMULATED. Choosing a GPU or cloud region does not run that GPU locally.

LOCAL tasks bypass simulated admission and reserve the separate one-CPU local
slot. They are completed only by Docker observations, never by accelerated demo
time. Timeouts and Docker timestamps use real UTC time; their completion is also
mapped to the current demo slot for scheduling provenance. Dispatch pause and the
existing allowlist/security restrictions remain enforced. Missing Docker returns
a visible error and leaves the job pending when preflight fails.

Verified on 25 October 2026 with a temporary demo database: actual container
`compute-ea22576065514ed9a6c393409b6b1a7e` completed in LOCAL mode, exit code 0,
with the deterministic 100,000-iteration SHA-256 result
`97bb604c0b0e2a4e82e4835ae0ea9cb065126091e3de9b1ed6feeaccc779e2a4`.
The exited container was preserved for inspection; no cloud instance was created.

### Local jobs and cloud compatibility

Pending jobs with a Docker task ID are now excluded from cloud pool searches in
both PAPER and SIMULATED modes. They show READY FOR LOCAL and are started from **Replay & execution → Execution → Run local task**. They do not become cloud-infeasible because the
AWS/demo market lacks a `local` region. Local Docker still checks arrival, actual
deadline time, one-CPU occupancy, allowlisted task identity and dispatch pause.
Restart the backend after updating this behavior. Create a new task if an older
one is already terminal or its deadline has expired; historical outcomes are not
automatically reset. Regression checks: 25 backend tests and frontend checks passed.

Local starts are available only on the Execution page; the workload table no
longer has a start button. Demo execution uses the same persisted logical-clock
floor as job creation if a process clock trails a committed slot. Real live
execution still requires wall-clock consistency, and future arrivals and expired
deadlines are rejected. At ten seconds per scheduling hour, a default six-hour
window lasts about one real minute: choose a larger completion window if needed.

### Add-local-task flow

Adding a LOCAL CPU task saves a PENDING workload and does not invoke cloud
planning or start a container. Workloads identifies it as Pending local execution.
In Replay & execution → Execution, the pending-local-task table and selector list
that same job from GET /api/jobs. Press Run local task there to call the existing
POST /api/execute/{jobId} Docker executor. The workload table has no start button.
Manual local tasks stay outside cloud matching in all scheduler modes unless
automatic local dispatch was explicitly enabled. Local capacity, actual arrival,
deadline, Docker readiness and dispatch pause are still checked at execution.

### Docker Desktop visibility

The backend now prefers the local Docker Desktop socket when it exists, before
the system Docker daemon. On Linux these are separate engines: a container on
`/var/run/docker.sock` may not appear in Docker Desktop, which normally uses
`~/.docker/desktop/docker.sock`. On macOS the Desktop socket may be
`~/.docker/run/docker.sock`. Remote Docker hosts remain unsupported for LOCAL.
New execution records pin the chosen local endpoint for future inspection and
show it, the container name and the container ID in the Execution tab. In Docker
Desktop include stopped containers: this short CPU task can finish immediately.
Old completed executions are not re-run or copied to another engine; create a
new local task after restarting the backend with this update.
