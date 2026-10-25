# Current merge update — 25 October 2026

The ML branch now supplies selected LightGBM artifacts and a serving contract.
The integration rebases clocks, maps GPU identifiers and preserves fixed source
identities; see [the current README](../README.md) and
[model serving](../data/forecast-serving.md). Older statements below that artifacts
are absent describe the earlier pre-merge audit. Automatic live history loading now supplies the required window for the
current T4/A10G demo pools. Fresh held-out evaluation remains outstanding. The saved evaluation remains
exploratory post-holdout, and simulated replay is not live cloud execution.

# Arbitr: readiness before ML integration

Updated 25 October 2026. This is a delivery plan, not authorization to provision
cloud resources or change another developer's owned modules.

## Verified starting point

- Live AWS ingestion works with profile `arbitr` in `eu-north-1`; the frontend
  proxy returned five observed Spot quotes for T4/A10G and two regional price indices.
- The default backend uses persistence; `./dev --ml` enables the selected model
  provider with explicit fallbacks and preserves unknown AWS capacity. Prices alone do not enable allocation.
- Job creation/persistence, GPU alternatives, decision evidence, seeded replay,
  shocks and policy accounting have integration evidence; see
  [the integration audit](../frontend/INTEGRATION.md). Those checks used simulated
  market data and do not establish real cloud execution or model quality.
- Earlier backend milestone reports document genuine LOCAL Docker smoke runs.
  Execution has not been repeated through the current frontend on this Mac.

## Milestones

| Milestone | Status | Definition of done | Ownership |
| --- | --- | --- | --- |
| 1. Reliable live-data startup | Complete for current macOS setup; verified 25 October 2026 | A documented command starts backend and frontend with the intended profile, region and source. Dependency installation includes browser-login support (`botocore[crt]`). Missing/expired credentials produce actionable errors; backend mode never falls back to examples. Restart and reconnect are verified. | Person 2: backend/runtime; Person 3: launch documentation and UI errors |
| 2. Historical data fit for forecasting | Complete for current T4/A10G live inputs: automatic backfill, gap recovery, identity/receipt checks and genuine inference verified | Confirm how hourly observations persist across restart; fill retention gaps if needed. Preserve exact instance/AZ, units, effective and observation timestamps, source and gaps. Establish hourly sampling and history requirements. Check historical coverage against the model's training target. A regional minimum-price index must not silently substitute for a fixed instance/AZ series. | Person 1: data/target; Person 2: ingestion/storage |
| 3. Explicit capacity scenarios | Complete for explicitly simulated replay; live-price hybrid remains separate | Use the existing deterministic replay path first. Define seeded capacity by compatible pool and hour, competing jobs and shortages. Keep AWS `availableUnits` unknown. Any later hybrid of observed prices and simulated capacity has a separate explicit mode and per-field provenance; it must not relabel the whole scenario as observed. Shared reservations prevent over-allocation, GPU models cannot be mixed, and reset reproduces results. | Person 2: scenario and engine; Person 3: mode/provenance display |
| 4. Complete baseline scheduling demonstration | APIs connected; full walkthrough pending | Demonstrate arrival → persistence forecast → constrained decision → explanation → simulated outcome. Cover waiting, deadline pressure, contention, hardware alternatives and infeasibility. Show backend-issued costs, slack and supplied risk; predicted cost remains distinct from realized spend. Verify the browser flow. | Person 2: correctness; Person 3: walkthrough |
| 5. Reproducible baseline benchmark | Replay/accounting integration verified; saved benchmark pending | Run FIFO, CHEAPEST_NOW and OPTIMIZER_WITH_NAIVE_FORECAST on identical jobs, realized prices, capacity and shocks. Save scenario, seed, configuration and results. Include spend, completions, missed deadlines, failures and unfinished jobs. Disclose different completed workloads. Repeat the run to verify reproducibility. ML availability/fallback versions must be disclosed per run. | Person 2: replay/accounting; Person 1: evaluation design; Person 3: results |
| 6. Genuine local execution | Earlier backend smoke verified; current UI/Mac run pending | With an available Docker daemon, run an allowlisted CPU task and verify start/completion timestamps, output, exit code and failure reporting. Label it LOCAL. Keep local resources separate from simulated regional GPU pools; a CPU container does not prove a GPU job ran. | Person 2: execution; Person 3: monitoring verification |
| 7. Model handoff contract | Selected artifacts, 169-hour input contract and clock/GPU/source adapters integrated | Agree on prediction target, identifiers, history window, units, UTC hourly alignment, 1–6 hour horizons, model artifacts and dependencies. Exercise the existing forecast interface with the baseline before loading ML. Define missing-history, unsupported-market and inference-failure behavior; any fallback is explicit. Retain issue time/model version and only supplied uncertainty/risk. | Person 1 + Person 2; Person 3 verifies display |

## Price-history audit and implementation — 25 October 2026

The existing hourly regional index survives restarts but overwrites same-hour
values; exact instance/AZ quotes previously existed only in memory. Added durable
quote batches, receipt timestamps and a read-only hourly export with gap reporting
and point-in-time filtering. See [PRICE_HISTORY.md](PRICE_HISTORY.md).
The scheduler's existing index and public API remain unchanged. Six added tests
cover restart/deduplication, cutoff safety, gaps/series separation, invalid times,
legacy inspection and API archival. Backend suite: 180 passed, 1 skipped.
That pre-merge audit had no trained artifacts. The ML merge now supplies selected
weights and the fixed-pool/169-hour contract; automatic backfill now supplies the live window; a fresh held-out evaluation
remains pending.

## Reliable startup verification — 25 October 2026

Implemented root `./dev` with `--setup`, `--login`, and `--check`; see
[STARTUP.md](STARTUP.md). Verified a normal launch with actual AWS quotes through
Next.js, Ctrl+C stopping both listeners, first-time dependency installation in
`backend/.venv`, and repeat launch using that environment. Five startup regressions
pass. The fresh environment's backend suite reports 174 passed / 1 skipped.
Browser reauthentication was verified earlier during project setup; the new
`--login` branch invokes that same CLI flow and has not forced a new browser login.
Runtime API errors remain visible; no automatic crash restart or continuous
browser-session renewal is implemented.

## Capacity-scenario verification — 25 October 2026

Registered the eight-hour `capacity-pressure` scenario and added a named UI
selector plus last-observed pool capacity. See [CAPACITY_SCENARIOS.md](CAPACITY_SCENARIOS.md).
Verified shared reservations, single-model GPU alternatives, routing, shortage
failures, waiting/recovery, deadlines, late arrivals, reproducible reset/shocks
across restart, no future forecasting input and isolation from live state.
Backend: 184 passed / 1 skipped. Frontend logic: 40 passed; production build
passed compilation, types and prerendering. Browser interaction
verification remains separate. A live-price/simulated-capacity hybrid is not part
of this completion and AWS inventory remains unknown.

## Order and readiness gate

Milestones 1 and 3 are now verified for their stated scopes. Milestone 2 has
verified retention/export but awaits model compatibility requirements. Agree
milestone 7 in parallel, then finish the baseline walkthrough and saved benchmark. Genuine Docker execution can proceed
independently; it is a demo requirement, not a technical prerequisite for loading ML.

Ready to plug in ML means the target/history match the model, the forecast
interface and failure behavior are agreed, and a reproducible baseline run exists.
Do not wait for weeks of fresh observations if suitable, validated historical data
already exists. The selected weights are now present; historical training datasets remain separate
from the small live archive.

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

## Automatic live inputs — 25 October 2026

Implemented automatic fixed instance/AZ backfill, persistent 168-hour historical
windows, new-hour/downtime recovery and explicit readiness/failure reporting.
Live verification: Stockholm T4/A10G both 168/168 prior hours; 336 saved samples
from two source fetches; 12 genuine LightGBM forecasts and no engine error.
Backfilled receipts are isolated from replay and never relabeled as earlier live
observations. See [automatic history](AUTOMATIC_HISTORY.md).

Checks: backend 360 passed / 1 skipped / 53 subtests passed; frontend 40 passed;
startup regressions 5 passed; production compilation/types/prerendering passed.
The remaining demo milestones are maintained in [README.md](../README.md).
