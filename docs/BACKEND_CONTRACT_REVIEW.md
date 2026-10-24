# Milestone 1: backend contract review

Reviewed 2026-10-24 on `codex/backend`. Owner: Person 2.

Historical Milestone 1 review: subsequent implementation resolves several gaps
listed below. PRE_M6_AUDIT.md is the current readiness/ownership checklist.

Sources: `AGENTS.md`, `README.md`, `docs/TEAM_WORKFLOW.md`, and
`data/provenance.md`. This is a proposal for teammate review, not a record of
team agreement. Existing API contracts are unchanged.

## Milestone 1 baseline (before persistence implementation)

- Pydantic schemas and TypeScript domain types agree on fields and enum values.
- All 15 required method/path combinations exist. Health and job creation/listing
  work; jobs are process-local. Market, forecast and decision reads return empty
  arrays. Replay state explicitly reports `NOT_IMPLEMENTED`.
- Optimize, replay mutations, metrics and execution return explicit HTTP 501.
- `ForecastService.predict(ForecastRequest) -> list[Forecast]` and
  `PortfolioOptimizer.optimize(OptimizationInput) -> list[Decision]` already exist.
- The demo fixture is SIMULATED and contains only slot-zero prices and one job.
  It cannot support a historical benchmark or genuine model evaluation.
- Original baseline: 4 tests passed. With six added contract-boundary cases:
  10 tests passed on Python 3.12.14. Tests exercise schema/API boundaries, not a
  working scheduler or deadline/capacity enforcement.
- One dependency deprecation warning: Starlette's TestClient warns about httpx.
  It does not fail tests. No dependency requirements were changed.
- Local environment: `backend/.venv` (ignored by Git), installed with
  `pip install -e '.[dev]'`. From backend, run
  `.\.venv\Scripts\python.exe -m pytest -q` on Windows. The default system
  `python` resolves to an unusable Windows Store alias on this machine.

## Milestone status

- [x] Run original tests and establish baseline.
- [x] Inspect Python schemas, TypeScript mirror, routes and service interfaces.
- [x] Review documented scheduling conventions and current validation gaps.
- [x] Add checks for existing schema boundaries without changing interfaces.
- [x] Prepare proposed missing contracts and review questions.
- [ ] Persons 1 and 3 review and agree shared contracts.

The local review is complete. The team contract freeze remains pending review.

## Conventions to preserve

- API output uses camelCase; Python constructors also accept snake_case.
  Unknown fields and non-finite numbers are rejected. Numeric inputs are not
  globally strict: Pydantic may coerce compatible values.
- A slot is one hour. Scheduling windows are nonempty `[startSlot, endSlot)`;
  `endSlot <= deadlineSlot` is feasible. Adjacent reservations do not overlap.
- USD per resource unit-hour multiplied by resource units and occupied hours
  gives compute cost. Carbon valuation defaults to zero.
- UTC timestamps must be timezone-aware. Relative integer slots require an
  explicit UTC origin in replay; the current ReplayState does not contain one.
- Impossible job deadlines remain valid submissions so the optimizer can report
  INFEASIBLE. Do not reject them as malformed job requests.
- Unknown uncertainty or risk remains null. No supervised interruption claims
  without labels. A scenario estimate must carry its provenance.
- Forecast history contains only rows at or before currentSlot and excludes
  FORECAST rows. SIMULATED history is permitted for labeled scenario runs.
- Forecast targets follow generation time; requests support horizons 1–6.
  Current validators do not enforce an upper bound on returned target horizons,
  interval ordering, or forecast freshness inside OptimizationInput.
- POST jobs returns 201, duplicate IDs return 409, validation errors return 422.
  Collection reads and optimize return bare arrays.

## Decisions needed before implementation

| Gap | Proposed behavior | Review owner |
| --- | --- | --- |
| Current-slot price vs future forecasts | Use the observed current-slot price for immediate execution; use forecasts only for future slots. Reject future-generated forecasts. Cover every occupied slot or exclude the candidate. | Persons 1 + 2 |
| Future capacity | Current availableUnits is the baseline, not a guarantee of future availability. Carry it forward explicitly for the MVP, subtract reservations, and document this assumption. Availability probability is a risk signal, not a unit count. Realized capacity may differ in replay. | Persons 1 + 2 |
| Forecast horizon vs long jobs | Exclude windows without full price coverage; report insufficient forecast coverage separately from proven deadline/hardware infeasibility. Agree an extension policy if longer workloads are needed. | Persons 1 + 2 |
| Risk semantics | Define whether interruptionProbability is per hour or for the full execution window before using it in expected recovery cost. Publish statistical/scenario provenance separately from price-model version. | Persons 1 + 2 |
| RUN / ROUTE / FALLBACK | WAIT when plannedStartSlot > currentSlot. RUN starts now in the preferred region, proposed as allowedRegions[0]. ROUTE starts now in another allowed region. FALLBACK starts now under an explicit reliability policy that still satisfies hard constraints. Explain route/reliability evidence even when WAIT takes precedence. | Persons 2 + 3 |
| Critical deadlines | Define fallback threshold, safety-buffer occupancy, recovery-cost assumptions, and priority direction in OptimizerConfig. Proposed: higher priority first after lower deadline slack. | Person 2; communicate to Persons 1 + 3 |
| Portfolio resource limit | A single limit currently mixes CPU and GPU units. Apply it only to homogeneous portfolios or introduce limits per resource type through a coordinated schema change. | Persons 2 + 3 |
| Reservations | Running reservations are committed; future WAIT plans are tentative and replannable. Starting work atomically commits capacity and status; repeated optimization must not count a reservation twice. | Person 2 |
| PAPER mode | Produce decisions without Docker or simulated completions. Replay uses SIMULATED; genuine local execution uses LOCAL. | Persons 2 + 3 |
| Shock payload | Generic magnitude cannot express a job arrival, interruption target or resource-specific shortage. Add kind-specific payloads and duration; reject retroactive shocks. | Persons 2 + 3; scenario data with Person 1 |

These proposals do not authorize schema changes in teammate-owned files.

## Proposed response contracts

All fields below are proposed camelCase JSON. Coordinate Python models and the
frontend mirror together before enabling the corresponding endpoints.

### Decision details

Keep the existing Decision fields and array response. Propose an optional
`details` object with `deadlineSlackSlots`, `forecastMode`, `modelVersion`,
`forecastGeneratedAtSlot`, `availabilityProbability`, `interruptionProbability`,
`riskSource`, and a cost breakdown (`computeUsd`, `startupUsd`, `transferUsd`,
`expectedRecoveryUsd`, `carbonUsd`). Missing evidence is null.

Expose predicted savings only with a named comparison and its projected cost;
do not reuse the realized benchmark-savings field. Define slack as deadline minus
planned end minus any required completion safety buffer.

### Replay

- Reset and step return the same expanded ReplayState as GET state.
- Add `scenarioId`, `originUtc`, `endSlot`, `dataKind`, and `strategyStates` to
  the existing status/currentSlot/seed/strategies fields.
- Each strategy state contains `strategy`, its own `jobs`, `reservations`,
  `decisions`, and `metrics`. No shared mutable job/capacity state.
- A step settles completions at the boundary, applies that slot's external events,
  reveals observations/arrivals, generates forecasts, schedules work, and charges
  occupied slots. All strategies see the same ordered external event stream.
- Shock returns an accepted event with `eventId`, `kind`, `slot`,
  `dataKind: "SIMULATED"`, and its validated payload. Acceptance is not completion
  of the affected workload. Reset with the same scenario, seed and shock sequence
  must reproduce results.

### Metrics

GET metrics returns `asOfSlot`, `executionMode`, `dataKind`, and a list of
strategy results with `strategy`, `computeSpendUsd`, `recoveryCostUsd`,
`startupCostUsd`, `transferCostUsd`, `carbonCostUsd`, `totalSpendUsd`,
`completedJobs`, `failedJobs`, `infeasibleJobs`, `pendingJobs`, `runningJobs`,
`unfinishedJobs`, and `missedDeadlines`.

`unfinishedJobs = pendingJobs + runningJobs`; lifecycle counts are disjoint.
Missed deadlines are a separate overlapping measure: unfinished work at its
deadline boundary and work completed late both count, without double counting.
Infeasibility is disclosed separately from deadline misses. Define failed-job
deadline accounting explicitly during replay implementation.

Savings comparisons identify the baseline, absolute difference, percentage
(null for zero baseline spend), and whether identical jobs completed. Cost
differences with unequal completion sets must be labeled as such.

GET models/metrics is Person 1's handoff: `status` (UNAVAILABLE/EVALUATED),
`modelVersion`, `dataSource`, UTC chronological split cutoffs, `sampleCount`,
`mae`, `rmse`, `persistenceMae`, `persistenceRmse`, and improvement values.
Unavailable evaluation is explicit with null metrics; no fabricated zeros.
Risk evaluation is separate and present only with genuine labels.

### Local execution

POST execute returns HTTP 202 with `executionId`, `jobId`,
`executionMode: "LOCAL"`, `status` (STARTING/RUNNING/COMPLETED/FAILED),
`startedAtUtc`, `completedAtUtc`, `exitCode`, `stdout`, `stderr`, and
`failureReason`. Incomplete timestamps/results are null. Logs are bounded with
an explicit truncation indicator.

Propose GET `/api/executions/{executionId}` for monitoring; this is an addition
to the required routes and needs frontend agreement. Docker task IDs resolve
through a server allowlist. Repeated starts must not launch another container;
return the active execution. Unknown jobs return 404, incompatible lifecycle
states return 409, and an unavailable Docker runtime returns 503.

### Errors and health

Propose application errors as `{"detail": {"code": "...", "message": "..."}}`;
retain FastAPI's field-level 422 validation format. This requires coordinating
the current duplicate-ID string response and NOT_IMPLEMENTED feature response.
Replace the hardcoded SCAFFOLD health stage only when functionality exists;
expose capability/readiness fields so the terminal can enable controls honestly.

## Review handoff

- Person 1: review horizon coverage, current-slot pricing, capacity assumptions,
  risk units/provenance, and model metrics. Training and data remain their scope.
- Person 3: review decision details, action semantics, replay/metrics/execution
  responses, error handling and health capabilities. Frontend files are unchanged.
- Person 2: implement agreed schemas and relevant contract tests, then persistence
  and optimizer milestones. Team agreement remains pending; no messages have
  been sent to teammates from this review.
