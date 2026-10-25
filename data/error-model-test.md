# Saved-model test verification

The saved CPU/GPU LightGBM weights were loaded and evaluated without fitting, selecting, changing correction weights, or adding training labels. All native weights and metadata match the frozen artifact checksums. Training ends at 2026-09-18 09:00 UTC.

## Designated test partition: October 10–24

Interval: `[2026-10-10T15:00:00Z,2026-10-24T00:00:00Z)`. This partition had already been evaluated; this run independently reproduces the earlier results rather than constituting a new blind test.

- **CPU:** MAE **10.62% lower** than persistence (5.6017498452e-05 versus 6.26747822972e-05 USD/vCPU-hour). RMSE **10.41% lower** (0.000100550488603 versus 0.000112229680484). 272,160 forecasts; pools: 137 improve, 7 worsen, 0 tie.
- **GPU:** MAE **10.70% lower** than persistence (0.00445348867421 versus 0.00498728060929 USD/GPU-hour). RMSE **9.59% lower** (0.012737194145 versus 0.0140889824692). 120,960 forecasts; pools: 63 improve, 0 worsen, 1 tie.

## Additional forward day: October 24

Interval: `[2026-10-24T00:00:00Z,2026-10-25T00:00:00Z)`. This is the final date in the existing observed dataset, previously excluded from search scoring and model fitting. The evaluation design was saved before opening these scores. It is one newly scored day within the same dataset, not a separate external dataset.

- **CPU:** MAE **6.47% lower** than persistence (5.59156328154e-05 versus 5.97865226337e-05 USD/vCPU-hour). RMSE **6.64% lower** (0.000100871882835 versus 0.000108041176266). 15,552 forecasts; pools: 111 improve, 33 worsen, 0 tie.
- **GPU:** MAE **10.71% lower** than persistence (0.00377392056443 versus 0.00422640516493 USD/GPU-hour). RMSE **11.24% lower** (0.0124967644906 versus 0.0140788713209). 6,912 forecasts; pools: 41 improve, 22 worsen, 1 tie.

## Limits and verification

One-hour predictions worsen relative to persistence: CPU 0.89% and GPU 0.94% on the designated partition; CPU 0.92% and GPU 2.28% on the forward day. Aggregate gains increase at longer forecast horizons. The forward day has more losing pools despite positive aggregate MAE, so the model is not uniformly better across hardware/locations.

All six targets at a scoring origin must remain within the partition. The 24-hour forward interval therefore contains 18 complete forecast origins per pool, not 24. Its 22,464 predictions contain overlapping horizons and correlated pools; they are not 22,464 independent experimental observations. One day is insufficient to settle overfitting or future generalization. This forward day is now evaluated and must not be presented as untouched in subsequent work. No uncertainty calibration, scheduling savings, paid cloud execution, or production default change is implied.

Independent audits checked all **415,584** current/target prices against observed source data, recomputed MAE, verified all original-period predictions exactly match the archived run, and checked packaged single-forecast inference against batch predictions. See the [complete results and audit receipt](error-model-test-results.json).

Reproduce from `backend/` with a fresh output directory:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.evaluate_error_test --dataset ../data/processed/hourly-prices-hardware-v3-001 --models ../models/error-reduction-001 --output ../data/processed/error-test-verification-NEW
```
