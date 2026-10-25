# Milestone 6: trustworthy metrics and comparisons

Backend metrics, reconciliation and policy comparisons are implemented. No
historical benchmark, trained model evaluation or real cloud bill was created.
The sample scenarios and injected test providers remain explicitly synthetic.
The requested manifest is optional and is not implemented. Dispatch pause/resume
remains an approved Milestone 7 prerequisite; see MILESTONE_7_PLAN.md.

## Official replay metrics

GET /api/metrics (or ?scope=REPLAY) reads one persisted replay snapshot. Before
reset it returns NOT_INITIALIZED with no strategy results or comparisons.
Otherwise it reports IN_PROGRESS/COMPLETED, scenarioId, originUtc, asOfSlot,
endSlot, executionMode=SIMULATED, dataKind=SIMULATED and
costBasis=SIMULATED_REALIZED. These are simulated costs at realized scenario
prices, not charges from AWS or the local machine.

Each strategy includes:

- ACTIVE/UNAVAILABLE/ERROR status, retained errors and modelVersions;
- reconciled compute, startup, transfer, optional carbon and total spend;
- completed, failed, infeasible, pending, running, unfinished and missed-deadline
  counts, along with the corresponding job IDs;
- per-job status, charged resource-unit-hours, actual modeled start/completion,
  completion slack, missed-deadline flag, cost breakdown and projected cost at
  start. A projection is never used as realized expenditure.

unfinishedJobs = pendingJobs + runningJobs. Lifecycle counts are disjoint;
missedDeadlines overlaps them and includes a previously failed/infeasible job
when its deadline passes. Completion exactly at the deadline is valid. Failed
jobs retain the charges incurred before failure. Recovery cost is zero because
the simulator has no retry/recovery execution; expected risk surcharges are
projections and are not converted into real charges.

Before returning official results the backend checks every ledger against:
the job/start, execution window, unique charged hours, actual observed scenario
price, configured first-hour overheads, carbon intensity, terminal outcome,
budget and missed-deadline set. Missing, duplicate or inconsistent charges
produce HTTP 409 / METRICS_LEDGER_MISMATCH instead of a savings number.

## Monetary arithmetic

Realized hourly monetary components use Decimal arithmetic, rounded HALF_EVEN
to USD 0.000000001 per component before storage. Subtotals and totals sum those
rounded components with Decimal; binary floats are only the JSON/storage
transport. Percentages round to six decimal places. Existing compatible float
ledgers are normalized to the same precision during reconciliation.

This intentionally retains small compute prices rather than rounding every hour
to cents. Optimizer projections remain estimates; the earlier 1e-12 USD budget
tolerance only suppresses floating-point noise in those feasibility checks.

## Comparisons and honest savings

The six ordered comparisons are cheapest-now versus FIFO, naive optimizer versus
both immediate baselines, and ML optimizer versus all three alternatives. The
ML-versus-naive pair is the same-optimizer forecasting ablation.

costDifferenceUsd = baseline total spend - candidate total spend. Positive means
the candidate incurred less cost. A cost difference is not automatically savings.
savingsUsd and savingsPercent are populated only after the replay ends when:

1. Both strategies remained ACTIVE, without missing providers or errors.
2. Exact completed job IDs and requirements match, not merely completion counts.
3. All job lifecycle/deadline outcomes match.
4. No pending/running work remains, and at least one job completed.

If matching failed/infeasible outcomes exist, their spend remains in the totals
and allJobsCompleted is false. This is a comparison conditional on those matched
outcomes, not a claim that all submitted work succeeded.

reasonCode explains why a comparison is blocked: IN_PROGRESS,
STRATEGY_UNAVAILABLE, STRATEGY_ERROR, DIFFERENT_WORKLOADS, DIFFERENT_OUTCOMES,
UNFINISHED_WORK or NO_COMPLETED_WORK. Unavailable/error peers have no numeric
cost-difference claim; other mismatches can expose a clearly labeled raw cost
difference but never savings. A zero baseline has no percentage (null), even for
a valid zero-cost completed workload. Negative savings are retained as losses.

## Live projections are a separate scope

GET /api/metrics?scope=LIVE returns costBasis=PROJECTED, current lifecycle counts,
known missed deadlines, unknown completion-time IDs, and each outstanding job's
latest plan. It never adds repeated historical decisions together.

knownProjectedCostUsd is the known subtotal. projectedPortfolioCostUsd is null
if any pending/running job is unpriced; unpricedOutstandingJobIds explains the
gap. With an empty outstanding portfolio the projected total is zero.
realizedSpendUsd and realizedSavingsUsd remain null: neither an AWS quote nor a
paper plan establishes a bill. Each projection retains its executionMode;
activeExecutionMode does not relabel mixed historical plans as one execution.

Completed live jobs are checked against recorded observedAtSlot, rather than
assuming COMPLETED means on time. Legacy completions lacking a slot are listed
as unknownCompletionTimeJobIds; Milestone 7's real monitor must supply outcomes.

## Model metrics handoff — Person 1

GET /api/models/metrics now returns typed UNAVAILABLE or EVALUATED state.
Without an evaluation provider, evaluation and improvements are null. No model
scores are invented from forecast output or test fixtures.

Wire Person 1's actual evaluated report through application composition:

```python
from app.main import create_app
from app.api.metrics_schemas import ModelEvaluation

def evaluated_report():
    # Return actual saved evaluation data supplied by Person 1.
    return ModelEvaluation.model_validate(actual_evaluation_data)

app = create_app(
    forecast_services={"NAIVE": naive_service, "ML": ml_service},
    model_metrics_provider=evaluated_report,
)
```

ModelEvaluation requires modelVersion, dataSource, sampleCount, UTC train/validation/
test start/end cutoffs, evaluatedAtUtc, mae, rmse, persistenceMae and
persistenceRmse. The intervals must be chronological, disjoint and nonempty;
the evaluation cannot be dated in the future. Reported RMSE must be consistent
with MAE for the same samples. Backend-computed improvements can be negative;
percentage improvement is null for a zero baseline.

Optional risk metrics require hasHistoricalLabels=true, a labelSource and sample
count. They support Brier score, calibration bins accounting for all samples,
and optional precision/recall with a classificationThreshold. Scenario-based
risk without genuine labels must omit these supervised metrics. Provider errors
or invalid reports return 503 / MODEL_METRICS_INVALID.

These validations check the declared report, not the underlying model training.
Person 1 remains responsible for real datasets, honest labels, chronological
evaluation and leakage prevention. No forecasting-owned implementation changed.

## Frontend handoff — Person 3

The response models are in backend/app/api/metrics_schemas.py and OpenAPI.
Use REPLAY metrics with the replay comparison screen, and LIVE metrics with the
live portfolio. Respect costBasis, executionMode, strategy status, comparable and
reasonCode. Display null as unavailable/unknown rather than zero.

Use backend savings fields, including negative values. Do not recompute official
percentages in the browser or mix live projections with simulated realized cost.
The existing base Decision/Forecast contracts are unchanged; metrics were already
unknown in the frontend client and now have a concrete schema to mirror.

## Verification

149 backend tests pass on Python 3.12.14. The existing Starlette/httpx
deprecation warning remains; no test failures. Frontend-owned files were not
modified in this milestone.

The suite includes hand-calculated multi-unit costs with startup/transfer/carbon,
six policy pairs, identical counts with different completed IDs, different failure
outcomes, differing partial progress, interim/error/unavailable states, zero
baselines, negative savings, ledger corruption/duplication, latest-plan-only live
projections, late completion, half-even precision, and valid/invalid model reports.
Constructed cases verify accounting; they are not real ML performance results.
