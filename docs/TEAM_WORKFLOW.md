# Three-person handoff

The initial scaffold is shared setup requested for all three roles. After this
handoff, keep implementation changes inside the following boundaries. No existing
teammate code was present when the scaffold was created.

| Owner | Files to edit independently | First deliverable |
| --- | --- | --- |
| Person 1 — ML/data | `backend/app/forecasting/**`, `backend/app/market/features.py`, `backend/tests/forecasting/**`, `data/**`, `models/**` | Persistence implementation of `ForecastService`, then chronological training/evaluation of a real price model |
| Person 2 — engine/API/execution | `backend/app/engine/**`, `backend/app/api/**`, `backend/app/execution/**`, `backend/app/jobs/**`, `backend/app/audit/**`, `backend/app/market/adapter.py`, `backend/app/main.py`, `backend/tests/engine/**`, `backend/tests/api/**` | Constrained portfolio optimizer, API integration, SQLite store, deterministic replay, allowlisted local Docker adapter |
| Person 3 — terminal/demo | `frontend/**` | Develop components against mock mode, then connect backend responses and actions |

Data/model ownership above extends Person 1's data responsibilities in AGENTS.md;
Person 2 integrates the market adapter with Person 1. Person 2 is the coordinator
for root documentation, CI, shared backend config and dependencies. Person 3 owns
`frontend/package.json` and its lockfile. Person 1's ML dependencies have a dedicated
optional group in `backend/pyproject.toml`; coordinate edits to this shared file.
Do not create a second dependency file with conflicting package versions.

## Start from one shared scaffold commit

The integrator should commit and push this scaffold once before teammates branch.
No commits or branches are created automatically by the scaffold setup.
Then each person creates a different branch from that same commit:

```sh
git switch -c person1/forecasting
# Person 2 instead: git switch -c person2/engine
# Person 3 instead: git switch -c person3/terminal
```

Use separate clones or Git worktrees if people/agents share a machine. Do not
switch branches in a directory where another person is working. Keep PRs within
ownership boundaries, merge small changes regularly, and never reset teammates'
work or force-push the shared branch. Ownership reduces conflicts; it cannot
eliminate conflicts if multiple people change the same files.

## Integration contracts — review together before independent implementation

The scaffold transcribes AGENTS.md's domain contracts; the team still needs to
review and agree to them. Person 2 owns the Python source of truth in
`backend/app/api/schemas.py`; Person 3 owns its TypeScript mirror in
`frontend/lib/types.ts`. FastAPI exposes OpenAPI at `/openapi.json` and `/docs`.
Coordinate changes to fields, response envelopes, units or semantics before
merging. Update both mirrors, API checks and affected fixtures together.

- API JSON uses camelCase; internal Python uses snake_case aliases. Unknown request
  fields are rejected. Optional `gpuType` may serialize as null.
- Slots are integer hours relative to a scenario's UTC origin. Intervals are
  `[startSlot, endSlot)`; completion at `deadlineSlot` is feasible. The production
  replay must record its UTC origin; the UI fixture has relative slots only.
- Costs are USD; prices are USD per resource unit-hour. Resource counts are integers.
- `POST /api/jobs` accepts `JobCreate` (Job without server-managed `status`). It
  returns a pending Job, 201 on creation and 409 for duplicate IDs. Impossible
  arrival/duration/deadline combinations remain representable so the optimizer
  can mark them INFEASIBLE instead of hiding them.
- Collection reads return bare arrays. Replay reset/step/state now return
  ReplayView, extending ReplayState; shock accepts ReplayShockRequest and returns
  ReplayShock (backend/app/api/replay_schemas.py). OpenAPI reflects those types.
  Person 3's client mirror still needs the extended contracts. Official scoped
  metrics and model-report contracts are now in api/metrics_schemas.py; see
  BACKEND_METRICS.md. Real execution and the approved pause/resume dispatch gate
  remain in Milestone 7 (MILESTONE_7_PLAN.md).
- AWS price-only observations extend availableUnits to number | null. null is
  unknown and cannot be allocated. Person 3 must update the TypeScript mirror;
  Person 1 must handle missing capacity explicitly. See AWS_MARKET.md.
- `POST /api/optimize` takes current slot, forecast mode (NAIVE/ML), and execution
  mode. Person 2 assembles `OptimizationInput` from server-owned state. The frontend
  does not submit authoritative job portfolios, forecasts or savings.
- `ForecastService.predict(ForecastRequest) -> list[Forecast]` is the Person 1 →
  Person 2 seam. History contains only rows at or before `currentSlot`; the request
  rejects future rows and forecast-as-history. This guard does not replace the
  team's responsibility to prevent training/evaluation leakage. Target horizons
  are 1–6 hours. Unknown risk/uncertainty remains null, not a fabricated zero.
- `PortfolioOptimizer.optimize(OptimizationInput) -> list[Decision]` receives
  pending/running jobs, forecasts, current market, reservations and overhead/
  safety/portfolio configuration. Risk estimates are carried by Forecast. It must
  account for shared capacity and never duplicate running jobs. The optimizer
  never imports trained model implementations or Docker.
- Detailed slack, forecast/risk evidence, cost breakdown and pricing assumptions
  are exposed by GET /api/decisions/details. GET /api/engine/state and
  GET /api/capabilities supply runtime status and supported hardware. Person 3
  owns consuming these additive endpoints; the base Decision is unchanged.
- All four policy names are fixed in `Strategy`. Replay strategies must have
  independent state and share identical exogenous events. Report failed and
  unfinished jobs alongside cost. No real benchmark exists in this scaffold.
- `dockerTaskId` is an allowlist lookup key, never a user-supplied shell command.
  Manual LOCAL execution is implemented; MILESTONE_8.md describes opt-in automatic
  local execution and its final plan/pause checks.
  See BACKEND_EXECUTION.md for task IDs, execution responses and frontend handoff.
  LOCAL execution does not substantiate regional cloud execution.

## Independent work and integration order

1. Person 1 implements persistence and price forecasting behind `ForecastService`,
   with provenance and chronological evaluation in their own test directory.
2. Person 2 implements/test-drives portfolio constraints using manually constructed
   Forecast inputs, then integrates Person 1's service in `main.py` (or a new
   Person 2-owned composition module). Person 1 need not edit the API routes.
3. Person 3 maintains isolated Design preview and explicit Backend data modes.
   The frontend now consumes runtime, replay/shock, metrics, dispatch and execution
   APIs. Preview-created jobs remain in memory and never reach FastAPI.
4. Person 2 coordinates shared API/schema changes with Person 3. API integration,
   restart persistence and seeded replay have recorded verification; browser flows
   still need checking. See [integration evidence](../frontend/INTEGRATION.md).
5. Follow the [pre-ML milestones](PRE_ML_MILESTONES.md): repeatable live startup,
   model-compatible retained history, explicit capacity scenarios, baseline results
   and the forecast handoff. Earlier backend LOCAL Docker smoke evidence remains
   valid for those runs; a current UI/Mac execution check and full demo remain.

### Additive GPU alternatives contract

The Add job multi-select uses `allowedGpuTypes` on Job/JobCreate. Python schemas,
the TypeScript mirror, and contract checks include this field. Legacy singular
`gpuType` requests normalize to one allowed model; multiple alternatives keep
`gpuType` null and must not be interpreted as unrestricted hardware. The optimizer and immediate policies now check membership in the alternatives
list (falling back to legacy `gpuType` when needed), and committed reservations
retain the selected model. Allocate the requested number of one model,
not a mixture, and do not duplicate the workload per selected model. CPU requests
must contain no GPU requirements. Other forecast/market/resource contracts retain
singular `gpuType` because each observation or forecast describes one model.
