# More complex price-model experiments

The existing extended-history LightGBM with a 50% persistence correction remains
the best model in this comparison. None of the 14 new variants beat its aggregate
MAE on either the earlier windows or the later development period. The default
forecast mode has not changed, and calibration and final test remain reserved.

## Frozen experiment

The [design](complex-model-design.json) was saved before this run. Using only
existing dependencies and the downloaded observed AWS data, it adds:

- **Deeper LightGBM:** 15 leaves, depth 5, 240 boosting rounds, feature subsampling
  and L1/L2 regularization, compared with the incumbent's 3 leaves and 80 rounds.
- **Random forest:** 120 trees, depth 12, minimum leaf size 20, 80% feature sampling.
- **RBF support-vector regression:** nonlinear kernel with standardized training
  features and targets, C=1 and epsilon=0.1 in standardized target units.
- **Neural network:** two hidden layers of 64 and 32 ReLU units, Adam, L2
  regularization, and up to 250 iterations. Features and target deltas are scaled
  on training data only. No random validation subset or early stopping is used;
  training-loss stopping and a fixed iteration cap bound the run. Batch order is
  deterministic. Convergence warnings are retained rather than hidden.
- **Two fixed ensembles:** equal-weight averages of raw predicted deltas from
  incumbent + deeper LightGBM, and incumbent + deeper LightGBM + RBF SVR.
  Both apply a fixed 50% correction to persistence; no learned stacking weights.

Every family uses separate models for horizons 1–6 and the existing causal
168-hour features. Four new individual families each test corrections of 25%,
50% and 100%. The incumbent is fixed at 50%, plus two fixed blends: **15 total
variants, including the incumbent control**. Seed 42 and one computational thread
are used. No additional packages, AWS calls or paid compute were required.

## Fairness and selection

All models use the same eligible origins with 169 consecutive observed prices.
Three expanding windows use the existing boundaries at slots 512, 768, 1024 and
1281, and six-hour boundary purging. There are 13,518 earlier forecasts and 5,670
later development forecasts; each horizon has 945 later forecasts.

To replace the incumbent, a candidate must beat its earlier aggregate MAE, beat
it in at least two of three earlier windows, and also beat persistence in earlier
aggregate MAE. The lowest eligible earlier MAE wins. Otherwise retain the incumbent.
This selection is frozen before later development scoring. **No new variant
qualified**; only deeper LightGBM at 25% won even one earlier window against the
incumbent. Every other new variant won zero earlier windows against it.

The control reproduces the prior comparison's full later grouped metrics exactly.
Every variant's MAE/RMSE, horizon, pool and price-movement breakdown is retained in
[the complete results](complex-model-results.json). No failed variant is omitted.

## Measured results

Positive percentages below mean lower MAE than persistence; negative percentages
mean higher error. New individual families below use 25% correction, which happened
to give each family's best aggregate earlier and later result in the fixed grid.
This summary does not imply those variants were promoted after examining later scores.

- **Incumbent LightGBM, 50%:** earlier **+3.1683%**, later **+1.8885%**.
  Later MAE **0.000617497066 USD/GPU-hour**, RMSE **0.000992252279**.
- **Tree ensemble, 50%:** earlier **+1.5965%**, later **+0.4600%**.
  Later MAE is **1.4559% higher than the incumbent**.
- **Deeper LightGBM, 25%:** earlier **+0.6653%**, later **-0.1043%**.
  Later MAE is **2.0312% higher than the incumbent**.
- **Random forest, 25%:** earlier **-3.0203%**, later **+0.8338%**.
  Later MAE is **1.0749% higher than the incumbent**.
- **RBF SVR, 25%:** earlier **-4.8440%**, later **-2.6133%**.
  Later MAE is **4.5884% higher than the incumbent**.
- **Neural network, 25%:** earlier **-17.5831%**, later **+1.7448%**.
  Later MAE is **0.1464% higher than the incumbent**. Its near-match later obscures
  substantially weaker earlier results; selecting it from that period alone
  would be misleading.
- **Kernel/tree ensemble, 50%:** earlier **-2.0989%**, later **-1.7195%**.
  Later MAE is **3.6774% higher than the incumbent**.

Persistence's later MAE is **0.000629382716 USD/GPU-hour**, RMSE
**0.001014334649**. Larger corrections generally made these new candidates worse.
The full neural correction had earlier MAE **107.8863% worse than persistence**;
the report retains this failure alongside the more conservative variants.

**Neural convergence limitation:** 12 of 24 horizon-specific neural fits reached
the 250-iteration cap: 11 earlier fits and one later fit. Their predictions are
finite and scored, but these results evaluate this fixed training budget and
configuration, not the best achievable neural architecture or fully converged fit.
The other model families emitted no captured fit warnings.

## Interpretation and limits

Keep the incumbent as the leading experimental candidate; keep persistence as the
default pending a separate frozen final evaluation. Added complexity did not
improve MAE in this run. Several alternatives optimize squared or epsilon-insensitive
training loss, while the incumbent optimizes absolute error; this is a comparison
of complete recipes, not an isolated causal test of model complexity.

The earlier and later periods have both informed prior experiments. They are
development evidence with selection optimism, not independent confirmation. Only
Stockholm, one instance type (g4dn.xlarge/NVIDIA T4) and three related AZs are
represented. Overlapping horizons and AZ observations are correlated. No
statistical significance, final-test superiority, cloud reliability or scheduling
savings is established. Protected calibration `[1602,1815)` and test `[1815,2136)`
rows are removed before example building and remain unused for training or scoring.

## Reproduce and inspect

From `backend/`, using the existing `.[dev,ml]` environment:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m app.forecasting.compare_complex_models \
  --dataset ../data/processed/hourly-prices-001 \
  --report-output ../data/processed/complex-models-002
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest tests/forecasting -q
```

The completed run is `complex-models-001`; use fresh output names. Its ignored
directory contains the report, exact design, and predictions for every variant in
both periods. The tracked results preserve all aggregate/grouped scores, dataset,
feature, design and implementation hashes, package versions and warnings. Fitted
estimators are intentionally not serialized or installed into the API.

Validation: **112 forecasting tests and 53 subtests passed**. New tests cover all
five families, deterministic fitting, target/feature scaling using training only,
label-independent prediction, unseen-pool fallback, exact ensemble arithmetic,
earlier-only selection, protected-period exclusion and reproducible report outputs.
Existing uncommitted alternative-model work was left unchanged. No shared schemas,
API routes, scheduler code, dependency configuration or default forecast mode changed.
