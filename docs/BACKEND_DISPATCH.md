# Milestone 7b — pause new starts, keep observing

The live engine has a persistent dispatch pause. It blocks manual LOCAL Docker
starts and live SIMULATED scheduling starts. Monitoring, market observation,
forecast refresh on relevant changes and planning continue. Running jobs are not
stopped, migrated or duplicated. Historical replay keeps its independent controls.

Milestone 8 adds automatic LOCAL dispatch through the same execution service,
disabled by default and enabled by explicit deployment configuration plus LOCAL
mode. See MILESTONE_8.md. No cloud provisioning or frontend-owned files were changed.

## API and frontend handoff — Person 3

`POST /api/engine/pause` and `POST /api/engine/resume` accept no body or `{}` and
return the complete `EngineState`. Extra body fields return 422. The existing
`GET /api/engine/state` includes the additive `dispatch` object:

```json
{
  "paused": true,
  "revision": 3,
  "changedAtUtc": "2026-10-24T21:15:00Z",
  "lastResumedAtUtc": null,
  "lastResumeError": null,
  "automaticLocalDispatchEnabled": false
}
```

The example is illustrative, not an execution record. Existing databases default
to active dispatch, preserving the previous manual/PAPER/SIMULATED behavior.
Once paused, the state survives process/laptop restarts. A restart during resume
also leaves it paused until an explicit successful retry.

Frontend work:

- Add **Pause new starts** / **Resume** buttons and display backend-confirmed
  `dispatch.paused`. While paused, say that running work continues.
- Keep execution status/log polling and market/forecast displays active. The
  backend's normal background ticks remain enabled when dispatch is paused.
- Show resume as pending until the response arrives. On an error, refresh state
  and show `dispatch.lastResumeError` plus the API error. Never optimistically
  display resumed status.
- Decision details now have `dispatchBlocked` and `dispatchBlockReason`, currently
  `DISPATCH_PAUSED`. A planned RUN while paused is not an actual start: use job and
  execution state to display outcomes. Core Decision fields remain unchanged.
- Treat pause separately from PAPER mode and replay step/play. Do not imply
  enabling dispatch alone arms autonomous real execution: configuration and LOCAL
  mode are also required. Read the capability boolean from current backend state.

New manual starts while paused return HTTP 409 with `detail.code=DISPATCH_PAUSED`.
Repeated execute calls for an existing execution still return that same record;
they do not start work. GET execution endpoints continue to reconcile state.

## Resume and race semantics

Resume keeps the gate closed while it polls outcomes, receives current market
observations, refreshes forecasts and computes a fresh feasible portfolio plan.
The scheduler reads current jobs/reservations in the final transaction. That
transaction atomically activates dispatch and applies the newly computed plan
according to the existing mode: PAPER records plans; SIMULATED can start simulated
jobs. In LOCAL mode, resume plans only; the next tick refreshes the plan again
before Docker dispatch. It never replays a previously saved decision.

If market/forecast inference or planning fails, activation rolls back and pause
remains in effect; the error is persisted. With no market source configured,
resume returns 503 until a working source is provided. A planning hour rollover
returns 409 and requires a fresh retry. Monitoring settlements already confirmed
before a market/model outage remain durable.

Control revisions protect against concurrent requests. Another pause (even a
repeated pause) cancels any resume already forecasting; it returns 409 with
`RESUME_SUPERSEDED`. No background tick can implicitly resume the engine.
After a failed/superseded resume, the caller should read the latest state.

For Docker, the pause check is repeated after image preparation. A local OS file
lock associated with the SQLite database serializes pause with the final claim
and actual create/start submission across threads and processes. Docker I/O does
not hold SQLite's writer lock. If pause wins, no job/execution claim is created.
If a submission already won, pause waits for that submission to return before
acknowledging. An already-submitted start may still be unconfirmed after a lost
Docker response; the existing monitoring/reconciliation rules apply. Pause does
not cancel work already admitted. A busy Windows OS lock can return 503
`DISPATCH_GATE_BUSY`; retry and keep displaying the last confirmed state.

Pause state is stored in an additive `dispatch_state` SQLite table. The
`.dispatch.lock` file is only an OS synchronization handle; it contains no state,
and process exit releases its lock. Keep the database and use one shared local
path for all app processes. The engine fingerprint includes control revisions,
so a control change invalidates cached planning work. Unchanged ticks retain the
normal forecast deduplication rather than generating redundant predictions.

Person 1 needs no interface/model changes. ForecastService continues through the
existing integration seam while paused.

## Verification

162 backend tests pass, including seven focused pause/resume cases added to the
155-test suite. They cover restart persistence, monitoring/forecasting while
paused, independent replay, changed-capacity replanning, market/model failures,
pause during image preparation, cancellation of an in-flight resume, and pause
acknowledgment around an admitted start. The existing Starlette/httpx warning remains.

Opt-in genuine local check, from backend:

```powershell
.venv/Scripts/python.exe scripts/docker_smoke.py --check-dispatch-controls
```

Verified 2026-10-24: pause blocked a manual start, a reopened app retained pause,
fresh resume succeeded, the bounded CPU task ran with exit code 0 and its expected
SHA-256, and monitoring captured completion while paused again. Scheduling input
was explicitly a SIMULATED local planning fixture; execution was genuinely LOCAL.
Execution ID: `d15633f64a8440b08ae6d2ba7aa81e1c`.
Container ID: `e074c38a9ca0d10d02ca7124d3a3b124ce14f623e73b2ecd5f853bb18bd48a61`.
Local result: `backend/state/docker-smoke-1b2ff7e628b7480e95d6db89cc4674d7.json`.
No cloud execution or financial savings are claimed.
