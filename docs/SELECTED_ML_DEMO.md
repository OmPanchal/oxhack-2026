# Selected ML success example

Localhost update: the backend has now been restarted with this selected bundle
and LEGACY waiting, reset with seed 44, and run to completion through the frontend
proxy. Refresh Policy comparison to see the totals below. This startup setting
also selects LEGACY for live optimization; restore CAUTIOUS after the demo.
The bundle's original disclosure refers to the usual cautious configuration,
rather than these temporary demo settings.

This example was **chosen retrospectively because ML won**. It is a demonstration
of a useful decision, not representative performance or a new fair benchmark.
The full results, including losses, remain in
[FLEXIBLE_WORKLOAD_EXPERIMENT.md](FLEXIBLE_WORKLOAD_EXPERIMENT.md).

It uses genuine trained LightGBM inference, observed historical prices, and
simulated jobs/capacity. Prices, jobs, predictions and accounting were not altered
to manufacture the result. No future prices are given to policies. This is not
cloud execution, and these dates are not a fresh held-out evaluation period.

## Verified result

Selected case: `20261015T00-flexible-seed-44`, from the existing 27-case legacy
flexible-workload suite. October 15–16, 2026 UTC; 168-hour prior warm-up; 14 jobs
lasting 1–3 hours with 24-hour completion windows. Fixed T4 and A10G price pools,
one simulated GPU each. Both repeats completed the same 14 jobs for every policy,
with no missed deadlines, failures or unfinished jobs.

| Strategy | Simulated realized expenditure |
| --- | ---: |
| FIFO | $4.8115 |
| Cheapest now | $4.8115 |
| Optimizer with persistence | $4.8115 |
| Optimizer with ML | $4.7819 |

ML saves **$0.0296 (0.615193%)** against each baseline in this selected case.
The model version is `lightgbm-price-l1-v1-gpu-734be7a557de` throughout.
The complete states and official metrics match exactly between runs stepping
24 hours and one hour at a time.

This uses **LEGACY waiting**, which allows small predicted savings to justify
substantial delays. The active localhost policy remains CAUTIOUS, which tied the
baselines in the larger experiments. This demo does not justify switching the
general policy back: legacy missed more work elsewhere.

## Reproduce

From `backend/`, using a fresh output path:

```powershell
.\.venv\Scripts\python.exe scripts/run_selected_ml_demo.py --output ../data/processed/selected-ml-demo-003
```

The original suite scenario must exist at
`data/processed/flexible-workload-legacy-001/scenarios/20261015T00-flexible-seed-44.json`.
The runner validates its bundle and model receipt, adds the selection disclosure,
and runs the production replay twice. It fails if ML is not genuine throughout,
states differ, completed workloads differ, or ML does not beat all three baselines.
It does not alter the original benchmark or running server.

Fresh evidence is in `data/processed/selected-ml-demo-002/`: `scenario.json`,
`summary.json`, and `replay/` containing input receipts, both SQLite databases,
both complete states, and the official report. These large files are Git-ignored.
The compact [saved result](../data/selected-ml-demo-results.json) includes per-job
charged slots and costs, including jobs where ML paid more.

To inspect this case in the existing UI, a backend can be started with:

```powershell
$env:COMPUTE_ENABLE_ML = '1'
$env:COMPUTE_WAITING_POLICY = 'LEGACY'
$env:COMPUTE_HISTORICAL_REPLAY_FILE = 'C:\Users\trish\Downloads\oxhack-2026\data\processed\selected-ml-demo-002\scenario.json'
```

These are startup settings, not changes to a running server. Start the backend
using the usual instructions; select historical replay and reset with seed **44**.
The description carries the selection disclosure. Restore CAUTIOUS and the
normal historical bundle after the demo, restart and reset replay. Never label
an old saved replay as having run with a newly selected configuration.

## Pitch wording

“Here is a selected historical example showing the mechanism. The model forecasts
future prices, and the scheduler can wait while respecting the deadline. All four
strategies finish the same 14 simulated jobs. Here ML saves about 0.62%. Across
the broader benchmark it does not consistently outperform the simpler policies.”

Do not describe this as a large saving, a synthetic price-drop experiment,
production cloud savings, or evidence of general superiority.
