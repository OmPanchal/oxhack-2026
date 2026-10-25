# Expanded data import and fixed LightGBM comparison

The uploaded export was imported and validated, then the existing best LightGBM
recipe was compared with persistence. MAE improved for both CPU and GPU in all
three earlier windows and the later development period. No protected calibration
or final-test labels were used, and the default service remains unchanged.

## Actual collection scope

The export requested 42 region/instance combinations. Six were collected, one
was reported not currently offered, and 35 returned `UnauthorizedOperation`.
All successful observations are in Stockholm (`eu-north-1`); this export does
**not** expand regional coverage. Frankfurt, Ireland, Virginia, Oregon and
Singapore could not be collected with the account's current permissions.

Collected hardware:

- `g4dn.xlarge`: one NVIDIA T4, three AZ price series.
- `g5.xlarge`: one NVIDIA A10G, two AZ price series.
- `g6.xlarge`: one NVIDIA L4, two AZ price series.
- `m5.xlarge`, `c6i.xlarge`, `r6i.xlarge`: four vCPUs each, three AZ price series each.

`p3.2xlarge` was `NOT_OFFERED` in the Stockholm metadata query. Missing AZ price
series do not establish unavailable compute capacity.

The 89-day source interval is `[2026-07-28T00:00:00Z,2026-10-25T00:00:00Z)`.
There are 5,737 price events, six hardware records and **34,176 hourly records**
across **16 pools: seven GPU and nine CPU**. Every represented pool has 2,136
known hourly start prices and no missing start prices. Completeness still assumes
the source provider supplied complete price-change history.

The source archive SHA-256 is
`e759ee0201a335f436bafe9d687cdf32ac35d7a417ce7f4f5e6c1209c8c19c6d`.
The prepared dataset SHA-256 is
`85d5a2853e3f414d9f4a8a8bb25b25ce3670f7f887aa5b78461f44892bf3de82`.
See [the import summary](expanded-import-summary.json) for hardware, exclusions,
per-series coverage and validation evidence. Hashes establish consistency with
the supplied export; they are not independent provider signatures.

Import checks passed: ZIP CRC and safe paths, manifest file hashes, combined data
matching the successful shards, and exact recomputation of normalized prices from
raw instance prices and hardware metadata. The preserved archive, extracted data
and validation receipt are under ignored `data/raw/expanded-import-001/`.

## Frozen comparison

[The design](expanded-evaluation-design.json) fixes the existing incumbent's
parameters, seven-day causal features, seed 42, separate horizon models and 50%
correction to persistence. No hyperparameter, feature or weight search was run.
CPU and GPU models are fitted independently because their targets use different
resource units. Within each resource type, models pool compatible price-series
representations while retaining instance, GPU and AZ identity as features;
this does not imply workloads can substitute one hardware type for another.

Three earlier scoring windows use the original absolute UTC boundaries:

- `[2026-08-17T08:00:00Z,2026-08-28T00:00:00Z)`.
- `[2026-08-28T00:00:00Z,2026-09-07T16:00:00Z)`.
- `[2026-09-07T16:00:00Z,2026-09-18T09:00:00Z)`.

Each model uses only prior training targets. All six targets at an origin must
remain inside its partition; crossing origins are purged. All models and the
baseline use the same eligible origins, target hours and realized prices.

The later development window is
`[2026-09-18T09:00:00Z,2026-10-01T18:00:00Z)`. Training has 103,968 examples,
and later scoring has 30,240 forecasts: 17,010 CPU and 13,230 GPU. There were
zero unsupported-pool fallbacks. The three earlier scoring windows together have
72,096 forecasts: 40,554 CPU and 31,542 GPU.

**All rows from `2026-10-01T18:00:00Z` onward are removed before example building.**
The original calibration and test periods remain reserved. Using fixed timestamps
avoids accidentally moving protected labels into development when the collection
start shifts by a day. The runner also rejects designs exceeding that cutoff.

## Measured results

All improvement percentages below are relative reductions in MAE against
persistence; they are not compute-cost savings.

- **CPU:** earlier windows **+0.9001%, +2.6003%, +2.4029%**; earlier aggregate
  **+1.9351%**. Later development **+2.1393%**. All **9/9 CPU pools** improve later.
- **GPU:** earlier windows **+3.0586%, +4.8686%, +3.3189%**; earlier aggregate
  **+3.7807%**. Later development **+3.3430%**. All **7/7 GPU pools** improve later.

CPU later MAE is **0.000059659941 USD/vCPU-hour**, versus persistence's
**0.000060964139**; RMSE is **0.000104288810**, versus **0.000106522996**.
GPU later MAE is **0.000963458165 USD/GPU-hour**, versus **0.000996780045**;
RMSE is **0.001660144744**, versus **0.001705098841**.

Later development MAE improvements by instance type:

- T4 / `g4dn.xlarge`: **+4.3455%**.
- A10G / `g5.xlarge`: **+2.0682%**.
- L4 / `g6.xlarge`: **+4.4024%**.
- `m5.xlarge`: **+3.3208%**.
- `c6i.xlarge`: **+1.6826%**.
- `r6i.xlarge`: **+1.9497%**.

Equal-weight mean per-pool MAE improvement is **2.2474% for CPU** and **3.7927%
for GPU** in the later period. This complements resource-specific dollar MAE,
which can be dominated by more expensive hardware.

Benefits remain concentrated at longer horizons. CPU horizons 1–3 tie persistence;
horizons 4–6 improve **0.0537%, 2.4938%, 5.3886%**. GPU horizons 1–2 tie;
horizons 3–6 improve **1.7289%, 0.9763%, 4.7534%, 6.2210%**.

[Full results](expanded-evaluation-results.json) retain MAE/RMSE by resource,
hardware, pool, horizon and price movement, plus environment versions, code/data
hashes, sample counts and fixed partitions. Every resource-specific aggregate
MAE/RMSE was independently recalculated from saved per-forecast predictions.

## Interpretation and remaining limits

The fixed recipe shows encouraging consistency across hardware and earlier time
windows. This is broader hardware evidence than the original T4-only study, but
still one region and development data. These observations are temporally and
geographically correlated; no statistical significance or future-superiority
claim follows from all pools winning.

The original model was developed using overlapping T4 periods. New hardware,
the shifted dataset start, and independent CPU/GPU fitting also change the
comparison. Differences from the earlier 1.89% T4 result do not isolate a causal
benefit of adding data; that would require matched training-scope ablations.
No geographic generalization, scheduler cost savings, cloud execution or risk
calibration was tested. A separate frozen final evaluation is still needed before
promotion; this run changes no forecast defaults or API contracts.

## Reproduce and verify

From `backend/`, using the existing `.[dev,ml]` environment:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m app.forecasting.evaluate_expanded \
  --dataset ../data/processed/hourly-prices-expanded-001 \
  --report-output ../data/processed/expanded-evaluation-002
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest tests/forecasting -q
```

Use a fresh output directory. Run `expanded-evaluation-001` holds the exact design,
full report and predictions for all four periods. Models are fitted in memory;
weights are not serialized or installed into API routes.

**121 forecasting tests and 53 subtests passed.** New tests check separate resource
units, zero-baseline reporting, deterministic fitting, exclusion of protected
future rows, identical predictions when those labels change, and rejection of
designs that cross the original cutoff. Existing uncommitted work was preserved.
