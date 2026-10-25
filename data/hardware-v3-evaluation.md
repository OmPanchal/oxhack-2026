# Hardware v3 import and fixed-model evaluation

## Validated collection

The user supplied `hardware-data-v3.zip`. The collector obtained **79 of 96
requested instance types** in Stockholm: **31 GPU types and 48 CPU types**.
The other 17 candidates were `NOT_OFFERED` in the current metadata query;
there were no collection `ERROR` outcomes. This export expands hardware coverage,
not regions.

GPU metadata identifies eight models: NVIDIA T4, A10G, L4, L40S, A100, H100,
H200 and B200, with 1/4/8-device whole-instance configurations where offered.
There are 30 x86 CPU instance types and 18 ARM CPU instance types. Resource
identity, device counts, CPU architectures and original instance prices are
preserved rather than treating all compute as interchangeable.

The export interval is `[2026-07-28T00:00:00Z,2026-10-25T00:00:00Z)`: 89 days.
It contains **74,387 price-change events**, **208 AZ/instance pools** (144 CPU,
64 GPU) and **444,288 hourly records**. Of those, 443,116 have known start prices.
207 pools exceed 60 known days. The remaining pool is B200:
`p6-b200.48xlarge` in `eu-north-1b`, with 964 known hours and 1,172 missing start
prices. Its first event is `2026-09-14T19:30:35Z`; earlier hours remain unknown.
No future backfill or invented availability is used.

Validation passed ZIP CRC/path checks, every manifest hash, exact agreement of
combined price events with successful per-pair shards, and recomputation of all
normalized prices from original prices and hardware metadata. These establish
internal consistency with the supplied export, not independent provider signatures.

Archive SHA-256:
`e61ed7133bff8d37fb952cbe633e9b086ef481c03a9c58a6380e1658ce9c6c4a`.
Prepared dataset SHA-256:
`618ed38329ec8b4934c7fd40a0e77e61b3dcd9d3850b2df87299af5827903a36`.
The tracked [import summary](hardware-v3-import-summary.json) contains full
hardware mappings, exclusions and per-series coverage. Raw files and the source
archive are preserved in ignored `data/raw/hardware-import-v3-001/`.

## Method and implementation

The [unchanged fixed design](expanded-evaluation-design.json) uses the incumbent
LightGBM parameters, seed 42, 168-hour causal features, six separate horizon models
and 50% correction to persistence. CPU and GPU models fit separately. There is no
new feature, hyperparameter or correction-weight search. It retains the three
earlier windows and later development window described in
[the previous expanded comparison](expanded-evaluation.md).

The later training cutoff remains `2026-09-18T09:00:00Z`; later development ends
at `2026-10-01T18:00:00Z`. **All source labels from the latter timestamp onward
are removed before example building**, preserving original calibration/final-test
periods across every pool. B200 has no eligible training origins before the frozen
cutoff because seven days of history are required; its eligible later predictions
therefore fall back to persistence. It must not be represented as a trained B200 model.

The evaluator was made more memory efficient for this larger dataset:

- The input loader validates hashes and streams JSONL rows instead of retaining
  the full byte payload and decoded JSON records together.
- Training/scoring feature dictionaries are built for one resource type at a time.
- A one-origin cache reuses the horizon-independent statistics. The three horizon
  and known target-calendar fields are recomputed exactly as in the original builder.
- Feature dictionaries are discarded after predictions; aggregate metrics retain
  identities, labels and predictions rather than all training features.

These are execution optimizations, not a different forecasting recipe. Tests
verify exact feature equality with both original builders and exact fitted-model
prediction equality with the original evaluation path. Feature schemas, public
forecast interfaces, API contracts and default forecast mode are unchanged.

## Measured results

Positive percentages below mean lower MAE than persistence. All results are
development accuracy, not scheduling savings or untouched final-test performance.

- **CPU:** earlier-window improvements **2.7749%, 2.7994%, 1.9062%**; earlier
  aggregate **2.5098%**. Later development **2.1368%**.
- **GPU:** earlier-window improvements **1.9555%, 1.7693%, 1.6861%**; earlier
  aggregate **1.8048%**. Later development **0.8744%**.

Later scoring contains **392,622 forecasts**: 272,160 CPU and 120,462 GPU.
Training has **1,345,086 examples**. The earlier windows together score 932,742
forecasts. These counts include overlapping horizons and correlated size/AZ
series; they are not numbers of independent observations.

Later CPU MAE is **0.000059952677 USD/vCPU-hour**, versus persistence's
**0.000061261712**. RMSE is **0.000107878455**, versus **0.000109966806**.
Later GPU MAE is **0.003934049788 USD/GPU-hour**, versus **0.003968753217**.
RMSE is **0.011620582828**, versus **0.011673787330**.

The improvements are not universal:

- **CPU pools:** 137 improve, 7 worsen, none tie, out of 144. Three worsening
  pools had zero persistence error, so percentage improvements are undefined.
  The worst defined relative loss is **12.2801%** for `r7g.4xlarge` in zone 1c,
  from baseline MAE 0.000004722222 to model MAE 0.000005302118 USD/vCPU-hour.
- **GPU pools:** 57 improve, 6 worsen, one ties, out of 64. One worsening pool
  (`g4dn.8xlarge` in zone 1c) has zero baseline error and a small model error;
  its relative percentage is undefined. The tied pool is the B200 fallback.
- All **48 CPU instance-type aggregates** improve when combining their zones.
  Of 31 GPU instance-type aggregates, 29 improve, H100 worsens and B200 ties.

Equal-weight mean per-pool relative MAE improvement is **2.2255% for CPU** and
**1.7286% for GPU** later. This excludes three CPU pools and one GPU pool whose
persistence MAE is zero; their absolute errors remain in the report and aggregate
dollar MAE, and they are counted as losses above rather than hidden.

Later development by GPU model, aggregating all represented instance sizes/zones:

- **T4:** 2.0799% lower MAE.
- **A10G:** 1.1431% lower MAE.
- **L4:** 2.2974% lower MAE.
- **L40S:** 0.5608% lower MAE.
- **A100:** 0.3358% lower MAE.
- **H100:** **0.1321% higher MAE**.
- **H200:** 0.4150% lower MAE.
- **B200:** tied, because **all 1,392 scored forecasts use persistence fallback**.
  It is not evidence of a fitted B200 price model.

CPU architecture aggregates improve **2.2839% for ARM** and **2.0696% for x86**.
Architecture labels come from provider metadata; these are forecasting groups,
not evidence that ARM workloads/images can execute on x86 or vice versa.

Short horizons remain difficult to improve. Both resources tie persistence at
one and two hours. At six hours, CPU MAE improves **5.4596%** and GPU **2.3200%**.
Intermediate horizons, all pools, price-movement groups and each instance type
are retained in [the full results](hardware-v3-evaluation-results.json).

## Interpretation and verification

The frozen recipe beat persistence at aggregate CPU/GPU level in all four periods,
but this larger scope exposes specific losses. It does **not** justify a guarantee
or a blanket claim that ML improves every hardware configuration. The GPU gain
is smaller than the previous 16-pool study; expensive hardware and additional
sizes change the dollar-error weighting. That comparison does not isolate a
causal effect of more training data. A matched training-scope ablation would be
needed to make that attribution.

The selected recipe was informed by prior overlapping development data, and all
observations remain in one region. Related instance sizes/AZs and overlapping
horizons are correlated. No confidence interval or significance test was performed.
No final-test result, scheduler savings, calibrated reliability estimate or real
cloud execution is claimed. Existing forecast defaults and deployment stay unchanged.

Resource-specific aggregate MAE and RMSE for ML and persistence were independently
recalculated from all saved forecasts for all four periods, including sample-count
and target-cutoff assertions. The tracked report records the original run-report
hash and derived later group metrics by GPU model and CPU architecture. Derived
groups use the same absolute/squared-error definitions, grouped using the import
metadata; no model is selected from these breakdowns.

## Reproduce

From `backend/`, in the existing ML environment:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m app.forecasting.evaluate_expanded \
  --dataset ../data/processed/hourly-prices-hardware-v3-001 \
  --report-output ../data/processed/hardware-v3-evaluation-002
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m pytest tests/forecasting -q
```

Use a fresh report directory. The completed run uses `hardware-v3-evaluation-001`;
the output records fixed settings, code/data hashes, package versions, sample
counts and forecasts for each period. Models fit in memory and are not deployed.

**132 forecasting tests and 53 subtests passed.** They include the new equivalence
checks, immutable protected-period behavior, model reproducibility, checksums,
hardware mapping, and whole-instance allocation/billing checks.
