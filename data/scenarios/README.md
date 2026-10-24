# Person 1 simulation data handoff

These files provide inputs for Person 2's replay engine. They do not run an
optimizer, execute jobs, estimate empirical interruption probabilities, or
calculate benchmark savings. `demo.json` remains the original frontend fixture.

## Generated suite

[generated-v1/manifest.json](generated-v1/manifest.json) identifies the five
seed-42 fixtures and checksums. Every scenario spans 24 hourly slots from
`2026-10-24T00:00:00Z`; the date is a synthetic clock origin.

- `normal.json`: simulated prices and fixed capacity, with staggered arrivals.
- `price-spike.json`: GPU prices in `us-east-1` are multiplied by three during
  `[4, 7)`. Other prices, capacity, and jobs match the normal case.
- `capacity-shortage.json`: the GPU admission ceiling in `us-east-1` becomes zero
  during `[6, 9)`. Prices and jobs match the normal case.
- `interruption.json`: a GPU pool interruption in `us-west-2` at slot 9. Prices,
  capacity, and jobs match the normal case. Whether it affects a job depends on
  the policy's actual running state; no failure result is fabricated.
- `deadline-pressure.json`: an additional priority-10 GPU job arrives at slot 6,
  takes two hours, and is due at slot 8. It has zero waiting slack.

Each scenario has two GPU units and eight CPU units per region before shortages.
These are fictitious resource pools, not verified AWS instance inventories. GPU
labels use `NVIDIA T4`; CPU units mean vCPUs. The three ordinary jobs have a
hand-checked feasible schedule in the normal fixture. Two additional jobs are
deliberately infeasible: `impossible-time` has too little time to finish and
`impossible-hardware` requests `UNSUPPORTED_GPU`. All jobs start `PENDING`; the
engine must discover and report infeasibility. The `deliberatelyInfeasibleJobs`
field is test metadata and is not passed to the scheduler.

## Interface and ownership

The new envelope/event format is a versioned dataset format, not a change to the
shared API. Its `jobs` and `market` records validate against the existing `Job`
and `MarketSnapshot` schemas. Events are local simulation annotations, not request
bodies for `/api/replay/shock`. Person 2 owns adapter/replay integration; confirm
these semantics with them before wiring the new files into API execution.

From Python, use the Person 1 helpers:

```python
from app.forecasting.scenario_data import (
    generate_scenario,
    independent_strategy_inputs,
    observations_at,
)

scenario = generate_scenario("price-spike", seed=42)
view = observations_at(scenario, current_slot=3)
inputs = independent_strategy_inputs(scenario, current_slot=3)
```

`observations_at` returns fresh copies of market history through the current slot,
arrived jobs, and occurred events. Future prices, jobs, shocks, and test annotations
are omitted. A price or capacity event does not announce its future restoration
time. `independent_strategy_inputs` returns equal, separately mutable copies for
FIFO, CHEAPEST_NOW, OPTIMIZER_WITH_NAIVE_FORECAST, and OPTIMIZER_WITH_ML.

The complete scenario is for the simulator only. Never pass it directly to a
forecaster or optimizer. Each policy must maintain its own persistent execution,
reservation, and accounting state; these helpers do not implement that state.
Because views include historical events, the engine must process each event once
(for example by its index in the original event array), and enqueue each job ID
only once. Rebuilding a view must not reset a completed job to `PENDING`.

## Proposed tick semantics for integration

At the boundary for slot `t`:

1. Complete jobs whose `endSlot == t` before applying interruptions.
2. Apply interruption events for `t` to matching jobs already running with
   `startSlot < t < endSlot`. Match region, resource type, and GPU type. The event
   affects all such jobs, using the same exogenous event for every policy.
3. Reveal the market row for `t` and newly arrived jobs.
4. Replan and start new work using that policy's remaining reservations/capacity.

Jobs starting at the interruption boundary are not retroactively interrupted.
Recovery, retries, and cost accounting remain Person 2's engine policy; use the
same rules across strategies and disclose them in benchmarks.

`availableUnits` in these fixtures is the total admission ceiling, not unused
capacity. Subtract existing reservations before admitting new work. A shortage
does not kill already running jobs; it prevents new admissions when the ceiling
is below committed use. Forced termination is represented only by explicit
interruption events. Do not migrate running jobs to make a shortage disappear.

Price/capacity shocks are already reflected in `market`; their event annotations
are audit information. Do not apply the multiplier or capacity reduction twice.
Deadlines and durations use half-open hourly intervals, and completion exactly at
the deadline is feasible. The deadline-pressure event describes a newly arrived
urgent job; it does not silently rewrite an existing job's deadline.

## Combining historical prices with simulated operational data

The generated suite is wholly simulated. It does not claim to have joined live
AWS prices or hardware metadata. Keep observed prices from Steps 1–2 in their own
artifact, with instance/AZ identity and collection hashes.

The current API has a single `dataKind` field per market row. If a later adapter
combines observed prices with synthetic capacity, mark the combined row
`SIMULATED`, retain separate price/capacity provenance in the dataset envelope,
and describe the source accurately. Do not mark the combined row entirely
`OBSERVED`. A future per-field provenance API extension needs team agreement.

## Reproducibility and checks

Run the generator with the same seed, origin, slots, and generator version to
reproduce the files byte for byte. A different seed changes baseline price data.
The generator refuses an existing output directory. Verify the manifest hashes
before consuming a suite, especially after an interrupted write.

Tests cover byte-identical regeneration, shock windows, independent policy
inputs, future-data exclusion, schema compatibility, explicit simulation labels,
and feasible/infeasible workload examples. None of those tests establishes model
accuracy, optimizer performance, or real cloud execution.
