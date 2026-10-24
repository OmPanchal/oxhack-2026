# Milestone 8 — final backend integration and automatic local execution

Backend scope is complete. ML/data and frontend integration remain with their
owners, as agreed. This does not claim that the whole team demo or a historical
ML savings benchmark is complete.

- [x] Connect fresh optimizer decisions to actual local Docker starts.
- [x] Retain safe PAPER defaults and require explicit automatic LOCAL opt-in.
- [x] Enforce the task allowlist, hardware, local region, timing, capacity and pause gate.
- [x] Recheck plans after image preparation; reject stale plans and duplicate starts.
- [x] Monitor completion/failure and replan remaining work on background ticks.
- [x] Preserve restart/pause behavior and support removing the deployment opt-in.
- [x] Run backend regression checks and a genuine automatic execution smoke test.
- [x] Document activation, interfaces, evidence and remaining limitations.

## Enable and operate

Install `pip install -e '.[dev,execution]'`, run the local Linux Docker engine,
and set `COMPUTE_ALLOW_LOCAL_DISPATCH=1` before starting FastAPI. Alternatively,
integration code can pass `allow_local_dispatch=True` to `create_app`.
The default remains disabled; simply installing Docker never arms the scheduler.

Provide a server-owned observation source containing an explicitly labeled
`local` CPU series with known capacity. For a local demonstration, a JSON file
under ignored `backend/state/` can contain:

```json
{"market":[{"slot":0,"region":"local","resourceType":"CPU","priceUsdPerUnitHour":0,"availableUnits":1,"carbonKgPerUnitHour":null,"source":"local demonstration fixture","dataKind":"SIMULATED"}]}
```

Set `COMPUTE_MARKET_FILE` to its absolute path. This is a SIMULATED planning input,
not an AWS observation or a claim of measured local billing. The existing Spot
source does not automatically create local capacity or local prices.

Submit jobs using `dockerTaskId: "cpu-hash-v1"`, one CPU, no GPU type, and an
`allowedRegions` list including `local`. Use arrival/deadline slots relative to
the engine's persisted `originUtc`. Nonzero configured startup/transfer overhead
is still unsupported by the local demonstration adapter.

Select `executionMode: "LOCAL"` through `POST /api/optimize`, with the current
wall-clock slot (UTC hours since `originUtc`). The request itself can dispatch a
current RUN/ROUTE/FALLBACK. Subsequent background ticks automatically monitor,
refresh forecasts, replan and dispatch eligible work. `COMPUTE_TICK_SECONDS=0`
disables the background loop; explicit optimize requests still operate.
LOCAL rejects accelerated/future slots. Use replay for accelerated time.

To arm without starting yet, pause first, then select LOCAL. Resume refreshes the
plan and opens the gate; the next tick computes another fresh plan before real
dispatch. PAPER stays plan-only, and SIMULATED never starts Docker. Selecting
PAPER disarms automatic local starts without stopping already-running containers.

`POST /api/engine/pause` blocks new automatic and manual starts. Running work
continues; observations, forecasts and plans continue on relevant changes.
Pause/mode/records survive restart. A restart with the opt-in retained can continue
LOCAL operation after fresh planning; with opt-in removed it falls back to PAPER
planning and still monitors previously running jobs.

## Dispatch correctness

The optimizer stays independent of Docker. The integration service restricts
LOCAL candidates to compatible allowlisted CPU jobs and local market/forecast
rows, with capacity capped at one. A cheaper Frankfurt quote cannot become a
local execution price. Unsupported jobs receive WAIT/LOCAL_TASK_UNSUPPORTED and
are not permanently marked infeasible just because this adapter cannot run them.
Eligible jobs with genuinely infeasible constraints can still become INFEASIBLE.

The scheduling transaction records a LOCAL plan without pretending a container
has started. Outside that transaction, the runtime submits only current local
RUN/ROUTE/FALLBACK decisions. The execution service checks the latest decision ID,
portfolio/market/config/control fingerprint, active mode and wall-clock slot both
before and after image preparation, at the shared final pause/claim/start boundary.
New arrivals, reservations, market edits, a newer plan, pause or hour rollover
invalidate dispatch. A rejected stale plan waits for another fresh tick.

Actual creation/start still uses the unique execution record, single local slot,
resource limits, OS gate and outcome monitoring described in BACKEND_EXECUTION.md
and BACKEND_DISPATCH.md. The backend never changes a job to RUNNING merely because
the optimizer returned RUN. An uncertain submitted start remains reserved and is
not retried automatically. An unavailable Docker engine before claiming leaves
the job pending and exposes the failure through `engine/state.lastError`.

## Teammate handoff

No frontend, forecasting, model or dataset modules were modified.

- `/api/execution/tasks.automaticDispatchEnabled` and
  `/api/engine/state.dispatch.automaticLocalDispatchEnabled` now report deployment
  capability as booleans. An enabled capability alone does not mean the engine is
  armed: also check `executionMode == "LOCAL"` and `dispatch.paused == false`.
- `/api/optimize` now accepts LOCAL when configured, in addition to PAPER/SIMULATED.
  The existing camelCase Decision contract is unchanged. Use execution records
  and job state for actual outcomes; a plan is not a successful start.
- Existing pause/resume/status and execution/log endpoints are unchanged. Missing
  configuration returns 503 LOCAL_EXECUTION_UNAVAILABLE. Invalid LOCAL scheduling
  time returns 409. Unknown local capacity produces no execution.
- Real model predictions continue through ForecastService. No fake ML results or
  silent provider substitutions were added. Teammates own model/UI integration,
  benchmark production and the final three-minute presentation.

## Reproduce verification

Final regression result: **170 passed**, including eight focused automatic-execution
cases added to the 162-test suite. The existing Starlette/httpx deprecation warning
remains. `git diff --check` passes. Frontend checks were not repeated because its
files were not changed and runtime integration remains with Person 3.

From backend, run the normal regression suite and the explicit genuine smoke:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/docker_smoke.py --automatic
```

The smoke creates a new isolated database and explicitly SIMULATED local planning
fixture, arms LOCAL while paused, resumes, then lets the background loop execute
two real containers sequentially. It makes **zero manual execute calls**, verifies
both deterministic hashes/exit codes, pauses, and reopens the database to verify
the records and pause state. Result JSON and SQLite state stay under ignored
`backend/state/`. Containers are retained for inspection.

Verified 2026-10-24: both automatic jobs completed, exit code 0 and empty stderr.
`automatic-a`: container `0d38023e69536ad9de29ba38b0c8d1a0ff8da1558f863a783a07aafe78840e76`.
`automatic-b`: container `009a6fe00ca34b6e33526950ca1b23581443b658abfe10e5e58cf41ed7fd4921`.
Result: `backend/state/automatic-smoke-8772a462739248d48991911fc93c9f31.json`.
This demonstrates backend autonomy and real LOCAL execution, not cloud purchasing
or realized savings. AWS provisioning remains outside the MVP.

Known limits from 7a remain: monitor-enforced timeouts require a running backend;
uncertain never-started claims may require manual reconciliation; actual cloud
billing/retries/cancellation are not implemented. These are disclosed rather than
being silently presented as production execution guarantees.
