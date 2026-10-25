# Flexible and mixed-deadline experiment

Completed **27 fixed input cases × three policy variants × four scheduling
strategies × two repeats = 648 simulated policy replays**. Every repeated full
state and official metric matches exactly. All source, ledger and hindsight
audits passed. The active localhost policy is unchanged.

Longer deadlines did not establish an ML cost advantage in these fixed pools.
The hindsight diagnostic found little price-only opportunity even before
accounting for competition for GPUs.

## Frozen inputs

- Three 48-hour periods beginning October 3, 9 and 15, 2026, UTC, each with
  168 prior hours for warm-up. No dates were chosen for their scheduling savings.
- Observed T4/g4dn.xlarge/eu-north-1a and A10G/g5.xlarge/eu-north-1b prices,
  Linux/UNIX, one GPU per instance. Model weights are unchanged.
- Jobs and constant one-GPU capacity per pool are **SIMULATED**. These profiles
  are illustrative, not a real firm's workload trace. No verified interchangeable
  hardware or additional regional sources were supplied; routing remains untested.
- Seeds 42/43/44; durations 1–3 hours. Arrivals stop 24 hours before the horizon
  ends so every job receives its full completion window.
- Forecasts remain limited to six future hours; long deadlines do not create
  unsupported 24-hour ML predictions. These dates were previously used in model
  development/evaluation, so this is not fresh held-out accuracy evidence.

| Profile | Arrivals per pool | Completion windows | Jobs per case |
| --- | --- | --- | ---: |
| Flexible | Every 4 hours | 24 hours | 14 |
| Mixed | Every 4 hours | Seeded cycle of 3, 12 and 24 hours | 14 |
| Busy mixed | Every 2 hours | Seeded cycle of 3, 12 and 24 hours | 26 |

Each profile has nine cases, totaling 486 case-specific jobs per variant.
Scenario bundles, model artifacts and engine code are identical across variants;
only the declared policy configurations differ. All variants were fixed before
scoring, all outcomes are retained, and none was automatically promoted.

| Variant | Waiting policy | Absolute margin per hour | Relative margin per hour | Normal speculative allowance |
| --- | --- | ---: | ---: | ---: |
| Legacy | LEGACY | None | None | Legacy behavior |
| Cautious | CAUTIOUS | $0.01 | 2% | 1 hour |
| Flexible margin | CAUTIOUS | $0.001 | 1% | 4 hours |

Cautious variants use the larger margin and preserve half the original slack;
their backlog preference remains active. Forced waits remain possible. These
are heuristic operator preferences, not calibrated uncertainty estimates.

## Results

FIFO, cheapest-now and persistence tie throughout: **$184.6857, 462 completed
jobs and 24 missed deadlines**. All missed jobs are infeasible; there are no
failed or unfinished jobs. Missed/infeasible counts overlap.

| ML variant | Simulated spend | Completed / submitted | Missed | Comparable cases vs FIFO |
| --- | ---: | ---: | ---: | ---: |
| Legacy | $187.7344 | 460 / 486 | 26 | 15 / 27 |
| Cautious | $184.6857 | 462 / 486 | 24 | 27 / 27 |
| Flexible margin | $184.6857 | 462 / 486 | 24 | 27 / 27 |

Both cautious variants tie baseline cost and outcomes in all cases. Legacy ML
has five cost wins, one tie and nine losses in its 15 comparable cases, totaling
$0.0448 additional expenditure on that subset. Twelve cases complete different
job sets; unconditional aggregate savings remains unavailable.

On the pure flexible profile, legacy ML completes all 126 jobs but costs $50.3922
versus the baseline's $50.3234. It completes 121 versus 126 jobs in mixed cases,
and 213 versus 210 in busy-mixed cases. These differences are retained; spend
alone cannot describe performance.

## Hindsight price opportunity

This diagnostic runs only after policy replay. It uses realized future prices
to minimize each submitted job independently, ignoring GPU competition. It is
an optimistic lower bound, **not an executable plan, forecast or achievable
portfolio saving**, and is never supplied to scheduling policies.

| Independent computation across all 486 jobs | USD |
| --- | ---: |
| Run each job at arrival, ignoring competition | $199.7057 |
| Best individual windows across full deadlines, ignoring competition | $198.9793 |
| Potential price reduction with at most one hour of delay | $0.0791 |
| Potential price reduction within six-hour priced windows | $0.2547 |
| Potential price reduction across full completion windows | $0.7264 |

The full-window difference is about 0.36% of the independent arrival calculation.
It prices **all 486 jobs**, whereas the real baselines complete 462: comparing
$198.9793 directly with their $184.6857 would be invalid. Shared-capacity
constraints can further reduce available opportunity.

These specific pools and periods offer little price-only timing opportunity.
Changing completion windows alone does not demonstrate ML scheduling value.
This does not settle the value of verified comparable pool choices or actual
customer workload traces.

## Evidence and reproduction

- [Combined comparison and audits](../data/flexible-workload-comparison.json)
- [Legacy design](../data/flexible-workload-legacy-design.json) and [results](../data/flexible-workload-legacy-results.json)
- [Cautious design](../data/flexible-workload-cautious-design.json) and [results](../data/flexible-workload-cautious-results.json)
- [Flexible-margin design](../data/flexible-workload-flexible-margin-design.json) and [results](../data/flexible-workload-flexible-margin-results.json)

Full scenarios, frozen inputs, repeated databases/states and reports are under
ignored `data/processed/flexible-workload-*-001/`. Each variant's audit checked
11,664 scenario price rows, 1,944 job outcomes and 486 hindsight job bounds
against original source prices. All unmatched outcomes remain explicit.

From `backend/`, with a fresh output directory:

```powershell
.\.venv\Scripts\python.exe -m app.engine.fair_benchmark --dataset ../data/processed/hourly-prices-hardware-v3-001 --design ../data/flexible-workload-flexible-margin-design.json --output ../data/processed/flexible-margin-NEW
.\.venv\Scripts\python.exe scripts/audit_fair_benchmark.py --suite ../data/processed/flexible-margin-NEW --dataset ../data/processed/hourly-prices-hardware-v3-001
```

Use `.venv/bin/python` on macOS/Linux. Verification: 188 backend engine/API tests
passed, followed by 12 focused tests after audit extensions. Tests check mixed
window cutoff/reproducibility and reject fabricated hindsight totals. No frontend
code or active policy changed in this task; frontend compilation was not rerun.
