# Person 1 Milestone 2: price forecasting handoff

Follow-up: [controlled improvement experiments](forecast-experiments.md) now
compare 40 variants. Extended history with separate horizon models shows
development-period gains, but the frozen winner failed the later check, so the
default remains `NAIVE`. The initial run below remains unchanged as its original
record. Calibration and final test are still reserved.

Milestone 2 now has a working persistence service, causal features, chronological
training/evaluation, a trained LightGBM artifact, and validation reports. Everything
in this milestone runs locally on the downloaded dataset. No further AWS calls
or rented compute are required.

## What you need to do

The initial training run is already complete. Your remaining actions are:

1. Review the validation result below: persistence currently has lower error than
   LightGBM, so keep `NAIVE` as the recommended forecast mode for this run.
2. Give Person 2 this document and the `models/price-model-001/` artifact directory
   when they are ready to integrate forecasting. Coordinate the fixed AZ/instance
   selection and scenario clock. The backend routes remain Person 2's work.
3. Keep the calibration and final test periods reserved while improving the model
   in Milestone 3. Do not tune against final test results.
4. Collect more regions only when account access permits it. The current run
   covers one GPU type in one region, with three separate AZ series.

Models and raw/processed datasets are Git-ignored. A teammate needs a copy of the
artifact directory to load this trained model; a code checkout alone will not
contain the weights or the downloaded data. Share only the required artifacts,
without AWS credentials or the virtual environment. Source changes and compact
validation results can be committed independently.

## What was implemented

- `PersistenceForecastService.predict(request)` repeats each pool's latest current
  price for all 1–6-hour targets. It keeps pools separate, accepts unordered
  history, and rejects stale/conflicting/future input through the shared checks.
- The feature builder reads only the current and preceding 24 hourly observations:
  price lags, trailing means/volatility, recent price change, capped time since a
  change, UTC calendar values, horizon, and source resource identity.
- Training and inference call the same feature builder. Retrospective hourly
  averages and capacity values are excluded from model inputs.
- A pooled LightGBM model learns the price change from the latest observed price.
  Adding that correction back gives the future price, clipped at zero. GPU and
  CPU unit prices remain identified by their source hardware.
- The categorical encoder is fitted on training examples only. Unseen source
  pools fall back to persistence rather than being silently treated as trained.
- The model artifact uses LightGBM text and JSON encoding/metadata, with checksums,
  package versions, dataset fingerprint, feature-code fingerprint, seed, and
  training/selection cutoffs. No Python pickle is used.
- The evaluation compares identical horizons, targets, and origins against
  persistence. It reports MAE/RMSE overall, by horizon, region, resource type,
  source pool, and whether the target price changed.

Price accuracy is distinct from compute savings. No optimizer replay or savings
benchmark is produced by this milestone. Uncertainty intervals and availability/
interruption probabilities remain null until the later evidence/calibration work.

## Chronological partitions and leakage protection

All three AZs use the same boundaries, relative to `2026-07-27T00:00:00Z`:

- Training: slots `[0, 1281)`, ending `2026-09-18T09:00:00Z`.
- Validation/model selection: `[1281, 1602)`, ending `2026-10-01T18:00:00Z`.
- Reserved calibration: `[1602, 1815)`, ending `2026-10-10T15:00:00Z`.
- Reserved final test: `[1815, 2136)`, ending `2026-10-24T00:00:00Z`.

For every forecast origin, all six targets must stay inside the same partition;
origins crossing a boundary are purged. A valid feature window needs 25 consecutive
known hourly prices. The one missing first-hour price in zone `eu-north-1a`
therefore excludes one additional training origin rather than being backfilled.

The run has 22,512 training examples from 3,752 source-pool/time origins and 5,670
validation examples from 945 origins. There are 945 validation examples per
horizon. These horizons and pool series can be correlated; counts do not imply
independent statistical trials or a significance claim.

The maximum training target is slot 1280, before the first validation origin at
1281. Three candidate configurations were defined before running validation; the
winner is selected by validation MAE, then RMSE, then candidate ID. The selected
model is not refitted on validation outcomes. Calibration and test labels are not
built into evaluation examples or scored by the training command. Loading and
validating the source dataset is separate from using those labels for learning.

Because model selection itself used validation outcomes, the selected artifact is
available for historical inference only from slot 1602 onward. Earlier service
calls return a clearly labeled persistence fallback. This prevents replay from
using knowledge of a future model-selection result.

## Measured validation result

The initial model version is `lightgbm-delta-v1-3310f6a9f1d7`, selected candidate
`small-l1`, with seed 42. These are model-selection results, not final test results.

- Persistence MAE: **0.000629382716 USD/GPU-hour**.
- LightGBM MAE: **0.000683137627 USD/GPU-hour**.
- Persistence RMSE: **0.001014334649 USD/GPU-hour**.
- LightGBM RMSE: **0.001040400522 USD/GPU-hour**.
- MAE improvement versus persistence: **−8.5409%**, meaning the ML model's MAE is
  approximately 8.54% higher. The proposed 5% improvement target was not met.
- No validation samples required an unsupported-pool fallback in this dataset.

The best of the three ML candidates still loses to persistence. The model is kept
for reproducible ablation and further validation work; the report recommends
`NAIVE`. This recommendation concerns forecasting accuracy, not proven scheduler
cost performance.

See [the tracked validation report](milestone2-validation.json) for all candidate
and horizon results. The full local run also contains
[validation predictions](processed/forecast-run-001/validation-predictions.jsonl)
and [metrics](processed/forecast-run-001/metrics.json). The trained model metadata
is [models/price-model-001/metadata.json](../models/price-model-001/metadata.json).

## Install and test locally

From the project root, if you do not already have a Python environment:

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,ml]'
python -m pytest tests/forecasting -q
```

For the complete backend suite, run `python -m pytest -q`. The initial training
environment versions are recorded in the report: Python 3.12.3, LightGBM 4.7.0,
scikit-learn 1.9.1, NumPy 2.5.4, and SciPy 1.18.1. The training process uses a
fixed seed, one LightGBM thread, deterministic settings, and fixed candidate
configurations. Exact cross-version/platform reproducibility is not guaranteed;
use the recorded environment when comparing model checksums.

## Reproduce training

From `backend/`, using the same downloaded/prepared dataset:

```sh
python -m app.forecasting.train \
  --dataset ../data/processed/hourly-prices-001 \
  --model-output ../models/price-model-002 \
  --report-output ../data/processed/forecast-run-002 \
  --seed 42
```

The first run already uses the `001` directories; this example uses new `002`
directories. Choose fresh names for each additional run. Existing runs are never
overwritten. Feature-code changes require retraining or loading the artifact with
its matching source version. The command verifies the input dataset checksum.

Outputs include `model.txt`, `encoder.json`, and `metadata.json` in the model
directory, and `metrics.json` plus `validation-predictions.jsonl` in the report
directory. The CLI does not evaluate the final test period.

## Person 2 inference integration

The public signature remains `predict(ForecastRequest) -> list[Forecast]`.
Use the same source pool for all API history assigned to its key. For example:

```python
from pathlib import Path
from app.forecasting.baselines import PersistenceForecastService
from app.forecasting.price_model import LightGBMForecastService, LightGBMPriceModel
from app.market.features import SeriesIdentity

naive_service = PersistenceForecastService()
model = LightGBMPriceModel.load(Path("../models/price-model-001"))
ml_service = LightGBMForecastService(model, pool_selections=[
    SeriesIdentity(
        region="eu-north-1", availability_zone="eu-north-1b",
        instance_type="g4dn.xlarge", product_description="Linux/UNIX",
        resource_type="GPU", gpu_type="NVIDIA T4",
    ),
])
# Person 2 builds the request from server-owned state, preserving this selection:
# forecasts = naive_service.predict(request)
# forecasts = ml_service.predict(request)
```

The example's `eu-north-1b` is an explicit integration choice, not a claim that
this zone was selected as the cheapest. The offline accuracy evaluation includes
all three separately identified zones. Do not flatten all three zones into one
API pool or infer source selection from whichever future price is lowest.

Use the artifact's UTC origin when constructing slots. Otherwise temporal
features and availability cutoffs will be wrong. The shared request has no origin,
AZ, or instance fields, so this context belongs to the backend's configuration.
Missing capacity must not be replaced with invented observed counts; price-only
training does not need capacities. A hybrid historical-price/simulated-capacity
request must retain the simulation labels and source provenance agreed in
[the forecasting contract](forecasting-contract.md).

ML service fallback `modelVersion` values identify `unmapped-pool`,
`unsupported-pool`, `model-not-available`, or `insufficient-history`. These repeat
the current known price and retain null uncertainty/risk. Stale or conflicting
snapshots still raise errors. A missing/corrupt artifact raises an explicit load
error; the backend may deliberately select the independent naive service and
report that choice instead of disguising an artifact failure as ML.

Both services and the generated reports are ready for integration. Person 2 owns
`main.py`, API routing, replay, and official scheduling metrics; those integrations
and scheduler cost ablations remain subsequent work.
