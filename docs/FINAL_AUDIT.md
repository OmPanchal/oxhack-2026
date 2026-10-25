# Current code audit — 2026-10-25

> Historical backend milestone snapshot. Later frontend/API integration and live
> AWS verification supersede its pending-handoff statements. See
> [current integration evidence](../frontend/INTEGRATION.md) and the
> [pre-ML plan](PRE_ML_MILESTONES.md). Test counts and Docker evidence below belong
> to the original run; they have not been repeated for this documentation update.

Audited the current `codex/backend` checkout against AGENTS.md and the milestone
contracts. Scope included backend source, schemas, persistence, forecasting seam,
AWS adapter, optimizer, scheduling, replay/accounting, execution/control/monitoring,
the smoke script, all test modules, frontend source/configuration, shared fixture,
dependency declarations, CI and integration documentation. This does not inspect
work on teammates' other branches or establish production/cloud readiness.

## Concrete issues fixed

| Issue | Correction and evidence |
| --- | --- |
| Local background monitoring ran after scheduling preflight. A rejected source/slot or invalid scheduling mode could leave a running local container unmonitored. | Reconcile local execution before scheduling validation, independently of the trusted simulated-outcome monitor. The regression first reproduced RUNNING remaining in storage after rejection, then passed after the fix. |
| The timeout/outage test read GET executions after polling; that endpoint performed another reconciliation and hid a broken background path. | The existing test now reads persisted execution state directly before any refreshing endpoint, with a deliberately rejected source preflight. |
| Docker log retrieval could throw after a successful state inspection, preventing completion/failure settlement and capacity release. | Preserve confirmed state, retain prior output, disclose log gaps in lastMonitorError and settle outcomes atomically. A focused fake-SDK regression confirms completion and reservation release despite both log endpoints failing. |
| Docker client info/OS validation could fail without closing its client. | Close the client on failed readiness checks. |
| CombinedMonitor became unnecessary once local reconciliation was made independent. | Removed the wrapper and the extra engine-state lookup on GET executions. Core monitor protocols and domain contracts remain intact. |

New execution behavior does not change JSON shapes. `lastMonitorError` can now
also disclose incomplete log capture on a terminal record; it does not imply the
container failed. Startup uncertainty still reserves capacity and never causes an
automatic duplicate/retry.

## Test and workspace cleanup

Removed five redundant collected cases, preserving their distinct useful assertions:

- Consolidated duplicate empty/unavailable API checks into the existing metrics/API
  integration case, including missing-market errors and unknown-job execution.
- Removed the duplicate replay bad-forecast cost scenario; the official metrics
  regression now also verifies WAIT, projected price, realized charge and completion.
- Moved unknown-capacity replay rejection into existing scenario validation;
  AWS API coverage already verifies nullable capacity and blocked dispatch.
- Combined shared-capacity, priority and deterministic tie-breaking in one optimizer
  case, retaining zero-capacity rejection.
- Dropped the equivalent Infinity variant while retaining non-finite NaN and
  negative-price rejection in the AWS adapter test.

Added one regression for the previously untested Docker log-failure path and
strengthened an existing monitoring regression. Net suite: **170 → 166 cases**.
Concurrency, transactional rollback, budget precision, no-future-data checks,
independent optimizer oracle, honest savings guards and restart/idempotency tests
were retained. CI installs the execution SDK extra for the fake-SDK test; it does
not require a Docker daemon. Core-only local installs skip that optional SDK case.

Removed 13 generated `.test-tmp-*` directories after verifying each resolved
directly inside the workspace backend directory. Preserved `backend/state/`, real
execution evidence, development databases, dependency installations and teammates'
source. Restored the required postponed-annotation import in ReservationStore after
an attempted cleanup exposed its `list` method shadowing the built-in type.

## Verification

- Backend: **166 passed**, no skipped cases in this environment. The existing
  Starlette/httpx deprecation warning remains.
- Frontend: TypeScript type checking and the production build passed. Initial
  sandbox build reached prerendering
  but Windows denied a generated-directory write, so it was retried outside the
  sandbox without source changes.
- Python static pass parsed all 55 backend source/test files; no unused imports
  were reported by the AST name-usage check. This is supplementary to runtime tests.
- Genuine automatic LOCAL smoke: two sequential Docker containers completed with
  exit code 0, expected SHA-256 and empty stderr; zero manual execute calls. The
  script verified pause and persisted state after reopening the database.
- Planning input for the smoke was explicitly SIMULATED. The containers were LOCAL;
  no cloud run, ML improvement or real savings is claimed.
- Local smoke evidence:
  `backend/state/automatic-smoke-68b31004690d44fe9629370533ac7538.json`.
- `git diff --check` passed. Existing changes remain uncommitted on `codex/backend`.

## Remaining team handoffs and disclosed limits

These are visible in this checkout, not claims about work on other branches:

- Person 1's model, feature, baseline and evaluation modules remain placeholders.
  A real evaluated ML provider, appropriate risk evidence and historical data still
  need integration. The backend exposes missing providers honestly.
- Person 3's terminal remains an initial-load scaffold: charts, refreshed state,
  execution/pause controls, replay/shock controls and policy metrics need wiring.
  The TypeScript capacity mirror must accept null, and replay/shock/detail/control
  types must mirror the current backend. Frontend source was left unchanged.
- No authenticated AWS check was performed during this audit. The AWS integration
  is read-only; Spot prices/catalog offerings do not establish purchasable capacity.
  Unknown capacity remains null and cannot be allocated.
- No historical benchmark or complete three-minute UI demo was produced. Those
  require the teammates' model/frontend integration and rehearsal.
- The supported real adapter is a bounded, single-slot local CPU task. Timeouts
  require a running backend monitor; uncertain startup claims can require manual
  reconciliation. Cloud provisioning, cancellation and automatic workload recovery
  are not implemented. Replays use the documented scenario risk/recovery assumptions.

No additional confirmed backend constraint/accounting defects were found in this
review. Passing tests and a local smoke are evidence for the implemented MVP paths,
not a guarantee about every possible input, outage or future integration.
