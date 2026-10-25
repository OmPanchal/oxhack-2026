# Stockholm GPU model transfer to other regions

The frozen Stockholm-only GPU model does not transfer reliably under the tested
unseen-pool strategies. The primary strategy worsens aggregate MAE versus
persistence; an exact-instance proxy average has a small positive point estimate
but loses on many pools and its time-block interval includes no improvement.
The multi-region-trained model has the strongest aggregate MAE on this cohort.

## Frozen experiment

The [design](gpu-transfer-design.json) was persisted before transfer predictions
were generated. There is no training, scaling adaptation, correction-weight tuning,
selection of a donor by error, or deployment change. Both original and multi-region
native weight hashes are frozen. Price features use each target region's own
observed history and the original training feature builder, clock, GPU category,
scaling and full correction weight.

Period: `[2026-09-18T09:00:00Z,2026-10-01T00:00:00Z)`. The same **162,162** forecasts,
**91 pools**, five regions and horizons 1–6 are used for every method. These are
the exact targets from the previous regional experiment, not a new blind test.
The recipe was chosen using contemporaneous Stockholm outcomes, so this is a
retrospective diagnostic, not operational historical replay.

The original service intentionally returns persistence for unsupported regional
pools. This experiment tests controlled offline alternatives to that guard:

1. **Primary: missing pool category.** Set only the categorical pool ID to -1,
   preserve actual price features and the known GPU-family category, and apply
   frozen native weights. Negative categorical values are treated as missing by
   [LightGBM](https://lightgbm.readthedocs.io/en/stable/Advanced-Topics.html#categorical-feature-support).
2. **Secondary: exact-instance Stockholm proxies.** Evaluate every trained
   Stockholm pool with the same instance type and GPU family; average their raw
   residual predictions equally, then rescale, add the target region's current
   price and clip at zero. These are statistical proxy identities, not a mapping
   of physical AZs across accounts/regions. No proxy is selected using scores.
3. **Controls:** pure persistence and the previously trained multi-region model.

B200 was never represented in the Stockholm model's supported training identities,
so both transfer methods retain persistence for its **7,128 forecasts**. This
isolates regional transfer for known GPU families rather than silently pretending
the original model learned a new accelerator family. These fallbacks remain in
all aggregate scores and counts.

## Results

All errors are USD/GPU-hour. Positive reduction means lower error than persistence.

- **persistence:** MAE 0.00173651656985; MAE reduction **0.0000%**. RMSE 0.00601573124041, reduction 0.0000%. Pool counts: 0 improve, 0 worsen, 91 tie.
- **missing-pool-category:** MAE 0.001780525952; MAE reduction **-2.5343%**. RMSE 0.00571871336461, reduction 4.9374%. Pool counts: 36 improve, 51 worsen, 4 tie.
  Descriptive 95% interval from seven joint 48-hour time blocks: [-4.194%, -1.188%]. Overlapping horizons and all pools are resampled together; this does not account for historical selection or establish prospective performance.
- **mean-exact-instance-stockholm-proxies:** MAE 0.00172799290569; MAE reduction **0.4908%**. RMSE 0.00549452693667, reduction 8.6640%. Pool counts: 39 improve, 48 worsen, 4 tie.
  Descriptive 95% interval from seven joint 48-hour time blocks: [-1.747%, 3.080%]. Overlapping horizons and all pools are resampled together; this does not account for historical selection or establish prospective performance.
- **multi-region-trained:** MAE 0.00162326288242; MAE reduction **6.5219%**. RMSE 0.00565195796863, reduction 6.0470%. Pool counts: 59 improve, 26 worsen, 6 tie.
  Descriptive 95% interval from seven joint 48-hour time blocks: [5.921%, 7.090%]. Overlapping horizons and all pools are resampled together; this does not account for historical selection or establish prospective performance.

Regional MAE reductions versus persistence:

- eu-central-1: missing-category -6.878%; proxy average -1.338%; multi-region 6.623%.
- eu-west-1: missing-category 4.598%; proxy average 7.706%; multi-region 7.190%.
- eu-west-2: missing-category -8.367%; proxy average -5.179%; multi-region 2.100%.
- us-east-1: missing-category -0.642%; proxy average 1.127%; multi-region 7.219%.
- us-west-2: missing-category -1.883%; proxy average 1.508%; multi-region 7.403%.

Some families transfer better than others. H100 MAE is approximately 54–57% worse
than persistence under the transfer variants, while A10G/L4 improve in aggregate.
H200 has zero persistence MAE in this cohort, so its percentage improvement is
undefined; absolute errors remain in the report and overall MAE. No zero-baseline
pool is hidden. Although proxy transfer has the lowest aggregate RMSE, **MAE is
the existing primary objective**, and the multi-region model clearly wins MAE.

## Interpretation and safeguards

There is insufficient evidence to enable unrestricted zero-shot regional inference
for the Stockholm model. Its Stockholm performance cannot be assumed to hold
elsewhere. The result favors retaining the old model for Stockholm and validating
region-trained models for new regions. This is a recommendation from a limited,
reused historical cohort; it is not a guarantee that every regional pool improves.
No changes were made to backend defaults, pool mappings, unsupported-pool guards,
model weights, uncertainty or risk behavior.

The audit reconciles all 162,162 current/target prices with observed source data,
independently recomputes 648,648 method predictions' MAE/RMSE, checks exact parity
with the previous multi-region control, and verifies transfer features/predictions
are identical when future history is removed. Original serving-artifact checksums
and experiment implementation hashes match. Thirteen targeted forecasting tests
pass, including missing-category encoding, preservation of real price features,
all-donor averaging, untrained-hardware fallback and causal feature checks.
See [complete results and audit](gpu-transfer-results.json).

## Reproduce

From `backend/`, with existing downloaded/prepared inputs and a fresh output name:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.evaluate_gpu_transfer --original ../data/processed/hourly-prices-hardware-v3-001 --public ../data/processed/public-region-hourly-001 --previous-models ../models/error-reduction-001 --multi-models ../models/public-region-001 --reference-run ../data/processed/public-region-comparison-001 --output ../data/processed/gpu-transfer-NEW --design ../data/gpu-transfer-design.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest tests/forecasting/test_gpu_transfer.py tests/forecasting/test_public_spot_data.py tests/forecasting/test_error_search.py -q
```

No AWS access, paid compute, new packages or retraining is required.
