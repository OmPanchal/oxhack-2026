# Arbitr: readiness before ML integration

Updated 25 October 2026. This is a delivery plan, not authorization to provision
cloud resources or change another developer's owned modules.

## Verified starting point

- Live AWS ingestion works with profile `arbitr` in `eu-north-1`; the frontend
  proxy returned five observed Spot quotes for T4/A10G and two regional price indices.
- The backend currently uses persistence forecasts, reports ML as unconfigured,
  and preserves unknown AWS capacity. Prices alone do not enable allocation.
- Job creation/persistence, GPU alternatives, decision evidence, seeded replay,
  shocks and policy accounting have integration evidence; see
  [the integration audit](../frontend/INTEGRATION.md). Those checks used simulated
  market data and do not establish real cloud execution or model quality.
- Earlier backend milestone reports document genuine LOCAL Docker smoke runs.
  Execution has not been repeated through the current frontend on this Mac.

## Milestones

| Milestone | Status | Definition of done | Ownership |
| --- | --- | --- | --- |
| 1. Reliable live-data startup | Live feed verified; repeatable setup pending | A documented command starts backend and frontend with the intended profile, region and source. Dependency installation includes browser-login support (`botocore[crt]`). Missing/expired credentials produce actionable errors; backend mode never falls back to examples. Restart and reconnect are verified. | Person 2: backend/runtime; Person 3: launch documentation and UI errors |
| 2. Historical data fit for forecasting | Retention and model compatibility need audit | Confirm how hourly observations persist across restart; fill retention gaps if needed. Preserve exact instance/AZ, units, effective and observation timestamps, source and gaps. Establish hourly sampling and history requirements. Check historical coverage against the model's training target. A regional minimum-price index must not silently substitute for a fixed instance/AZ series. | Person 1: data/target; Person 2: ingestion/storage |
| 3. Explicit capacity scenarios | Replay capacity exists; live-price hybrid not implemented | Use the existing deterministic replay path first. Define seeded capacity by compatible pool and hour, competing jobs and shortages. Keep AWS `availableUnits` unknown. Any later hybrid of observed prices and simulated capacity has a separate explicit mode and per-field provenance; it must not relabel the whole scenario as observed. Shared reservations prevent over-allocation, GPU models cannot be mixed, and reset reproduces results. | Person 2: scenario and engine; Person 3: mode/provenance display |
| 4. Complete baseline scheduling demonstration | APIs connected; full walkthrough pending | Demonstrate arrival → persistence forecast → constrained decision → explanation → simulated outcome. Cover waiting, deadline pressure, contention, hardware alternatives and infeasibility. Show backend-issued costs, slack and supplied risk; predicted cost remains distinct from realized spend. Verify the browser flow. | Person 2: correctness; Person 3: walkthrough |
| 5. Reproducible baseline benchmark | Replay/accounting integration verified; saved benchmark pending | Run FIFO, CHEAPEST_NOW and OPTIMIZER_WITH_NAIVE_FORECAST on identical jobs, realized prices, capacity and shocks. Save scenario, seed, configuration and results. Include spend, completions, missed deadlines, failures and unfinished jobs. Disclose different completed workloads. Repeat the run to verify reproducibility. ML remains unavailable until connected. | Person 2: replay/accounting; Person 1: evaluation design; Person 3: results |
| 6. Genuine local execution | Earlier backend smoke verified; current UI/Mac run pending | With an available Docker daemon, run an allowlisted CPU task and verify start/completion timestamps, output, exit code and failure reporting. Label it LOCAL. Keep local resources separate from simulated regional GPU pools; a CPU container does not prove a GPU job ran. | Person 2: execution; Person 3: monitoring verification |
| 7. Model handoff contract | Forecast protocol exists; artifact/data handoff pending | Agree on prediction target, identifiers, history window, units, UTC hourly alignment, 1–6 hour horizons, model artifacts and dependencies. Exercise the existing forecast interface with the baseline before loading ML. Define missing-history, unsupported-market and inference-failure behavior; any fallback is explicit. Retain issue time/model version and only supplied uncertainty/risk. | Person 1 + Person 2; Person 3 verifies display |

## Order and readiness gate

Start with milestones 1–3 and agree milestone 7 in parallel. Then finish the
baseline walkthrough and benchmark. Genuine Docker execution can proceed
independently; it is a demo requirement, not a technical prerequisite for loading ML.

Ready to plug in ML means the target/history match the model, the forecast
interface and failure behavior are agreed, and a reproducible baseline run exists.
Do not wait for weeks of fresh observations if suitable, validated historical data
already exists. Do not assume the earlier model's artifacts or training data are
present on this branch.

After integration, compare ML against persistence on chronological held-out data
and compare both forecast providers through the same optimizer and replay inputs.
Report MAE/RMSE and scheduling outcomes even when ML fails to improve them.

## Separate later scope: actual cloud allocation

Cloud allocation is not required to evaluate forecasts or demonstrate constrained
scheduling in an explicitly simulated scenario. It is required before claiming
the system actually buys and runs AWS compute.

That work needs exact whole-instance/AZ commitments, project/quota compatibility,
an authorized provisioning adapter, confirmed allocations, rejection/retry/replan
handling, monitoring, interruption handling and cost accounting. Placement scores
can supplement availability evidence; they are not counts, reservations or calibrated
probabilities and must not be converted into available GPU units.

The current project uses AWS's new experience with selected region `eu-north-1`.
Access to additional regions must be verified before promising a live multi-region
feed or deployment. Multi-region simulated replay remains a separate capability.
