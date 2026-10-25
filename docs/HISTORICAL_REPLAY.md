# Historical replay using the production engine

The replay importer, warm-up support, catalog/UI and benchmark runner are
implemented. The user transferred `hourly-prices-hardware-v3-001.zip` into
`data/processed/`; its 444,288 observed rows / 208 series match the previously
recorded dataset hash `618ed38329ec8b4934c7fd40a0e77e61b3dcd9d3850b2df87299af5827903a36`.
The archive and extracted dataset remain Git-ignored. A fresh checkout still
needs that transfer and import; missing data is reported explicitly.

## Recorded result — 25 October 2026

The single-day result below is preserved. A subsequent [27-case fair benchmark](FAIR_BENCHMARK.md)
now compares three fixed dates, three workload profiles and three seeds using the
same production engine and saved model. Its completion differences prevent an
overall ML savings claim.

The frozen 24-hour replay ran twice with identical full replay states and
official metrics. It also ran through the actual Next.js proxy/FastAPI process;
those metrics match the saved benchmark exactly. All four strategies completed
the same ten job IDs, with zero failures, infeasible jobs, missed deadlines or
unfinished jobs.

| Policy | Simulated spend |
| --- | ---: |
| FIFO | $2.6348 |
| Cheapest now | $2.6348 |
| Optimizer / persistence | $2.6348 |
| Optimizer / ML | $2.6391 |

**ML costs $0.0043 (0.1632%) more in this window.** This is a valid negative
result, retained without changing the model, workloads or selected date. Every
scored ML version is `lightgbm-price-l1-v1-gpu-734be7a557de`; no persistence
fallback entered the scored run. The result does not establish a broad benefit
or loss across other workloads/dates.

[Tracked results](../data/historical-replay-results.json) and the
[audit receipt](../data/historical-replay-audit.json) retain outcomes and scope.
The source audit matched all 384 selected warm-up/scored prices to the original
observed dataset and verified all 40 policy executions / 68 charged hours,
hardware, shared capacity, windows, deadlines and charge amounts. The full inputs,
repeated SQLite sessions and replay views are retained under ignored
`data/processed/historical-benchmark-001/`.

## Fixed experiment

[The saved design](../data/historical-replay-design.json) was written before
running real-data scheduling comparisons. It chooses October 24, 2026, UTC,
and the already configured Stockholm T4 and A10G source pools. These dates have
already been used in model evaluation; this is not a fresh accuracy holdout.
The design does not select a window based on its scheduling savings.

- Price inputs: observed slot-start prices for g4dn.xlarge / eu-north-1a and
  g5.xlarge / eu-north-1b, Linux/UNIX, one GPU per instance.
- Warm-up: October 17–23 inclusive, 168 hours. No workloads or charges are
  generated for these hours. Reset starts at slot 168; the first scored tick
  reveals that hour's quote and has all 169 required observations available.
- Scoring: October 24 `[00:00, October 25 00:00)` UTC, 24 hours.
- Capacity: **SIMULATED**, constant one GPU per fixed pool. Availability is not
  inferred from historical prices or asserted to be AWS inventory.
- Workloads: **SIMULATED**, seed 42, arrivals every four hours while a full
  six-hour completion window remains; durations 1–3 hours; one specified GPU.
- All four production policies use identical inputs and independent state.
  The selected ML provider receives only history through the current tick.
- No interruptions, retries, actual executions or paid cloud resources.

Combined market rows are `SIMULATED` because they include synthetic capacity.
Their source strings retain the observed price pool and dataset hash. Typed
provenance separately identifies observed prices and synthetic capacity/jobs.
Injecting a price shock changes provenance to `OBSERVED_WITH_SIMULATED_SHOCKS`.

## Prepare real data

Obtain the original prepared `hourly-prices-hardware-v3-001` directory from the
teammate who collected it. It must include `manifest.json` and the matching
`hourly-prices.jsonl`, preserving exact bytes and hashes. The tracked simulated
examples and compact result summaries cannot replace this dataset.

From `backend/`, using the backend Python environment with the ML extra:

```powershell
.\.venv\Scripts\python.exe -m app.engine.historical_replay prepare --dataset 'C:\path\to\hourly-prices-hardware-v3-001'
```

macOS/Linux: use `.venv/bin/python` instead. The default output is
`data/processed/historical-replay/scenario.json`. Existing output directories
are rejected. `--output` and `--design` support explicitly selected alternatives.

The importer verifies the source dataset checksum, exact instance/AZ identity,
whole-instance granularity, USD/GPU-hour conversion, UTC boundaries, complete
warm-up/scored coverage and model availability. Simulated source datasets,
missing hours and unsupported zero-price inference are rejected. No model is
retrained. A bundle receipt binds its scenario, design, serving configuration
and selected model artifact receipt.

Restart the backend after preparing the bundle. Its default registry discovers
that file; `COMPUTE_HISTORICAL_REPLAY_FILE` can name an alternative server-owned
bundle. Invalid or missing data leaves the other scenarios operational and
marks historical replay unavailable. `/api/replay/scenarios` reports availability.
Enable the provider with `COMPUTE_ENABLE_ML=1` (or `./dev --ml` on macOS/Linux).

In Replay, choose **Historical T4/A10G**, Reset, then Step or Play. The 168 warm-up
hours are already loaded and excluded from the displayed 0/24-hour progress.
Expand **Historical data and assumptions** to inspect provenance.

## Save a fair benchmark

```powershell
.\.venv\Scripts\python.exe -m app.engine.historical_replay benchmark --output '..\data\processed\historical-benchmark-001'
```

This runs `ReplayService`, its existing optimizer, policies and accounting—not
the earlier separate offline planner. It saves frozen inputs, seed, optimizer
configuration and engine code hashes **before scoring**, then runs two isolated
SQLite sessions. Official metrics must reproduce exactly. All strategies must
remain active and every scored ML model version must identify genuine saved-model
inference; fallback-only or mixed runs cannot become this benchmark report.

Outputs include `inputs.json`, both SQLite sessions, both complete replay views,
and `report.json`. They retain costs, completed job IDs, failures, infeasibility,
missed deadlines, unfinished work, model versions and backend comparison guards.
Losses remain losses. Neither equal counts nor lower raw spend automatically
becomes a savings claim. Savings need not be positive for a valid experiment.

## Verification scope

Synthetic test data exercises importer rejection, warm-up boundaries, genuine
saved-model inference, future-price perturbation safety, restart persistence,
official reconciliation and duplicate-run reproducibility. Test prices are
synthetic even in tests of the `OBSERVED` validation branch. These checks establish
software behavior, not historical model accuracy or scheduling savings.

Final checks: 179 backend engine/API tests passed; 42 frontend tests passed;
production frontend build passed. Browser inspection verified historical scenario
registration, 24/24 scored-hour progress, price/capacity provenance, genuine ML
labels and final policy outcomes. The existing Starlette/httpx warning remains.
