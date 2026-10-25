# Alternative price model comparison

Four new model families were implemented and tested against persistence and the
previous extended-history LightGBM candidate. Several beat persistence on
development data, but none displaced that LightGBM candidate under the frozen
earlier-window selection rule. The final test remains untouched and the default
forecast service has not been changed.

## Models tested

- **Ridge regression:** a regularized linear model of the future price change.
  Numerical inputs and encoded categories are standardized using training data
  only. It is a simpler alternative to tree models.
- **Extra Trees:** an ensemble of randomized trees, trained to estimate the
  future price change. Depth and minimum leaf sizes restrict complexity.
- **Histogram gradient boosting:** a different implementation of boosted trees,
  trained with absolute-error loss to align with the MAE evaluation metric.
  Early stopping is disabled, avoiding any implicit randomly selected validation
  data inside time-series training.
- **Two-stage LightGBM:** first classify whether the target-hour price differs
  from the current price, then predict the signed price change with a regressor
  trained only on changed-price examples. Keep the current price unless the
  classifier reaches a specified threshold. These are actual price-change
  labels derived from observed historical prices; they are not interruption or
  capacity labels. Classification probabilities are not claimed to be calibrated.
- **LightGBM reference:** the previous separate-horizon, strongly regularized
  model with seven days of price history, rerun as a control.

Every family uses separate models for horizons 1–6 and the same extended causal
features. The experiment tests half and full corrections. For two-stage models,
price-change thresholds are 0.5, 0.7 and 0.9. That gives **14 variants** in total.
The settings were written to [the design](alternative-model-design.json) before
running this comparison; no additional dependencies were installed.

## Measured results

Positive percentages mean a reduction in MAE relative to persistence. Negative
percentages mean higher error. All results below were measured on real downloaded
AWS prices, with seed 42.

- **LightGBM reference, half correction:** earlier aggregate improvement
  **3.1683%**, wins in **2/3** earlier windows, later improvement **1.8885%**.
  This was the frozen selection. Its later MAE was **0.000617497066 USD/GPU-hour**,
  compared with persistence's **0.000629382716**. The reproduced reference agrees
  with the previous experiment.
- **LightGBM reference, full correction:** earlier improvement **2.1062%**,
  wins **2/3**, later improvement **2.9059%**. The first window was substantially
  worse, so the higher later score does not establish greater consistency.
- **Two-stage, half correction, threshold 0.5:** earlier improvement **0.4167%**,
  wins **1/3**, later improvement **2.0375%**. This is a useful exploratory result
  but fails the required two-window selection rule.
- **Two-stage, half correction, threshold 0.7:** earlier improvement **1.8171%**,
  wins **1/3**, later improvement **1.2050%**. Also fails the selection rule.
- **Two-stage, half correction, threshold 0.9:** earlier improvement **1.1989%**,
  wins **2/3**, later improvement **0.1330%**. A more conservative gate helped
  across windows, but its later benefit was very small.
- **Histogram gradient boosting, half correction:** earlier improvement
  **0.9566%**, wins **2/3**, later improvement **0.6110%**. It beat persistence
  in both aggregate comparisons, with smaller gains than the reference.
- **Extra Trees, half correction:** earlier improvement **−2.7203%**, wins
  **1/3**, later improvement **−0.8675%**. It did not improve on persistence in
  either aggregate period.
- **Ridge, half correction:** earlier improvement **−13.9413%**, wins **0/3**,
  later improvement **2.6937%**. Selecting it from its later score alone would
  obscure its poor earlier performance.

The [complete results](alternative-model-results.json) retain all 14 variants,
including full-correction failures, plus MAE/RMSE by horizon, source pool and
whether prices changed. No failed variants were removed from the report.

## Evaluation boundaries and limitations

All models use exactly the same eligible origins, requiring 169 consecutive known
hourly prices. They fit their encoder, scaling and estimators on training examples
only. The three expanding windows and six-hour boundary purges match the earlier
study: 13,518 earlier validation forecasts, followed by 5,670 later development
forecasts. The later model fits use only training targets below slot 1281.

The selection rule requires lower aggregate earlier MAE and improvements in at
least two of three windows, then chooses the eligible variant with the lowest
MAE. Selection happens before the later comparison and is not changed by later
scores. This design restricts candidates to extended-history models, unlike the
larger previous study; its winner therefore differs from that study's winner.

Both the features and candidate choices were informed by earlier development
experiments. The later period `[1281,1602)` has already been examined repeatedly.
It is **development evidence, not independent confirmation**. Earlier scores also
have selection optimism. Calibration `[1602,1815)` and test `[1815,2136)` are
removed before example building and remain unused for learning or scoring.

This is one region, one instance type and three availability zones. The proposed
5% improvement target has not been established. No result here proves statistical
significance, future superiority, cheaper scheduling or improved interruption
estimation. Persistence remains the current default until a separate decision
and frozen final evaluation.

## Reproduce and test

From `backend/`, with the existing `.[dev,ml]` environment:

```sh
python -m app.forecasting.compare_models \
  --dataset ../data/processed/hourly-prices-001 \
  --report-output ../data/processed/alternative-models-002
python -m pytest tests/forecasting/test_alternative_models.py -q
```

The completed run uses `alternative-models-001`; use fresh names for new runs.
Its [full report](processed/alternative-models-001/report.json) records dataset,
feature, implementation and design hashes, package versions and partition counts.
[Per-variant predictions](processed/alternative-models-001/later-predictions.jsonl)
allow independent recalculation of every later score. Processed outputs remain
Git-ignored; the tracked results contain all aggregate and grouped metrics.

`AlternativePriceModel` supports the existing in-memory
`LightGBMForecastService` interface, including explicit source-pool selection,
historical availability cutoffs and persistence fallback for missing history.
These fitted estimators are not serialized or installed into API routes. The
runner saves the recipe, metrics and predictions; rerunning trains them again.
No shared schemas, scheduler code, dependencies or cloud resources were changed.

Tests check deterministic predictions, training-only encoders, unseen-pool
fallback, no-change classifier handling, exact gating/shrinkage behavior, shared
forecast-service compatibility, frozen selection and invariance when protected
future labels are changed.
