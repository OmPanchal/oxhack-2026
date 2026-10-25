# Cautious waiting policy

The scheduler now supports an explicit `CAUTIOUS` waiting policy. Model weights,
features, training and risk estimates are unchanged. The original `LEGACY`
policy and all original benchmark artifacts remain available.

## Rules frozen before evaluating the change

The new planning score discourages delay by the larger of **$0.01 or 2% of the
earliest feasible plan's cost per additional hour**. Speculative delay normally
stays within one hour and half the job's original deadline slack. The allowance
is anchored to arrival time, so replanning does not grant another hour each tick.
When another compatible, deadline-feasible job is already queued, additional
delay receives a stronger penalty to favor keeping ready capacity busy.

These are conservative operator preferences, not calibrated uncertainty or
failure probabilities. They can suppress small genuine savings. They were not
tuned after examining the revised-policy evaluation results.

All candidate windows remain available: capacity, budgets or admission of other
known workloads may force waiting. Admission and existing deadline-risk ordering
still precede the planning score. Running reservations, hardware compatibility,
budgets and deadlines retain their original hard checks. No future arrivals or
realized future prices are supplied to the scheduler.

**Planning penalties are not charges.** Budget checks and projected cost
breakdowns still use actual estimated expenditure; replay charges still use
observed realized prices. Decision explanations identify the cautious policy.

## Evaluation

The paired evaluation uses October **13, 19 and 23**, with the same three workload
profiles and seeds 42/43/44: 27 cases per policy. These scheduling windows were
chosen before scoring the change, but their prices were already used in model
evaluation. This is not fresh held-out forecasting evidence. Models, code,
scenario bundles and workloads match across variants; only `waitingPolicy`
differs. Both variants ran twice with 24-hour versus single-hour stepping.

| On the new 27-case grid | Completed / submitted | Missed deadlines | Simulated spend | Idle pool-hours with ready work |
| --- | ---: | ---: | ---: | ---: |
| FIFO / cheapest-now | 444 / 468 | 24 | $164.4093 | — |
| ML with legacy waiting | 408 / 468 | 60 | $142.5102 | 400 |
| ML with cautious waiting | 444 / 468 | 24 | $164.4093 | 0 |

The cautious ML optimizer matches baseline completed job IDs and lifecycle/
deadline outcomes in all 27 cases, and ties their cost in every case. Its higher
spend than legacy ML is associated with more completed work, not a like-for-like
cost regression. This fixes the additional ML completion losses in this sample;
it does **not** demonstrate incremental ML savings.

The old, already opened 27-case benchmark was also rerun as a development
regression: cautious ML completes 444 jobs versus the original legacy ML's 411,
matching baseline outcomes and $167.8166 spend. Idle ready pool-hours fall from
350 to zero. The original negative results were not overwritten.

All three suites reproduced exact full states and official metrics. The separate
source/ledger audit passed for each. The paired control check verified identical
scenario bundles and engine code across all 27 evaluation cases, with only the
waiting-policy setting changed.

## Evidence

- [Paired comparison and audit summaries](../data/waiting-policy-comparison.json)
- [Legacy evaluation results](../data/waiting-policy-evaluation-legacy-results.json)
- [Cautious evaluation results](../data/waiting-policy-evaluation-cautious-results.json)
- [Original-grid cautious regression](../data/waiting-policy-regression-results.json)
- [Legacy evaluation design](../data/waiting-policy-legacy-design.json)
- [Cautious evaluation design](../data/waiting-policy-cautious-design.json)

Full scenarios, input receipts, repeated SQLite databases and full replay views
remain in `data/processed/waiting-policy-*-001/` (Git-ignored). Prices are observed;
workloads and capacity are simulated, with no interruptions or paid execution.

## Activation and reproduction

`./dev` now selects CAUTIOUS unless `COMPUTE_WAITING_POLICY` explicitly overrides
it. Direct FastAPI startup and standalone default benchmark configuration retain
LEGACY for compatibility. For direct Windows startup, set:

```powershell
$env:COMPUTE_WAITING_POLICY = 'CAUTIOUS'
```

Changing the deployment policy requires a replay reset; an existing session is
never silently relabeled. The active localhost backend has been restarted with
CAUTIOUS. Its historical replay was reset and verified through the frontend
proxy: all policies complete ten jobs for $2.6348, and ML decisions report
`CAUTIOUS_WAITING_POLICY`.

From `backend/`, reproduce with a new output directory:

```powershell
.\.venv\Scripts\python.exe -m app.engine.fair_benchmark --dataset ../data/processed/hourly-prices-hardware-v3-001 --design ../data/waiting-policy-cautious-design.json --output ../data/processed/cautious-NEW
.\.venv\Scripts\python.exe scripts/audit_fair_benchmark.py --suite ../data/processed/cautious-NEW --dataset ../data/processed/hourly-prices-hardware-v3-001
```

Use the legacy design for the paired control, or the regression design for the
old grid. Use `.venv/bin/python` on macOS/Linux.

## Checks and limits

185 backend engine/API regressions passed, followed by three deployment API
tests including the new setting propagation check. Tests cover negligible
savings, meaningful short waits, cumulative slack, queued workloads, forced
budget/capacity waits and projected costs excluding planning penalties. Existing
legacy tests and optimizer oracle were retained.

The standalone launcher suite had four passes and one existing Windows platform
error (`os.killpg`, unsupported on Windows); `./dev` remains a macOS/Linux launcher.
The running Windows manual startup and real frontend proxy check succeeded.
No frontend code changed in this task, so its build was not rerun. Further
evaluation on different workloads and newly collected data remains necessary.
