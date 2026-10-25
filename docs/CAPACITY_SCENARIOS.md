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

## Replay metrics and GPU alternatives

Replay charge records retain the actual allocated `gpuType`. Accounting uses
that pool's realized observation rather than the job's optional singular GPU
requirement. This matters for `allowedGpuTypes` jobs, including `gpu-choice`,
whose singular `gpuType` is null. Price, compatibility and budget reconciliation
remain enforced; GPU models cannot change mid-execution.

If a replay saved before this fix lacks an allocated GPU type, accounting accepts
it only when the compatible realized pool is unambiguous. Otherwise the API
returns `METRICS_LEDGER_MISMATCH` with instructions to reset replay. Restart the
backend with the updated code, then press **Reset** in Replay and run it again.
This resets the simulated replay, not live jobs or market history. Do not delete
the application database to fix this error.

Regression coverage includes metrics after every capacity-pressure slot, all four
strategies, restart persistence, old-ledger handling and rejection of corrupted
GPU prices/identities or missing observations.

## Still separate

Live AWS quotes retain `availableUnits: null`. No live-price/simulated-capacity
hybrid is implemented. The simulated capacity profile does not enter live market
state, model training data, local Docker capacity or cloud provisioning.

The next milestone is a saved reproducible baseline benchmark with explicit
scenario/seed/configuration and all completion/failure counts. This scenario can
be one test case, but it is not a representative performance benchmark by itself.

## All configured model regions

With `./dev --ml`, choose **All model regions · CPU/GPU · simulated**, then press
**Reset** and **Step +1h**. This server-owned `model-coverage` fixture uses every
configured serving pool (currently 42 across six regions), with one job per pool.
It exercises CPU vCPU-hour inputs, each configured GPU model, regional routing,
per-pool capacity, all six forecast horizons, and persisted accounting. Unsupported
Stockholm B200 is explicitly forecast with persistence. Its prices and capacity
are entirely SIMULATED; this is an integration demonstration, not an accuracy or
savings benchmark or evidence of AWS access in those regions.

Reset starts at slot 168 with 168 prior simulated hours available for causal model
features. Every job arrives at or after slot 168. Only prior rows are preloaded;
future rows remain inside the scenario and are revealed as replay steps. The UTC
origin is after the serving router's selection cutoff. This warmup is independent
of live historical backfill and requires no AWS calls. Existing demo/capacity
scenarios retain their slot-zero reset behavior.

An incompatible old ledger now has a **Reset saved replay** action beside its
error on the Overview page. It resets that scenario with its existing seed and
clears simulated results only. Run the replay again afterward; live jobs, market
history and the application database are preserved.
