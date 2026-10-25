# Simulated capacity scenarios

## Run it

Start the app with `./dev`, select **Backend data → Replay & execution → Replay**,
choose **Capacity pressure · simulated**, and press **Reset** with seed 42.
Use **Step +1h** or **Play**. Choose a policy/workload to inspect its decisions and
outcomes. **Capacity by pool** shows only the last processed slot's total capacity,
before workload reservations. It does not show unused capacity or AWS inventory.
Switch to **Policy comparison** for server-accounted outcomes.

The server registers `capacity-pressure` alongside the original `demo`. Custom
registered scenario IDs remain supported. No new API endpoint or JSON schema was
introduced; reset uses the existing `scenarioId` field.

## Fixed world: capacity-pressure-v1

All prices, capacities, jobs and outcomes are SIMULATED. Region/GPU names are
identifiers used to exercise compatibility, not evidence of real AWS inventory.

| Pool | Slot 0 | 1 | 2 | 3 | 4–7 | Illustrative USD/GPU-hour |
| --- | --- | --- | --- | --- | --- | --- |
| Stockholm (`eu-north-1`), A10G | 2 | 1 | 0 | 1 | 2 | 0.40 |
| Stockholm (`eu-north-1`), T4 | 1 | 1 | 1 | 1 | 1 | 0.20 |
| Frankfurt (`eu-central-1`), A10G | 1 | 1 | 1 | 1 | 1 | 0.65 |

Seven workloads cover urgent competing training, region-flexible inference,
acceptable GPU alternatives, a two-GPU batch arriving during the shortage, a
three-GPU job which never fits, and a later arrival. The horizon is eight one-hour
intervals. Jobs are non-preemptive; alternatives require all units of one model.

The baseline capacity profile is fixed, not randomly generated. Resetting with
the same seed and events reproduces the run; the seed controls probabilistic
interruption events if injected. A different seed need not change this fixed
world without probabilistic events. This is a constraint demonstration, not a
historical dataset or evidence that an optimizer saves money.

## What is verified

- Every active allocation respects the shared region/GPU pool, allowed hardware,
  arrival and deadline, including half-open end-slot boundaries.
- Under the naive optimizer, flexible inference routes to Frankfurt and the GPU
  alternative job uses T4. The two-GPU job waits at slots 1–3 and starts at slot 4.
- The oversized job becomes infeasible. Capacity loss produces visible failures
  and retained pre-failure charges. Running work is not silently migrated.
- All strategies receive the same realized world and independent job/reservation
  state. Forecast providers receive only history through the decision slot;
  they do not see the later shortage/recovery profile above.
- Reset + seed + identical shock reproduces the full replay response, including
  stepping across a service/database restart.
- API replay reset/step leaves live market rows, jobs and decisions untouched.
- The capacity view excludes future and stale slots, preserving genuine zero
  and unknown capacity instead of inventing units.

Existing simulator behavior settles a capacity reduction against running
reservations in stable start-slot/job-ID order. Jobs which no longer fit fail
with `REALIZED_CAPACITY_LOSS`; they are not automatically restarted or migrated.
This is an explicit scenario assumption, not a measured AWS interruption model.

The naive optimizer can spend more or lose more work than an immediate policy
in this scenario. Display the received outcomes; do not turn the demonstration
into a guaranteed-savings claim. Missing ML stays UNAVAILABLE.

## Still separate

Live AWS quotes retain `availableUnits: null`. No live-price/simulated-capacity
hybrid is implemented. The simulated capacity profile does not enter live market
state, model training data, local Docker capacity or cloud provisioning.

The next milestone is a saved reproducible baseline benchmark with explicit
scenario/seed/configuration and all completion/failure counts. This scenario can
be one test case, but it is not a representative performance benchmark by itself.
