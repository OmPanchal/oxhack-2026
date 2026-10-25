# Pre-Milestone-6 code and requirements audit

Reviewed 2026-10-24 on codex/backend. This reviews the current checkout, not work
that teammates may have on other branches. Earlier milestone completion reports
refer to backend implementation, not the full project's acceptance checklist.
This is the historical pre-Milestone-6 snapshot. BACKEND_METRICS.md describes
the subsequent metrics implementation; MILESTONE_7_PLAN.md records the approved
pause/resume requirement. The manifest remains optional by user decision.

## Scope and evidence

Reviewed AGENTS.md, README, TEAM_WORKFLOW, all backend milestone/AWS guides and
data/provenance.md against the backend modules, schemas, APIs, all test files,
frontend source/configuration, dependency manifests/lockfile and CI. The audit
did not train a model, authenticate AWS, execute Docker or produce a benchmark.
ML/data and frontend modules remain in their owners' hands; only backend fixes,
backend tests and integration documentation were changed.

Verification after fixes:

- Backend: 127 tests pass on Python 3.12.14. This includes the independent small
  exhaustive optimization oracle, actual SDK Stubber validation, rollback,
  concurrency and no-future-input checks. One existing Starlette/httpx warning.
- Frontend: locked npm ci succeeded, npm run typecheck passed, and npm run build
  passed with the existing Next.js/Webpack configuration. No frontend source or
  lockfile changes resulted. A successful build does not verify missing runtime
  integrations or make the TypeScript capacity contract correct.
- No authenticated AWS test: credentials were absent at the previous SDK check.
- git diff --check passes. Existing prior milestone changes remain uncommitted.

## Concrete defects fixed

| Finding | Change and regression evidence |
| --- | --- |
| Market failures blocked execution outcome settlement | Monitoring commits first. A confirmed completion releases capacity despite market or forecast outages. |
| Source, monitor and forecast calls owned the SQLite writer lock | External calls now run outside write transactions. Tests acquire a separate writer and submit a new job during each callback; the final plan includes that job. |
| A model could plan against market data changed during inference | Final commit rereads history and rejects changed inputs, while still using fresh job/reservation state. |
| Slow replay inference blocked live job/database activity | Replay computes outside the writer lock and atomically saves only if its session is unchanged. Concurrent shock/reset tests prove edits are not overwritten. |
| Resetting replay to identical values could evade content-only conflict detection | Private generation identity distinguishes reset sessions. It never affects public results or seeded world events. |
| Valid long jobs could wait forever on missing forecast-tail prices | At the last safe start, an explicitly labeled persistence tail can yield FALLBACK while respecting hard constraints. Evidence never invents ML forecasts beyond six hours. |
| Repeated equivalent allocations could exhaust search on a modest portfolio | Memoization eliminates dominated prefixes with identical capacity state. A ten-job symmetric case now completes within a bounded search; exact cost checks still pass. |
| Floating-point noise could reject a valid $0.30 budget billed as 3 × $0.10 | Shared budget comparison allows only 1e-12 USD absolute numerical noise. All four policies complete the regression workload; ordinary budget/spike failures remain covered. This is not a substitute for Milestone 6's monetary accounting design. |
| Refactoring monitoring could let an invalid live-AWS time request advance the engine clock | AWS slot validation occurs before settlement/time changes. The API test confirms an accelerated live request is rejected without advancing currentSlot. |

The persistence-tail fallback is a disclosed policy change. It is a projected
price scenario, not an assertion of future cost or probabilistic success. It does
not make missing capacity, unsupported hardware or a missing ML provider usable.

## Requirements reconciliation

| AGENTS.md area | Current state | Remaining owner/work |
| --- | --- | --- |
| Buy-side compute cost objective; carbon secondary | Preserved. No marketplace/resale/fictional transactions. Carbon defaults to zero. | None for objective. |
| UTC, hourly half-open windows, end <= deadline, camelCase | Implemented and tested. Impossible jobs remain representable. | Frontend capacity nullability and richer replay types need mirroring. |
| Price forecasting and chronological evaluation | Protocol/integration and honest persistence adapter work. ML/features/evaluation files are still placeholders here. | Person 1: real data, trained model, MAE/RMSE vs persistence, chronological cutoffs, provenance and appropriate uncertainty. |
| Risk estimation | Unknown stays null; explicitly documented hourly interruption/restart scenario is supported. No trained risk classifier is claimed. | Person 1 + 2: agree output units and provenance/calibration before consuming real risk estimates. |
| Portfolio optimizer | Shared capacity, reservations, hardware, arrivals, deadlines, budgets, overhead costs, priority and deterministic choices work. | Scalar portfolio limits require homogeneous CPU/GPU units. Startup/transfer delays are represented only through a manually configured completion buffer, not detailed transfer timing. |
| Rolling-horizon behavior | Working API and background ticks; outcomes/observations refresh forecasts and replan. Running work is neither duplicated nor migrated. | Real monitor integration remains Milestone 7. Live AWS capacity is intentionally unknown. |
| Execution | Still an explicit 501 stub; no container has run here. | Person 2, Milestone 7: task/image/command allowlist, persistent execution IDs/results/logs, idempotent dispatch and genuine Docker run. |
| Replay | Four policy paths, independent state, shared seeded world, all five shock types, persistence and correct failure/unfinished disclosure. | ML strategy remains UNAVAILABLE without provider; ERROR/unavailable strategies must be excluded from valid savings comparisons. |
| Official metrics | Replay counters and charge ledger exist; /api/metrics and /api/models/metrics remain explicit 501. | Milestone 6 plus Person 1 model-evaluation handoff. |
| AWS ingestion | Dynamic catalog and detailed quotes/index endpoints work offline against SDK-shaped responses. No provisioning. | Credentials and authenticated smoke test; catalog/price data cannot supply an exact capacity count. Whole-instance/AZ cloud allocation is outside this read-only MVP. |
| Interactive terminal | Builds, but still a scaffold in this checkout. Initial load only; no refresh loop, disabled replay/shock controls, table instead of price/uncertainty chart, placeholder policy/execution panels. | Person 3: connect existing APIs, bind replay panels to selected strategy state, add controls/charts and update stale scaffold notices. |
| Three-minute demo | Not yet satisfied. Flat synthetic demo validates mechanics, not predictive value. | All: integrate models/data/UI, finish metrics/Docker, create an honest dynamic demo, rehearse clean reset/outage and record backup. |

## Interface handoffs to resolve explicitly

- availableUnits is intentionally nullable for AWS unknown capacity, while the
  original AGENTS.md example and frontend mirror still show number. This is a
  documented backend extension, not evidence of team agreement. Mirror it before
  frontend/ML integration; never coerce null into inventory.
- ReplayView/ReplayShockRequest, DecisionDetail, EngineState and capabilities
  exist in backend schemas. Frontend mutations still use unknown return types and
  its shock type lacks the required job/jobId fields for arrival/deadline events.
- In replay mode, panels should use strategyStates[].jobs/decisions/metrics;
  /api/jobs and /api/decisions intentionally describe the separate live engine.
- A GPU job without gpuType currently matches only a null-typed GPU pool; it does
  not mean any GPU. For the current selector require a specific catalog type.
  Generic GPU/VRAM/architecture compatibility needs an explicit future contract.
- Real AWS history is not yet a training dataset: this adapter polls current
  effective prices and stores a regional minimum price index. Person 1 must
  supply/prepare historical series and model that index or a consistent SKU
  series with recorded source/unit mapping. A changing minimum SKU is not one
  fixed-instance series.
- Typed error/status envelopes expose absent functionality honestly. Legacy
  /api/health stage=SCAFFOLD is compatibility data; readiness comes from runtime,
  capabilities and per-strategy states, not that static label.

## Test cleanup

Removed the standalone schema-boundary file and duplicate route-inventory and
CPU/empty-portfolio/search-limit smoke case: eight previously collected cases.
Most repeated generic Pydantic checks or behavior already covered by actual
scheduling, replay, storage and API integration tests. Important impossible-job,
server-owned-status and no-prediction-as-history assertions were folded into
existing API tests rather than discarded.

Added targeted regressions for the defects above. Total case count is 127 versus
124 before review; deletion was based on value, not a target count. Critical
capacity, budgets, deadline boundaries, leakage, realized costs, SDK parameter,
atomicity and independent-oracle checks were retained. Reusable correctness
tests are not bloat merely because they exercise edge cases.

## Milestone 6 gates and additions to the plan

Milestone 6 can proceed now for backend accounting with constructed scenarios.
Before publishing an ML savings claim it must also have:

1. A working real provider with chronological train/validation/test provenance,
   uncertainty/risk interpretation and a known evaluation scenario.
2. Exact/comparable completed workload IDs, statuses and deadline outcomes, plus
   failed/infeasible/unfinished counts. Counts alone cannot prove equal work.
3. Separate execution/accounting scope: PAPER projections, SIMULATED realized
   replay cost and any genuine LOCAL/cloud-billed data must never be mixed.
4. A defined monetary precision/rounding rule and ledger reconciliation. The
   current float budget tolerance fixes arithmetic noise, not a full currency
   accounting/export policy. Recovery is currently zero because retries are not
   implemented; do not invent charges from projected risk surcharges.

Two useful additions are not explicit in the current milestone checklist:

- **APPROVED for Milestone 7: pause new starts while monitoring continues.**
  Persist pause/resume state across restarts, enforce the gate for automatic and
  manual starts, keep forecasts/monitoring active, and replan before resuming.
  Person 2 owns backend/state/tests; Person 3 owns controls and visible status.
  Person 1 needs no model changes. Running jobs/reservations remain monitored.
- **OPTIONAL, not a required Milestone 6 deliverable (user decision): reproducibility manifest.**
  The proposed extra would include dataset/scenario hashes, seed, shocks, policy
  configuration, model version and training cutoffs. It is not part of the
  required Milestone 6 scope.

A high-impact optional demo feature is a **single-job counterfactual timeline**:
select a job and show when/where each policy ran it, realized cost, deadline slack
and outcome, alongside the chosen forecast and an immediate-run alternative.
It makes a cost difference and its tradeoffs visible without relying on a large
savings percentage. Person 3 can build it from real backend records after
Milestone 6; it should not distract from the model/Docker acceptance gates.

This audit did not claim teammate approval, modify their source files, provision
cloud resources, or move on to implementing Milestone 6.
