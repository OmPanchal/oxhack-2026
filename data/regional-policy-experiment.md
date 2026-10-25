# Regional specialists and persistence blending: bounded experiment

**Decision: retain the existing reference models.** The rolling-validation winner
produces small new-region gains but regresses on Stockholm, especially GPU. The
conservative blend does not provide a consistent aggregate improvement either.
No experimental policy, routing rule or model was deployed.

## Predefined experiment and chronology

The [frozen design](regional-policy-design.json) limits the experiment to the
existing 31-leaf, 200-round LightGBM L1 recipe, pooled versus single-region training,
and correction weights `[0, 0.25, 0.5, 0.75, 1]`. CPU/GPU remain separate. Blending
interpolates between the already clipped model price and current-price persistence.
No architecture, leaf-size, round-count or weight-grid search was added.

Rolling selection windows (UTC, common to all six regions):

- Train labels before August 28 00:00; score `[August 28 00:00, September 7 16:00)`.
- Train labels before September 7 16:00; score `[September 7 16:00, September 18 09:00)`.

Each window purges all origins whose six-hour targets cross its end. Native models,
training-only median-price scaling and source support are fitted separately for
each fold, never on the fold's scoring labels. These generate **1,058,112** rolling
forecast labels; overlapping horizons and related pools make them correlated.

The reference policy uses the previous Stockholm GPU specialist, the augmented
Stockholm CPU model, and the augmented models for the other five regions. The
candidate regional family fits the same recipe separately per resource/region.
There are two fitted model families, not an unrestricted search.

Using only the rolling predictions:

1. Choose the minimum-MAE family per resource/region from persistence, pooled and
   regional; ties prefer persistence, then pooled.
2. Choose one correction weight per resource/horizon, pooled across regions;
   ties prefer the smaller weight. This limits weight fitting to twelve cells.
3. Compare the fixed reference, its horizon-blended version, and the routed/blended
   candidate. Select minimum aggregate MAE per resource only if neither rolling
   fold is worse than reference; ties prefer the unchanged reference.

Both resources selected the routed/blended candidate. Both selections and their
hashes were frozen **before any later policy diagnostic was scored**. Final
models use labels before September 18 09:00, including the earlier validation
history. Existing matching pooled and Stockholm specialists are reused with exact
saved weights; ten additional regional experts were fitted. Existing model inputs,
hashes and source-pool encodings are preserved.

## Frozen selections

- **CPU:** selected `validation-route-blend`. Routed families: {'eu-central-1': 'pooled', 'eu-north-1': 'pooled', 'eu-west-1': 'pooled', 'eu-west-2': 'persistence', 'us-east-1': 'regional', 'us-west-2': 'pooled'}.
  Routed weights for horizons 1–6: [0.0, 0.25, 0.75, 1.0, 1.0, 1.0]; reference-blend weights: [0.0, 0.5, 1.0, 1.0, 1.0, 1.0].
  Rolling MAE reductions versus persistence: {'reference': 5.7387, 'reference-blend': 5.8152, 'validation-route-blend': 5.9741}. These are selection/development scores, not unbiased policy test results.
- **GPU:** selected `validation-route-blend`. Routed families: {'eu-central-1': 'pooled', 'eu-north-1': 'pooled', 'eu-west-1': 'pooled', 'eu-west-2': 'pooled', 'us-east-1': 'pooled', 'us-west-2': 'regional'}.
  Routed weights for horizons 1–6: [0.0, 0.5, 1.0, 1.0, 1.0, 1.0]; reference-blend weights: [0.0, 0.5, 1.0, 1.0, 1.0, 1.0].
  Rolling MAE reductions versus persistence: {'reference': 5.647, 'reference-blend': 5.7731, 'validation-route-blend': 5.8669}. These are selection/development scores, not unbiased policy test results.

The one-hour weight is zero for both resources: forecasts equal persistence exactly.
The CPU route uses a Virginia specialist and London persistence; the GPU route
uses an Oregon specialist. The selector also chose the pooled Stockholm GPU
model based on earlier validation. That choice fails to generalize to October.

## Later reused diagnostic periods

Stockholm: `[2026-10-10T15:00:00Z,2026-10-24T00:00:00Z)`.
New regions: `[2026-09-18T09:00:00Z,2026-10-01T00:00:00Z)`.
These periods were already examined in earlier research. They are not a new blind
test, and the original recipe was itself developed through previous experiments.
The data/label boundaries are enforced, but that does not erase historical test reuse.

All percentages below are MAE reductions versus persistence; comparison to the
reference uses identical targets. CPU errors are USD/vCPU-hour, GPU errors are
USD/GPU-hour, and different dates/resources are never combined into one MAE.

### Stockholm October comparison

- **CPU:** {'reference': 11.4003, 'reference-blend': 11.3847, 'regional': 10.6219, 'validation-route-blend': 11.2141}. Selected policy MAE is **0.2101% higher than reference**, on 272,160 forecasts. Reference MAE 5.55296970894e-05; selected MAE 5.56463910131e-05; selected RMSE 0.000100115803764.
- **GPU:** {'reference': 10.7031, 'reference-blend': 10.6707, 'regional': 10.7031, 'validation-route-blend': 8.2484}. Selected policy MAE is **2.7489% higher than reference**, on 120,960 forecasts. Reference MAE 0.00445348867421; selected MAE 0.00457591136307; selected RMSE 0.0132536092423.
### Five added regions, September

- **CPU:** {'reference': 3.9977, 'reference-blend': 4.0295, 'regional': 1.5056, 'validation-route-blend': 4.3964}. Selected policy MAE is **0.4152% lower than reference**, on 96,228 forecasts. Reference MAE 3.2745999515e-05; selected MAE 3.26100223656e-05; selected RMSE 8.66996090831e-05.
- **GPU:** {'reference': 6.5219, 'reference-blend': 6.5235, 'regional': 5.2485, 'validation-route-blend': 6.5745}. Selected policy MAE is **0.0563% lower than reference**, on 162,162 forecasts. Reference MAE 0.00162326288242; selected MAE 0.00162234899232; selected RMSE 0.00563962078891.

The additional October 24 day is also reused. On it, the selected CPU is 0.0015%
better than reference and selected GPU is 2.7450% worse. The reference-blend gains
are 0.0708% for CPU and 0.0740% for GPU on that one day; these tiny point estimates
are insufficient to establish generalization, and no confidence interval is
reported from a single time block.

## Interpretation

The selected router's new-region gains are only **0.4152% CPU** and **0.0563% GPU**
relative to the existing regional models. Stockholm regresses **0.2101% CPU** and
**2.7489% GPU** relative to its best reference models. It therefore fails as an
overall replacement even though it won the earlier selection windows.

The safer reference-blend preserves the source model choices, but Stockholm MAE
still worsens 0.0176% for CPU and 0.0362% for GPU. New-region MAE improves only
0.0331% and 0.0017%, respectively. Those near-flat results do not justify declaring
a better model. Correcting the known one-hour weakness is not sufficient when
other horizon weights or routing choices introduce new errors.

This shows that validation-selected routing did not generalize across these
periods; it does not prove every regional-specialist architecture is ineffective.
The tested specialists use the same small recipe and limited history. Further
adjusting weights after seeing these diagnostics would be additional test-driven
tuning, so no such changes were made.

Retain the reference: augmented CPU for Stockholm, original GPU for Stockholm,
and the augmented regional models as the existing regional research candidates.
The backend still uses its previously configured serving artifacts; optimizer,
API schema, frontend, uncertainty and risk behavior are unchanged. No compute-cost
or scheduling-savings claim follows from these forecast scores.

## Audit, artifacts and reproducibility

Audits reconcile **1,058,112 rolling targets**, **673,974 later targets**, and
**4,043,844 later policy-score pairs** with their source data. They reproduce
selection from rolling predictions, verify training/selection cutoffs and native
checksums, match all reference predictions to prior saved runs, and verify the
zero-weight forecasts equal persistence exactly. The two Stockholm regional
rolling validations reproduce earlier independent runs exactly. The full
forecasting/engine suite passed **180 tests plus 53 subtests**; the five targeted
policy tests also passed after a packaging-only path fix.

Scoring completed before that output-path serialization error. Packaging was
repaired from saved selections and results, without retraining or rescoring. The
original modelling script is preserved as
`data/processed/regional-policy-001/implementation-used.py`; the audit records both
the original and repaired source hashes. Future fresh runs use the repaired writer.

- [Complete results and audit](regional-policy-results.json)
- [Frozen design](regional-policy-design.json)
- [Experimental artifact checksums](regional-policy-artifacts.json)
- [Reserved forward-evaluation plan](regional-policy-forward-plan.json)

Native rolling models and predictions are in `data/processed/regional-policy-001/`.
Ten final regional experts and the frozen policy JSON are in
`models/regional-policy-001/`; the policy references the immutable existing pooled
and Stockholm model bundles. These experimental files remain Git-ignored and are
not a production service integration.

From `backend/`, with fresh names, reproduce the two phases:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.regional_policy_experiment --phase select --original ../data/processed/hourly-prices-hardware-v3-001 --public ../data/processed/public-region-hourly-001 --output ../data/processed/regional-policy-NEW --design ../data/regional-policy-design.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.regional_policy_experiment --phase evaluate --original ../data/processed/hourly-prices-hardware-v3-001 --public ../data/processed/public-region-hourly-001 --output ../data/processed/regional-policy-NEW --models-output ../models/regional-policy-NEW --design ../data/regional-policy-design.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest tests/forecasting/test_regional_policy.py -q
```

The next meaningful evidence is new dates, not more tuning on these periods.
The forward protocol reserves unscored external-region dates from October 1 and
new Stockholm dates from October 25, with at least fourteen complete days per
cohort. It requires another import/scoring run when observations become available;
it is not a scheduled collection or completed validation. No paid AWS access or
cloud compute is needed for the completed experiment.
