# Milestone 3: constrained portfolio optimizer

The optimizer and atomic scheduling service are implemented. This milestone used
constructed forecast inputs; it does not train models, execute containers, run
historical replay, or implement autonomous ticks. POST optimize returned 501 at
the end of this milestone; BACKEND_RUNTIME.md describes Milestone 4's subsequent
API/provider wiring and background ticks.

## Interfaces and ownership

`ConstrainedPortfolioOptimizer.optimize(OptimizationInput) -> list[Decision]`
implements the existing PortfolioOptimizer protocol. It is independent of model
implementations, SQLite and execution adapters. Inputs are not mutated.

`plan(inputs) -> OptimizationPlan` additionally returns per-job evidence and the
search node count. Evidence includes deadline slack, the selected forecast rows,
known risk estimates and the projected cost breakdown. These are internal Python
types; no public JSON schemas or teammate-owned frontend/ML modules changed.
The existing Decision explanation also describes slack, model versions, known
risk values and assumptions. Structured frontend exposure remains a coordinated
Milestone 4 contract change.

## What is optimized

Each non-preemptive job receives candidate region/start/end windows. Every hour
must be priced, every region must be allowed and hardware-compatible, and each
candidate must satisfy arrival, duration, deadline, safety buffer and budget.
Current-hour price comes from the latest observation, even if a forecast for
that hour exists. Future-hour prices come from the newest available forecast
vintage. Missing prices are never replaced with realized future observations.

The search considers combinations across the portfolio, enforcing resource units
at each region/hardware/hour and an optional portfolio resource limit. Running
reservations consume capacity once; running jobs receive no new decisions.
Anonymous external reservations may also consume capacity. Duplicate reservation
IDs, pending jobs already reserved, and running jobs without a matching active
reservation are rejected rather than silently duplicating or losing capacity.

The objective is ordered explicitly to avoid the trivial zero-cost solution of
running no jobs:

1. Prefer admitting jobs in ascending latest-start slack, descending priority,
   then job ID order. This is a lexicographic admission policy; an urgent job can
   take precedence over multiple less urgent jobs. It does not maximize job count.
2. For jobs at their last safe start, prefer lower modeled failure risk among
   otherwise equally admitted portfolios. Risk with missing inputs is ranked
   conservatively for this comparison, not presented as a calibrated probability.
3. Minimize total projected compute, startup, transfer, expected recovery and
   optional carbon valuation costs.
4. Break equal-cost ties by earlier start and alphabetical region, in job order.

The search is exact over enumerated windows with admission and cost bounds, and
memoizes equivalent occupied-capacity states to avoid redundant permutations.
The default 250,000-node limit prevents unbounded work; exceeding it raises
OptimizationLimitError and commits no partial plan. This is suitable for a small
demo portfolio; larger portfolios may need a solver. Tests are correctness
checks, not performance or savings benchmarks.

## Explicit MVP assumptions

- availableUnits represents the schedulable pool before this firm's reservations
  are deducted. Latest observed capacity is carried forward; it is not a promise
  of future cloud capacity. Capacity probability is never converted to units.
- GPU type must match exactly; CPU jobs normally have null gpuType.
- allowedRegions[0] is the preferred region for RUN/ROUTE and transfer overhead.
- Startup cost is per job; transfer cost is per job routed away from that region.
- The safety buffer is unused completion headroom: end + buffer <= deadline.
  It does not extend the occupied resource window beyond the job duration.
- A scalar portfolioResourceLimit is supported only for homogeneous CPU/GPU
  portfolios, including existing reservations. Mixed types require separate
  limits through a later coordinated schema extension.
- Carbon defaults to zero valuation. If enabled, observed carbon intensity is
  carried forward. Candidates with unknown carbon intensity are excluded rather
  than treating unknown carbon as free.
- Forecasts must have been generated at or before the decision time and cover
  no more than six hours after generation. Market inputs cannot contain future
  rows or FORECAST rows. Conflicting observations/vintages are rejected.
- Missing complete forecast coverage normally produces WAIT. At the last safe
  start, a compatible job with known capacity may instead use an explicit
  latest-observed-price persistence assumption for uncovered hours. This returns
  FALLBACK / PERSISTENCE_COVERAGE_FALLBACK, with pricingAssumption in decision
  details. It handles jobs longer than the forecast horizon without fabricating
  ML forecast rows. Budgets, capacity, hardware and deadlines remain enforced;
  unknown AWS capacity still cannot be allocated. This is an estimated price
  scenario, not guaranteed future pricing or calibrated deadline reliability.

### Risk scenario, not calibrated ML

RiskPolicy documents an explicit scenario assumption: each supplied interruption
probability describes an occupied hour conditional on reaching it. Window risk
is `1 - product(1 - hourlyRisk)` when every occupied hour has risk evidence.
One full-restart recovery cost is approximated as window risk times compute cost
times recovery_cost_multiplier (default 1). This is a scenario surcharge, not an
estimate of unlimited retries, a probabilistic deadline guarantee, or evidence
of a trained interruption classifier. If any hourly estimate is unknown, window
risk stays null and the recovery surcharge is omitted and disclosed.

Availability refers to obtaining capacity at the start, using that slot's
forecast. For an immediate start, the observed available pool supplies the
deterministic capacity assumption. Future acquisition probability and window
interruption risk form a scenario reliability score used near critical deadlines.
Acquisition failure has no invented dollar penalty. Agree the meaning of risk
outputs with Person 1 before consuming actual risk estimates; null inputs work
today. Do not interpret these assumptions as calibrated real-world probabilities.

## Actions and reasons

- WAIT: a selected future window, or currently no feasible priced/allocated
  window. Unscheduled decisions have null region, window and cost.
- RUN: immediate start in the preferred region.
- ROUTE: immediate start in another allowed region; no live migration.
- FALLBACK: at the critical deadline, a more reliable candidate is selected over
  the cheapest individually feasible candidate, or missing forecast hours use
  the explicitly labeled persistence assumption. All hard constraints still apply.
- INFEASIBLE: deadline is already impossible, or known capacity/budget prevents
  execution at the final safe start. No allocation is fabricated.

Reason codes distinguish missing hardware observations, missing forecast coverage,
unknown carbon intensity, budget, capacity conflicts and deadline infeasibility.
Capacity/budget failures with remaining slack can WAIT for updated observations.

## Atomic commit service

`SchedulingService(database).run(current_slot=..., market=..., forecasts=...,
config=..., execution_mode=...)` loads pending/running jobs and reservations from
SQLite while holding one scheduling transaction. It then plans and commits using
that same transaction. Different scheduling callers cannot both plan against an
unreserved last GPU. Every recorded decision has an audit event.

- PAPER persists decision history only; it changes no job lifecycle or capacity.
- SIMULATED commits immediate starts and running reservations, and marks proven
  infeasible jobs. This is explicitly simulated state, not an executed container.
- Future WAIT windows are tentative and consume no persistent reservation.
- LOCAL is rejected until the execution adapter can coordinate real dispatch.
- A search limit, validation error or persistence failure rolls back the plan.

The service does not finish jobs as time advances. Before moving to a slot where
a running reservation has expired, the later monitoring/replay layer must settle
its outcome; stale RUNNING state is rejected and requires reconciliation.

## Verification and next step

From backend: `.\.venv\Scripts\python.exe -m pytest -q`.

59 tests pass on Python 3.12.14, with the existing Starlette/httpx warning. Tests
include shared capacity, urgent priority, rerouting flexible jobs, multi-hour
costs, arrival/deadline boundaries, buffers, budgets/overheads, CPU/GPU compatibility,
reservations and adjacent windows, carbon, scenario risk/fallback, leakage guards,
input-order determinism, unchanged inputs, and search-limit failure. A separate
exhaustive oracle checks minimum costs on 12 small seeded portfolios. Transaction
tests cover concurrent scheduling, PAPER behavior, tentative waits and full
rollback after a mid-plan failure.

Milestone 4 will obtain forecasts through ForecastService, wire POST optimize,
expose agreed decision details, and implement observation/monitoring-driven ticks.
