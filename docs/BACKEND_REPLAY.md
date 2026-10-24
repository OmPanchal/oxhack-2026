# Milestone 5: deterministic counterfactual replay

Replay reset, step, state and shock endpoints are implemented. The simulator has
FIFO, CHEAPEST_NOW, OPTIMIZER_WITH_NAIVE_FORECAST and OPTIMIZER_WITH_ML policy paths.
ML remains UNAVAILABLE until Person 1 supplies a provider. No trained model,
historical performance claim or actual local/cloud execution is introduced.

## Scenario and source ownership

Person 1's data files are unchanged. The default server registry exposes demo:
the existing illustrative UI prices are explicitly expanded into an eight-hour
flat SIMULATED scenario. Its arbitrary UTC origin is 2000-01-01T00:00:00Z, not
a claimed observation timestamp. Source labels identify the synthetic expansion.
It demonstrates mechanics and shocks, not predictive advantage or real savings.

For other data, inject `create_app(replay_scenarios={"name": scenario})`, using
api/replay_schemas.py's ReplayScenario. The scenario has id, description,
originUtc, endSlot, jobs, market and optional interruptionProbability. It requires
an aware UTC origin, unique job IDs, arrivals before the end, and one realized
market row per resource series per hour. Missing historical prices/capacity are
rejected rather than silently filled and labeled observed. Capacity is the total
schedulable pool before this firm's reservations. FORECAST rows are not outcomes.

The frontend selects a registered scenario ID, never a file path or arbitrary
cloud resource. Custom scenario construction/real-data provenance remains a
handoff with Person 1.

## API and frontend handoff

| Endpoint | Input | Result |
| --- | --- | --- |
| POST /api/replay/reset | Existing seed and scenarioId fields | Fresh ReplayView |
| POST /api/replay/step | Existing slots integer, 1–24 | ReplayView after that many hourly intervals, capped at end |
| GET /api/replay/state | None | Persisted ReplayView |
| POST /api/replay/shock | ReplayShockRequest | Accepted SIMULATED event with deterministic eventId |

ReplayView extends the existing ReplayState fields with initialized, scenarioId,
description, originUtc, endSlot, executionMode=SIMULATED, dataKind=SIMULATED,
strategyStates, events and observedMarket. Existing frontend code reading the
base fields remains compatible. Before reset it is READY with initialized=false;
step/shock return 409 until reset. Unknown scenario IDs return 404 and malformed
requests return 422. Retroactive events and invalid references return 409.

Each strategy state contains strategy, ACTIVE/UNAVAILABLE/ERROR status, error,
jobs, reservations, decisions, latest forecasts, realized charges, outcomes,
missedDeadlineIds and backend-computed metrics. Person 3 owns adding the extended
TypeScript types and controls; no frontend files were edited.

The next slot awaiting processing is currentSlot. Reset starts at zero without
revealing future market rows or job arrivals. One step processes [t,t+1), settles
its boundary outcomes and returns currentSlot=t+1. End-of-horizon state is
COMPLETED even if some jobs remain unfinished or a strategy is unavailable;
those conditions stay explicit in strategy state. A completed step is a no-op.

Replay is isolated from live engine jobs, reservations, decisions and runtime
clock. It advances only through replay/step; the live background poll never
advances it. Existing SIMULATED lifecycle ticks in the live engine are not the
four-policy counterfactual replay.

## Policy rules and fairness

- FIFO visits arrived pending jobs by arrivalSlot then ID and starts immediately
  in the alphabetically first currently feasible region.
- CHEAPEST_NOW uses the same stable job order and chooses the lowest currently
  priced feasible region, breaking ties alphabetically. It does not deliberately
  wait for forecast price reductions.
- Both baselines enforce compatibility, allowed regions, current shared capacity,
  deadlines, buffers, scalar portfolio limits, and budgets. Their full-duration
  cost estimate holds current prices constant; it never reads future realized
  prices. Budget/capacity infeasibility can force waiting.
- Both optimizer strategies call the same constrained optimizer and config.
  Only the chosen ForecastService differs. They see only arrived jobs and
  observations at or before their decision slot. Earlier forecast vintages may
  supply current-slot risk; current prices still come from observations.
- ForecastService is injected through the same create_app forecast_services
  parameter as Milestone 4. Each reset makes independent provider copies, so
  replay does not intentionally advance a live model's state. Providers must be
  copyable, deterministic and stateless at inference for exact reproducibility.
- A missing ML provider is explicitly UNAVAILABLE; no naive model is presented
  as trained ML. A provider error or modelVersion change marks that strategy
  ERROR. Its running work is still monitored/charged to avoid hiding outcomes,
  but new jobs are not dispatched. Reset after correcting the provider.

All four strategies receive the same job definitions/arrivals, price/capacity
rows, deadline changes and seeded regional interruption outcomes. Jobs and
reservations are deep-separated per strategy. Completed workloads can differ
because policies make different decisions; this must remain visible in future
savings comparisons. Unavailable/error strategies are not valid benchmark peers.

The full scenario is private simulator state. Policies receive only current
observations or chronological revealed history; never the scenario's future
market array. This prevents inference-time leakage. Before claiming a real ML
benchmark, Person 1 must separately establish chronological training/evaluation
cutoffs and model provenance; a history guard cannot prove the model was not
trained on evaluation data.

## Hourly event order

For each hour:

1. Reveal that hour's common realized market and arrivals; apply scheduled
   deadline changes to the same job definitions in every policy.
2. Settle deadline constraints and apply interruption/capacity loss to running
   commitments. Capacity-loss survivors are ordered by start slot then job ID.
3. Refresh forecasts and make each policy's decisions on independent state.
4. Start immediate allocations, then charge that hour's realized unit-hours and
   any first-hour overhead. If the next charge would exceed the actual per-job
   budget, fail the job before incurring it; retain prior spend.
5. Advance the boundary, complete jobs whose end equals the boundary, release
   reservations, then record unmet deadlines. Completion at the deadline is valid.

Jobs are non-preemptive. Interruptions or capacity loss fail affected jobs and
release their reservations; there is no invented recovery/retry implementation.
RecoveryCostUsd is consequently zero. Expected recovery surcharges affect
optimizer projections only; they are never charged as realized expenditures.

## Simulated shocks

All event payloads retain kind, slot, region, magnitude and dataKind=SIMULATED.
ReplayShockRequest additionally supports durationSlots (default 1), resourceType,
gpuType, jobId and job. Price/capacity/interruption events can filter a region
and/or resource. Omitted filters affect all resource series.

| Kind | Magnitude and payload |
| --- | --- |
| PRICE_SPIKE | Nonnegative price multiplier for durationSlots |
| CAPACITY_SHORTAGE | Whole resource units removed from each matching pool, floored at zero, for durationSlots |
| INTERRUPTION | Probability in [0,1] of a pool outage each affected hour; magnitude=1 forces it |
| DEADLINE_PRESSURE | jobId plus whole hours removed from its deadline; new deadline is at least the event slot |
| JOB_ARRIVAL | Complete JobCreate in job; arrivalSlot must equal the event slot and ID must be new |

Deadline/arrival events do not accept regional filters or extended durations.
Events must start in an unprocessed slot and remain inside the horizon. An
interrupted pool has zero available units for that hour and running jobs fail;
new jobs cannot immediately reuse that interrupted pool in the same hour.

For example:

```json
{"kind":"CAPACITY_SHORTAGE","slot":2,"region":"eu-west-1","magnitude":1,"durationSlots":2}
```

The scenario's optional interruptionProbability is also explicitly simulated,
not inferred from spot-price history. Draws are a stable hash of seed, event ID,
slot and resource pool, independent of policy order, model calls and mutable RNG
state. Synthetic effects change market source/dataKind labels transparently.

## Accounting, persistence and verification

Realized compute, startup, transfer and optional carbon costs are stored as
hourly charges. A forecast price does not enter realized accounting. Lifecycle
counts include completed, failed, infeasible, pending and running jobs;
unfinished = pending + running. Missed deadlines overlap these counts and include
any non-completed arrived job when its deadline passes, including previously
failed/infeasible jobs. No job is removed to improve the displayed results.

The complete scenario, seed, accepted event sequence, history, policy config and
independent strategy states persist in a separate SQLite replay_session table.
Reset clears only replay state. Resume with the same deterministic model versions
and configuration; changed policy configuration requires reset. A requested batch
of hourly steps commits atomically, and restart/step batching preserves results.
Inference runs outside the database writer transaction. Before saving the batch,
the service checks the saved session for concurrent edits, including a reset to
identical inputs. An internal random generation ID distinguishes reset sessions;
it is excluded from public results and has no role in seeded market outcomes.

110 tests pass on Python 3.12.14 with the existing Starlette/httpx warning.
Replay tests verify policy distinctions, identical arrivals/outages, capacity
contention, realized-budget spikes, overhead/carbon costs, exact deadline
boundaries, failed and unfinished jobs, every shock kind, retroactive/reference
rejection, no future observations in model inputs, reset/seed/batching/restart
reproducibility, error-state disclosure, live-state isolation and batch rollback.
A deliberately wrong forecast waits for a supposed cheap hour and actually costs
more than naive scheduling; the test confirms accounting reports that loss.

Tests are constructed scenarios, not historical benchmark results. Milestone 6
adds the official scoped metrics endpoint, reconciliation and fair comparisons;
see BACKEND_METRICS.md. A manifest is optional and was not included. Genuine
ML/data integration and frontend controls remain separate work. Milestone 7a
subsequently implemented and verified local Docker execution; see BACKEND_EXECUTION.md.
