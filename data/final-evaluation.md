# Frozen final test and scheduling ablation

The fixed LightGBM recipe reduced final-test MAE **2.2267% for CPU** and
**1.1222% for GPU** versus persistence. The separate scheduling replay found
only **0.002596% incremental savings** from ML over the identical optimizer using
persistence: **USD 0.6606** on USD 25,450.3185 of simulated baseline expenditure.
This supports a modest predictive advantage, but not a material scheduling-cost
advantage under the frozen workload assumptions. No default or deployment changed.

## Freeze and test boundaries

The user authorized this final evaluation after development comparisons completed.
[The frozen design](final-evaluation-design.json) was written before opening final
scores. It fixes the dataset fingerprint, seed 42, 168-hour causal features,
separate CPU/GPU and per-horizon models, original LightGBM parameters and 50%
correction to persistence. It also freezes workload seeds and replay assumptions.
No candidate search, correction-weight selection or hardware exclusion occurred
after seeing final results.

- Dataset: 208 AZ/instance pools, one region, fingerprint
  `618ed38329ec8b4934c7fd40a0e77e61b3dcd9d3850b2df87299af5827903a36`.
- Training: `[2026-07-28T00:00:00Z,2026-09-18T09:00:00Z)`; 1,345,086 examples.
- Final test: `[2026-10-10T15:00:00Z,2026-10-24T00:00:00Z)`; 393,120 forecasts.
- Development and calibration labels were not added to training. Earlier observed
  prices can provide causal lag features when a final forecast is generated.
- All six targets at an origin stay inside the test partition; boundary-crossing
  origins are purged. Post-test rows are removed before example building.
- No uncertainty calibration or fitted interruption model was introduced.

The exact design and a start receipt were persisted before scoring. Final
evaluation ran once; subsequent audits recalculated saved errors and source
prices without retraining or selecting a different candidate.

**The final period is now evaluated. It cannot be called untouched for future
model tuning.** New tuning requires fresh evaluation data and another frozen design.

## Final forecast accuracy

All percentages are MAE reductions versus persistence, not dollar savings.

- **CPU:** 272,160 forecasts. MAE **0.000061279230 USD/vCPU-hour** versus
  **0.000062674782** for persistence, an improvement of **2.2267%**.
  RMSE **0.000109892230** versus **0.000112229680**.
  **138/144 pools improve; six worsen; none tie.** Two losing pools have zero
  baseline MAE, so their percentage improvements are undefined rather than hidden.
- **GPU:** 120,960 forecasts. MAE **0.004931313280 USD/GPU-hour** versus
  **0.004987280609**, an improvement of **1.1222%**.
  RMSE **0.014017823103** versus **0.014088982469**.
  **63/64 pools improve; one ties.** The tie is B200: all **1,890 B200 forecasts**
  use persistence because it lacks eligible history before the frozen training cutoff.

Final GPU-model MAE reductions, grouping observed instance sizes and AZs:

- T4: **3.6525%**.
- A10G: **2.2594%**.
- L4: **2.0446%**.
- L40S: **0.5534%**.
- A100: **0.9442%**.
- H100: **0.0287%**.
- H200: **0.6959%**.
- B200: **0%**, labeled persistence fallback rather than a trained B200 model.

Both resources pass the frozen aggregate-MAE success rule. That rule is a point
estimate comparison, not a statistical significance test or guarantee. Related
instance sizes, AZs and overlapping horizons are correlated; only Stockholm is
represented. Equal-weight mean per-pool improvement is 2.2991% for CPU (excluding
two undefined percentages) and 2.2970% for GPU. Absolute-error reporting retains
all pools, including those undefined relative scores.

The tracked [final forecast report](final-evaluation-results.json) contains all
resource, horizon, instance-type, pool and price-movement breakdowns. Independent
audits matched all 393,120 target and persistence values to the observed source
dataset, checked final-period boundaries, and recalculated aggregate MAE/RMSE.

## Scheduling benchmark and honest scope

The production optimizer, policy implementations and API replay routes were still
scaffolds. A separate [offline engine benchmark](../backend/app/engine/forecast_benchmark.py)
was added for this experiment; the original production modules and API remain
unchanged. The engine accepts quotes, current observations, jobs and reservations;
it imports neither ML models nor Docker.

The frozen replay uses nine instance types: g4dn.xlarge, g5.xlarge, g6.xlarge,
g6e.xlarge, p5.48xlarge, p6-b200.48xlarge, m5.xlarge, c6i.xlarge and r6i.xlarge.
Three workload seeds (42, 43, 44) produce 27 cases and **2,106 jobs**. Each
compatibility group receives two-job bursts every eight hours, durations 1–3
hours and six-hour deadlines. Allocations consume whole instances; jobs may route
among AZ pools of the exact same instance type, not across incompatible hardware.

The small exact planner jointly assigns pending jobs over quoted execution windows,
respecting arrivals, shared pool capacity, running reservations, non-preemption and
half-open deadlines. It maximizes feasible job count, then priority, then minimizes
quoted expenditure. Only allocations starting now are committed; future plans are
recomputed on the next tick. Running jobs are never duplicated or migrated.
This exhaustive implementation is appropriate for the frozen two-job bursts,
not a claim of production-scale optimization performance.

Both optimizer policies use exactly this planner. Only price forecasts change:
persistence versus the saved frozen ML forecasts generated at that tick. FIFO
uses a stable pool order; cheapest-now starts immediately at the cheapest feasible
observed pool. No policy sees actual future prices or future job arrivals. Final
forecast boundary coverage limits the replay to slots `[1791,2106)`; arrivals stop
six hours before the end so every generated deadline lies inside that interval.

**Prices are OBSERVED. Jobs and constant capacity are SIMULATED.** Capacity is one
whole instance per pool; there are no interruptions, startup/transfer charges or
recovery costs. Capacity is not inferred from price history. There was no Docker
or cloud execution and no money was actually spent. These assumptions materially
limit what can be concluded about real workloads, contention and reliability.

## Replay outcomes

Every policy completed the **same 2,106 job IDs**, with zero missed deadlines,
failed jobs and unfinished jobs under the stated assumptions. Hypothetical spend:

- FIFO: **USD 25,533.4502**.
- Cheapest-now: **USD 25,526.3718**.
- Optimizer with persistence: **USD 25,450.3185**.
- Optimizer with ML: **USD 25,449.6579**.

The ML optimizer reduced spend **0.3282% versus FIFO**, **0.3005% versus
cheapest-now**, and **0.002596% versus the persistence optimizer**. The last is the
relevant ML ablation: most of the benefit versus immediate execution comes from
scheduling itself, not the ML correction.

ML-versus-persistence savings by workload seed are **0.002295%, 0.003145% and
0.002356%**. Of 27 individual cases, 21 improve and six tie; none worsen. H100 and
B200 cases tie in all three seeds. Those expensive configurations dominate the
chosen expenditure mix. Other instance-type aggregates improve only about
0.050–0.102%, so excluding those expensive cases would still not establish a
large scheduling benefit.

The [complete replay report](final-replay-results.json) retains each policy's
spend, job outcomes, execution windows, projections and per-job actual costs.
An independent audit checked all **8,424 policy executions** for compatible pools,
whole-instance capacity, arrivals, deadlines, duplicate execution and observed
slot charges, then reconciled job/case/strategy totals. Identical completed-job
IDs were checked across all four policies rather than inferred from equal counts.

## Conclusion and validation

The model's modest accuracy advantage survived the frozen final test. The tested
workloads do not demonstrate a material incremental scheduling benefit from ML.
Keep the persistence default while evaluating representative workload slack,
capacity and execution-risk scenarios on fresh evidence; do not tune on this
opened final period and rebrand it as an independent test.

**145 forecasting/engine tests and 53 subtests passed.** New tests cover frozen
recipe guards, final boundaries, shared capacity, exact deadline completion,
missing quote coverage, running-job protection, deterministic independent policy
state, missed/unfinished accounting, reproducible workloads and adapter cost
reconciliation. No shared API schemas, production routes or defaults changed.

Artifacts are under ignored `data/processed/final-evaluation-001/` and
`data/processed/final-replay-001/`; compact tracked results are linked above.
The commands used were:

```sh
cd backend
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m app.forecasting.evaluate_final \
  --dataset ../data/processed/hourly-prices-hardware-v3-001 \
  --report-output ../data/processed/final-evaluation-001
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m app.forecasting.benchmark_final \
  --dataset ../data/processed/hourly-prices-hardware-v3-001 \
  --forecast-run ../data/processed/final-evaluation-001 \
  --metadata ../data/raw/hardware-import-v3-001/hardware-data-v3/resource-metadata/metadata.json \
  --report-output ../data/processed/final-replay-001
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest tests/forecasting tests/engine -q
```

Existing output directories are rejected. These commands document the completed
run; repeated computation of the same frozen recipe does not create a new
independent test. Saved forecasts support auditing without retraining.
