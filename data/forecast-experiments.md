# Forecast improvement experiments

## What was tried

Completed on the existing observed AWS dataset, locally, with seed 42. No new
AWS requests or paid compute were used. The frozen
[experiment design](forecast-experiment-design.json) crosses:

- The original 24-hour features versus up to 168 hours of history, including
  longer lags, trailing averages/volatility, price-change frequency and price age.
- One pooled model versus six separate models for the 1–6-hour horizons.
- Original versus stronger regularization: smaller trees, larger minimum leaves,
  fewer boosting rounds, and L1/L2 penalties. This is a combined regularization
  intervention; the experiment does not isolate each of these settings.
- Correction weights of 10%, 25%, 50% and 100%, plus horizon-specific weights
  selected from earlier validation predictions. A zero-weight correction is the
  persistence control. For example, 50% means applying half the model's predicted
  change to the latest observed price.

That produces **40 evaluated variants** across eight underlying model setups.
MAE is the primary metric: lower is better. Positive improvement means less
error than persistence. RMSE is also recorded for every variant.

## How the comparison was kept fair

All variants use identical eligible origins, requiring 169 consecutive known
hourly prices. Even the 24-hour models use this eligibility rule, so a feature
comparison cannot gain by dropping difficult examples. This removes some early
training origins compared with the original Milestone 2 run; compare feature and
architecture effects within this experiment rather than attributing every change
from the original model to a single intervention.

Three expanding-window folds use training/validation boundaries at slots 512,
768, 1024 and 1281. Each fold trains only on earlier labels; origins whose six
targets cross a partition boundary are purged. The combined validation cohort has
13,518 forecasts. Configuration and correction weights are selected using those
earlier predictions, requiring improvement in at least two of three folds as well
as lower aggregate MAE.

The winner is frozen before evaluating the original development-validation
period `[1281,1602)`, with 5,670 forecasts. This period had already been inspected
before these experiments were designed, so it is **not an independent final
test**. Other variants' later-period results are exploratory comparisons; they do
not replace the frozen winner after seeing their scores. Calibration
`[1602,1815)` and final test `[1815,2136)` remain unused for training, selection,
calibration or scoring. Protected rows are removed before example building.

## Measured results

Several combinations reduced error in both the earlier aggregate and the later
development period. Two useful candidates for a future frozen evaluation are:

- **168-hour features + separate horizon models + stronger regularization +
  50% correction:** MAE improved **3.1683%** across the earlier folds and
  **1.8885%** on the later development period. It won two of three earlier folds;
  individual improvements were −0.1992%, +6.3945% and +3.1231%. Later MAE was
  **0.000617497066 USD/GPU-hour**, versus persistence's **0.000629382716**.
- **The same setup with the full correction:** earlier aggregate improvement
  **2.1062%**, later improvement **2.9059%**. It also won two of three folds,
  but lost the first by 7.8190%, showing greater variation between periods.

Longer history is the clearest useful direction in this experiment: all 20
extended-history variants beat persistence on the later development period,
whereas all 20 original-history variants lost there. This pattern is specific to
these periods and source pools. Of the extended variants, 16 also passed the
earlier aggregate/two-fold selection rule.

The largest later-period improvement, **3.3772%**, came from extended features
with separate horizon models, original regularization and full correction.
However, that variant was **3.8648% worse** across the earlier folds and won only
one fold. Selecting it solely for its best later score would give misleading
evidence of reliability.

The actual frozen winner was **24-hour features + pooled model + stronger
regularization + horizon-specific weights**. Its corrections for horizons 1–6
were `[0, 0, 0, 1, 0.5, 1]`. It improved earlier aggregate MAE **3.3207%**, winning
all three folds, but was **0.0383% worse** on the later period. Its later MAE was
**0.000629623994**. Consequently the report retains **NAIVE/persistence** as the
recommended default. The saved winner is an experiment artifact, not a promoted
production model.

These are measured development results. None establishes final-test improvement,
statistical significance, generalization to other regions/hardware, or actual
scheduling savings. The proposed 5% improvement target has not been demonstrated.

## Reproduce and inspect

From `backend/`, in an environment installed with `.[dev,ml]`:

```sh
python -m app.forecasting.experiments \
  --dataset ../data/processed/hourly-prices-001 \
  --model-output ../models/price-experiment-002 \
  --report-output ../data/processed/forecast-experiments-002 \
  --seed 42
python -m pytest tests/forecasting -q
```

The completed run uses the `001` directories. Use fresh names to avoid overwriting
artifacts. The [tracked results](forecast-experiment-results.json) include all 40
variants, fold scores, MAE/RMSE, weights, selection decision, environment versions,
dataset hash and design hash. Full local outputs are in
[the run report](processed/forecast-experiments-001/report.json) and
[selected predictions](processed/forecast-experiments-001/selected-confirmation-predictions.jsonl).
Weights and processed data remain Git-ignored.

The saved artifact is [price-experiment-001](../models/price-experiment-001/metadata.json).
Load it with `ExperimentBundle.load(Path("../models/price-experiment-001"))` and
pass it into the existing `LightGBMForecastService` with the same explicit source
pool selection described in [the Milestone 2 handoff](milestone2.md).
`predict(ForecastRequest) -> list[Forecast]` is unchanged. Inference uses the
matching feature profile and frozen correction weights; missing history falls
back to persistence. Historical availability begins at slot 1602. No backend
routes, scheduler modules, shared schemas or dependencies were changed.

## Next decision

Keep persistence as the current default. The extended-history, separate-horizon
models are credible candidates for the next frozen comparison, with both 50% and
100% correction worth considering. Choose the next candidate and success rule
before using any fresh evaluation data. Do not repeatedly tune on the reserved
final test. Scheduler cost improvement still needs a separate fair replay with
Person 2; lower forecasting error does not guarantee lower compute spend.
