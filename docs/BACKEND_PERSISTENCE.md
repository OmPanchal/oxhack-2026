# Milestone 2: SQLite persistence

Jobs, decision history, active running reservations and audit events are stored
in one SQLite file. No domain JSON or frontend interfaces changed. The only API
behavior changes are persistence across restarts and GET decisions returning
stored history rather than an unconditional empty array.

## Configuration

The default path is `backend/state/engine.sqlite3`, resolved from the backend
source location, independent of the working directory. Set `COMPUTE_DB_PATH`
to choose another file. Relative overrides resolve against the working directory.
Tests can call `create_app(database_path=...)` for explicit isolation.

The file and its parent directory are created lazily on the first store access.
SQLite and JSON storage use Python's standard library; no dependency was added.
Database files and the local virtual environment are ignored by Git.

## Internal interfaces

Construct `Database(path)` and pass the same database to:

- `JobStore`: `create`, `get`, `list`, `start`, and `transition`.
- `DecisionStore`: append with `record`, read chronological insertion order with
  `list`. Decisions reference existing jobs and do not mutate their status.
- `ReservationStore`: `list` and `overlapping(start_slot, end_slot)` across all
  resources. The caller filters the returned reservations by hardware and region.
- `EventStore`: `list(job_id=None)`, ordered by persistent event ID.

Stored model payloads use camelCase JSON and are revalidated on read. Job lists
are ordered by job ID. Audit events include timezone-aware UTC timestamps,
structured payloads and execution mode when known. Job creation has no execution
mode because no execution has occurred.

## Lifecycle and atomicity

- Creation produces PENDING and a JOB_CREATED event.
- `start(job_id, reservation, execution_mode)` changes PENDING to RUNNING and
  inserts its reservation and JOB_STARTED event in one transaction.
- Starting requires SIMULATED or LOCAL mode; PAPER does not execute jobs.
- Reservation identity, units, hardware, allowed region, arrival, duration and
  deadline must match the job. Empty windows are rejected by the existing schema.
- `transition` supports PENDING to INFEASIBLE, and RUNNING to COMPLETED or FAILED.
  Terminal states cannot restart. Transitions record the reason and remove the
  active reservation atomically. Running outcomes inherit their start mode.
- Concurrent starts of the same job cannot both succeed. Duplicate job IDs are
  protected by the database primary key and continue to return HTTP 409.
- Failed operations, including audit-write failures, roll back the full mutation.

The start operation records lifecycle state; it does not launch a container.
Milestone 7 must coordinate actual adapter outcomes with these transactions.
It must not mark a workload completed just because a start was recorded.

The optimizer remains responsible for shared capacity, portfolio budgets,
safety buffers and cost feasibility. Milestone 3 adds SchedulingService, which
validates and commits a plan against fresh reservations within one scheduling
transaction. Use that service for portfolio commits. Merely calling start for
different jobs sequentially is not a capacity check. See BACKEND_OPTIMIZER.md.

Retries/recovery policy, replay strategy isolation and execution records are
later milestones. No automatic retries or simulated outcomes are invented here.

## Verification

From `backend` on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

27 tests pass on Python 3.12.14. Coverage includes API persistence, a fresh Python
process reading jobs/decisions/reservations/audit events, terminal reservation
release, half-open overlaps, invalid transitions and reservations, duplicate IDs,
concurrent creation/start, missing job references, and transaction rollback when
audit writes fail. Each test uses a temporary database.

The existing Starlette TestClient/httpx deprecation warning remains; no tests fail.
At the end of Milestone 2 the engine, Docker adapter, forecasting and replay were
unimplemented. See BACKEND_OPTIMIZER.md for the subsequent optimizer milestone.
