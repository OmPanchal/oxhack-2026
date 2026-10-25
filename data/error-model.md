# Error-focused ML pricing model

A shared-horizon LightGBM model with 31 leaves and 200 rounds improves forecast MAE substantially on the current observed AWS dataset. CPU and GPU use independent fitted models. The candidate was selected on September development data before its October scores were inspected. No production default changed.

## Comparison on the same October forecasts

The confirmation interval is `[2026-10-10T15:00:00Z,2026-10-24T00:00:00Z)`. Training ends at `2026-09-18T09:00:00Z`; no later labels enter fitting. All six forecast targets must lie before each partition boundary. CPU and GPU dollar-unit errors are reported separately.

- **CPU:** 10.6219% lower MAE than persistence; 8.5865% lower MAE than the previous ML model. MAE 5.6017498452e-05 versus persistence 6.26747822972e-05; RMSE 0.000100550488603; 272,160 forecasts.
- **GPU:** 10.7031% lower MAE than persistence; 9.6896% lower MAE than the previous ML model. MAE 0.00445348867421 versus persistence 0.00498728060929; RMSE 0.012737194145; 120,960 forecasts.

One-hour forecasts are weaker: CPU MAE worsens 0.89% and GPU MAE worsens 0.94% versus persistence. The aggregate advantage grows at longer horizons. This candidate does not establish an improvement for every horizon or every pool.

## Model and selection

Five training recipes each test correction weights of 0.5 and 1.0: relative-price L1 models with 7/31 leaves, scaled absolute-delta L1 models with 7/31 leaves, and a relative-price L2 model with 31 leaves. The minimum September MAE selects each resource independently. Both select `scaled-l1-31-w1.0`: predict the future price change divided by the median training price, then add the full predicted change to the current observed price. The scale is fitted only on training data. A common model learns across horizons 1–6, with horizon provided as a feature.

Features include current price; relative lags through 168 hours; past-window mean, standard deviation, minima/maxima and change frequency; age of the last price change; known calendar fields; and categorical pool/hardware identifiers. All use information available at the forecast origin. Parameters: learning rate 0.04, minimum leaf samples 100, L2 regularization 1, 200 fixed boosting rounds, seed 42, deterministic single-thread training. There is no random time split or early stopping on October data.

## Checks for overfitting

The selected recipe was frozen before the following three extra rolling diagnostics. Every fold retrains only on earlier observations and purges six-hour boundary crossings. These are stability checks, not independent model selection or a new blind holdout.

- **CPU:** earlier rolling MAE reductions 7.82%, 5.90%, 6.90%; September selection 10.74%; October confirmation 10.62%. Pool counts: {'improved': 137, 'worsened': 7, 'tied': 0}.
  The 24-hour joint time-block bootstrap gives a descriptive 95% interval of 8.25% to 12.69% MAE reduction, using 14 blocks. 14 blocks improve.
  The 48-hour joint time-block bootstrap gives a descriptive 95% interval of 7.72% to 13.15% MAE reduction, using 7 blocks. 7 blocks improve.
  October per-horizon gains (1–6 hours): -0.89%, 0.82%, 4.22%, 9.08%, 14.16%, 17.12%.
- **GPU:** earlier rolling MAE reductions 8.05%, 6.05%, 6.84%; September selection 9.39%; October confirmation 10.70%. Pool counts: {'improved': 63, 'worsened': 0, 'tied': 1}.
  The 24-hour joint time-block bootstrap gives a descriptive 95% interval of 9.89% to 11.46% MAE reduction, using 14 blocks. 14 blocks improve.
  The 48-hour joint time-block bootstrap gives a descriptive 95% interval of 10.09% to 11.41% MAE reduction, using 7 blocks. 7 blocks improve.
  October per-horizon gains (1–6 hours): -0.94%, 1.88%, 5.06%, 9.40%, 14.11%, 16.48%.

Blocks contain all pools and overlapping horizons together to retain their dependence. These intervals use only about two weeks of confirmation data and do not account for all historical model-search decisions. They cannot certify future performance. Source-price audits independently match every archived target/current price to the observed dataset. Tests verify causal features under future-price perturbations, native-model reload/inference parity, cold-history fallback, metrics, and block grouping.

**There is no evidence here of a collapse outside the selection interval, but absence of overfitting cannot be guaranteed.** The October interval had already been opened for the previous model. Another frozen evaluation on newly collected dates is required before claiming fresh prospective validation. Seven CPU pools worsen; all 63 trained GPU pools improve and the unsupported B200 pool remains persistence fallback. One region and related instance sizes do not establish transfer to new regions or hardware.

## Saved model and reproduction

Native text weights and hashed metadata are in `models/error-reduction-001/`. Load `ErrorPriceModel(directory, "CPU")` or `ErrorPriceModel(directory, "GPU")`, then call `predict(prices, identity, current_slot, horizon)`. Slots must use the recorded dataset origin `2026-07-28T00:00:00Z`. The adapter checks model/feature hashes, strips future observations before feature generation, and falls back to current price for unsupported pools or insufficient history. These models are experimental; API routing and scheduling integration are separate work.

From `backend/`, with a fresh output directory each time:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.error_search --dataset ../data/processed/hourly-prices-hardware-v3-001 --output ../data/processed/error-search-NEW
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.validate_error_model --dataset ../data/processed/hourly-prices-hardware-v3-001 --run ../data/processed/error-search-NEW --output ../data/processed/error-stability-NEW
```

The full [candidate results](error-model-results.json), [stability diagnostics](error-model-stability-results.json), [frozen search design](error-model-design.json), and [model checksums](error-model-artifacts.json) retain the comparison. These are forecast-error results; the previous scheduling savings result does not apply to the new model until it is replayed separately.
