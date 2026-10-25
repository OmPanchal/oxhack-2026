# Saved production-engine benchmark

This is the preserved **legacy waiting-policy** benchmark. A later
[cautious waiting change](CAUTIOUS_WAITING.md) addresses its additional ML
completion losses and reports a separate paired evaluation. The figures below
remain unchanged.

A subsequent [flexible/mixed-deadline experiment](FLEXIBLE_WORKLOAD_EXPERIMENT.md)
tests longer completion windows and three fixed policies, with a labeled
hindsight price diagnostic. Its results are saved separately.

The frozen suite ran **27 cases, four policies and two repeats**: 216 policy
replays over 468 case-specific workload instances. All repeated official metrics
and complete replay states matched exactly, including across 24-hour versus
single-hour stepping. Every scored ML version identifies the saved GPU LightGBM
model; no persistence fallback was counted as ML.

**There is no valid overall ML savings claim.** ML completes fewer jobs in this
suite. Its lower total expenditure must be read alongside the lost completions.

## Design and scope

[The frozen design](../data/fair-benchmark-design.json) specifies:

- October 12, 18 and 24, 2026, UTC; each scored window is 24 hours, with 168 prior
  hours loaded for warm-up. Dates are fixed six-day intervals, not selected for
  savings. October 24 / relaxed / seed 42 had already been evaluated separately.
- Three profiles: relaxed (arrivals every four hours, six-hour completion window),
  contended (every two hours, six-hour window), and urgent (every two hours,
  three-hour window). Durations are 1–3 hours; workload seeds are 42, 43 and 44.
- Observed T4/g4dn.xlarge/eu-north-1a and A10G/g5.xlarge/eu-north-1b prices,
  Linux/UNIX. Both source instances have one GPU. Dataset SHA-256:
  `618ed38329ec8b4934c7fd40a0e77e61b3dcd9d3850b2df87299af5827903a36`.
- Workloads and constant one-GPU capacity per pool are **SIMULATED**. No
  interruptions, recovery, transfers or real cloud execution are included.
- All four strategies receive identical requirements, arrivals and realized
  prices/capacity, with independent state. Future prices and arrivals are not
  supplied to policies. No model or optimizer tuning occurred during this suite.

Each job has one permitted GPU pool, so this measures scheduling over time,
not cross-region or alternative-hardware routing benefits. The dates were already
used in model evaluation. This is exploratory scheduling evidence, not a new
blind accuracy test, production guarantee or live cloud saving.

## Overall outcomes

| Policy | Simulated spend | Completed | Infeasible | Missed deadlines | Failed | Unfinished |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FIFO | $167.8166 | 444 | 24 | 24 | 0 | 0 |
| Cheapest now | $167.8166 | 444 | 24 | 24 | 0 | 0 |
| Optimizer / persistence | $167.8166 | 444 | 24 | 24 | 0 | 0 |
| Optimizer / ML | $149.2914 | 411 | 57 | 57 | 0 | 0 |

Missed deadlines overlap infeasible jobs; they are not additional disjoint
outcomes. ML completes 33 fewer jobs. Overall savings fields are therefore null,
despite the $18.5252 raw expenditure difference.

Against each baseline, ML has **11 comparable cases: seven cheaper, four more
expensive, zero ties**. The remaining 16 cases have different completed workload
IDs and are retained explicitly. The comparable-only cost difference is $0.0927
in ML's favor; this conditional subset must not be presented as overall savings.

## Results by profile

Each profile includes all three dates and all three seeds (nine cases).

| Profile | Baseline spend | Baseline completed | ML spend | ML completed | Comparable cases | ML wins / losses in comparable cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Relaxed | $31.6241 | 90 | $31.5333 | 90 | 9 | 6 / 3 |
| Contended | $70.7054 | 177 | $61.7418 | 164 | 2 | 1 / 1 |
| Urgent | $65.4871 | 177 | $56.0163 | 157 | 0 | — |

All relaxed cases complete identical work, with $0.0908 lower ML spend in total.
This is a profile-conditional result, not a claim that ML always wins. Completion
losses under contention and urgent deadlines need a separate scheduling-policy
investigation; this benchmark preserves the current policy and its failures.

## Saved evidence and safeguards

- [Tracked results](../data/fair-benchmark-results.json): frozen design,
  provenance, all 27 cases, exact completed/failed/infeasible/missed/unfinished job
  IDs, model versions, costs, comparison reasons, win/tie/loss counts and totals.
- [Independent audit](../data/fair-benchmark-audit.json): 10,368 scenario price
  rows matched to original observations; 1,872 policy job outcomes, 1,743 started
  executions and 3,297 charged hours checked. Full repeated states are identical;
  engine source hashes are unchanged across cases.
- Ignored `data/processed/fair-benchmark-001/`: inputs saved before scoring,
  every scenario, each case's full report, both SQLite databases, both complete
  replay states, package versions, model receipt and optimizer/code fingerprints.

The runner uses the existing production `ReplayService`, optimizer, policy and
accounting implementations. It does not substitute the older offline planner.
Missing/error strategies or non-genuine ML abort the suite and leave an explicit
incomplete-run receipt. The output directory must be new; prior results are never
overwritten. Aggregate savings are emitted only if every case has matching work
and lifecycle/deadline outcomes. Negative comparable savings are retained.

The separate audit reads original dataset prices rather than forecast output,
checks capacity/windows/hardware and charges, and verifies every expected grid
case is present. A regression corrupts both repeated charge ledgers identically
and confirms that this audit still rejects them.

## Reproduce

From `backend/`, with the project's ML dependencies installed and the original
prepared dataset available (Windows commands):

```powershell
.\.venv\Scripts\python.exe -m app.engine.fair_benchmark --dataset ../data/processed/hourly-prices-hardware-v3-001 --output ../data/processed/fair-benchmark-NEW
.\.venv\Scripts\python.exe scripts/audit_fair_benchmark.py --suite ../data/processed/fair-benchmark-NEW --dataset ../data/processed/hourly-prices-hardware-v3-001
```

Use `.venv/bin/python` on macOS/Linux. Repeated runs on these same dates are
reproductions, not new held-out experiments. The saved design supports an
explicitly chosen alternative file via `--design`; disclose changes before
viewing their results.

Verification: **181 backend engine/API tests passed**. After adding the independent
audit corruption regression, the ten focused historical/benchmark tests passed
again. The existing Starlette/httpx deprecation warning remains. This task changed
backend benchmarking and evidence only; frontend compilation was not rerun.
