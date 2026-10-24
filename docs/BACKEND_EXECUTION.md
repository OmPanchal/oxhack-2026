# Milestone 7a — manual local execution

Manual execution uses the local Linux Docker engine through the Python SDK.
Milestone 7b supplies persistent pause/resume; Milestone 8 adds opt-in automatic
LOCAL execution through this same adapter. See BACKEND_DISPATCH.md and MILESTONE_8.md.

Install backend extras `pip install -e '.[dev,execution]'`, start Docker Desktop in
Linux mode, then start FastAPI as usual. Without the extra/engine, manual starts
return 503. App startup and ordinary tests require no Docker daemon.

## Frontend handoff — Person 3

- `GET /api/execution/tasks` returns `tasks` and the deployment capability boolean
  `automaticDispatchEnabled` (false by default).
  Currently one task: `cpu-hash-v1`, one CPU, region `local`, 30-second timeout.
- Create an ordinary job with `dockerTaskId: "cpu-hash-v1"`, `resourceType: "CPU"`,
  `resourceUnits: 1`, no GPU type, and `allowedRegions: ["local"]`. Arrival/deadline
  slots use the engine's persisted UTC origin from `/api/engine/state`.
- `POST /api/execute/{jobId}` accepts an empty body or `{}`. Extra fields such as
  images/commands are rejected with 422. Unknown jobs return 404; incompatible,
  already-started-through-another-mode, capacity or timing conflicts return 409.
- The response is a camelCase execution record: `id`, `jobId`, `taskId`,
  `executionMode: "LOCAL"`, `region: "local"`, `status`, `containerName`,
  `containerId`, immutable `imageId`, `requestedAtUtc`, `startedAtUtc`,
  `completedAtUtc`, `exitCode`, `stdout`, `stderr`, their `*Truncated` booleans,
  `failureReason`, `lastMonitorError` and `timeoutRequested`.
- `GET /api/executions` and `GET /api/executions/{id}` refresh and return execution
  state. Poll these for live status/logs. Completed records survive app restart.
  Repeating POST returns the original execution, including after completion.
  New starts while dispatch is paused return 409 DISPATCH_PAUSED.
- Display STARTING separately from RUNNING. Job status RUNNING includes a claimed
  startup reservation; it alone does not confirm a container has started.
  `lastMonitorError` indicates unavailable/uncertain observation, not proof of failure.
- This is local CPU work. Never label it as regional GPU/cloud execution, a real
  cloud charge, or realized savings. Live realized spend remains null. No ML
  interface changes are needed; forecasting stays independent.

## Execution and failure behavior

The backend fixes the image (`python:3.11-alpine`), command and resource limits.
It resolves the image to its immutable ID before claiming the job. The task runs
100,000 SHA-256 iterations, without network, host mounts or root, with a read-only
filesystem, one CPU, 256 MiB memory, 64 processes and bounded Docker log rotation.
The output fields retain at most 64 KiB each and at most the latest 1,000 log lines;
truncation is explicit. Containers are retained for inspection, not auto-removed.
The configured engine socket is explicitly local; remote Docker contexts and
DOCKER_HOST are not used.

SQLite atomically claims a pending job, unique execution ID and capacity
reservation before launch. One local task can be active at a time. Arrival,
duration/deadline, safety buffer, overlapping local reservations and configured
portfolio limits are checked. Local demo compute has no billed charge; nonzero
configured startup/transfer billing overhead is rejected pending a billing adapter.
The scheduling duration is an estimate; actual UTC completion is captured separately.

Monitoring observes container state by unique name and execution label. It records
exit status/logs, updates the job, releases capacity and appends audit events in a
single transaction. Changes are available to replanning on the next tick; outcome
settlement precedes market/model inference, so their outages cannot erase outcomes.
GET execution endpoints also monitor when background ticks are disabled.
The live runtime reconciles local containers before scheduling-mode/time/source
preflight checks, so those failures cannot stop local outcome or timeout handling.
An unavailable log stream does not prevent confirmed completion or capacity
release: previously captured output is retained and `lastMonitorError` discloses
the log gap. A terminal record with that warning may contain incomplete output.
Actual local completion rounds up to the next slot boundary for deadline metrics,
so a finish one second after a deadline counts as late.

An observed running container exceeding 30 seconds is killed and reported FAILED.
This is a monitor-enforced limit, not an independent watchdog: if the backend is
offline, reconciliation/timeout enforcement occurs when it returns. Daemon outages
retain the claim and show an error; they never invent completion. A previously
observed container that disappears is marked FAILED with unknown finish time.

There is deliberately no retry after an uncertain Docker create/start response.
Restart monitoring can recover a container that ran despite a lost response. If
the process dies between claiming and starting, or leaves a never-started created
container, STARTING may require manual reconciliation; capacity stays reserved.
The service never automatically starts such a container or duplicates the work.
Operator reconciliation/cancellation is a later extension. Keep the state database
when restarting; deleting it loses dispatch idempotency and audit history.

## Genuine smoke evidence

Run from backend: `.venv/Scripts/python.exe scripts/docker_smoke.py`. This uses a
fresh separate database under ignored `backend/state/`, launches the real task
through HTTP, checks the deterministic hash/exit code, reopens the database and
verifies repeated dispatch returns the same record. It is opt-in, outside unit CI.

Verified on 2026-10-24: LOCAL CPU container completed, exit code 0, empty stderr.
Execution ID: `0f4dbe7c7d7d448693a244d59fb1c3cf`.
Container ID: `6d8a099589475ea014b399742b8d083f0e7fb0fc8400cda0889341ddff52e790`.
Start: `2026-10-24T21:05:27.139033Z`; finish: `2026-10-24T21:05:27.740447Z`.
SHA-256: `97bb604c0b0e2a4e82e4835ae0ea9cb065126091e3de9b1ed6feeaccc779e2a4`.
Full local record: `backend/state/docker-smoke-7fe943e5808e4d1a9106c5de0f8a0749.json`.
This proves genuine local execution only. It is not a cloud or savings benchmark.

Focused offline tests cover the allowlist, invalid requirements, daemon preflight,
concurrent/repeated starts, successful/failed exits, restart recovery, missing
containers, uncertain startup, outages, deadline accounting and timeout settlement.
Final backend regression result: 155 passed (six focused execution cases added to
the 149-test suite), with the existing Starlette/httpx deprecation warning.
