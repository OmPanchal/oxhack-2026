# Public multi-region augmentation: trained model comparison

The fixed LightGBM augmentation improves Stockholm CPU MAE slightly but worsens
Stockholm GPU MAE relative to the previous best. Broader data does not provide a
uniform accuracy improvement. The existing backend serving artifacts/configuration
remain unchanged; the new CPU/GPU candidates are saved separately.

## Imported data and provenance

Source: Eric Pauley (University of Wisconsin–Madison), **AWS Spot Price History**,
Zenodo version 2026-09, DOI [10.5281/zenodo.23082767](https://doi.org/10.5281/zenodo.23082767).
The August/September 2026 files total 508,409,765 compressed bytes; both published
MD5 checksums and local SHA-256 checksums were verified. The pinned API metadata
specifies CC-BY-4.0. See [source attribution and transformation notice](public-region-source-notice.md).
This is third-party archived AWS data, not a fresh direct AWS export from our account.

We selected five additional regions: Frankfurt, Ireland, London, N. Virginia and
Oregon. Eleven instance types reuse hardware-unit mappings verified in the original
AWS metadata: m5.xlarge, c6i.xlarge, r6i.xlarge, g4dn.xlarge, g5.xlarge, g6.xlarge,
g6e.xlarge, p4d.24xlarge, p5.48xlarge, p5e.48xlarge and p6-b200.48xlarge.

- Added **145 pools**: 54 CPU and 91 GPU, with **35,718 selected price events**.
- Added **212,280 known hourly prices**, covering `[2026-08-01,2026-10-01)` UTC.
- Combined with the existing 208 Stockholm pools: **353 pools across six regions**,
  with **655,396 known hourly prices**. The global instance-type inventory remains
  the original 79 types; only eleven are included in the new regional subset.
- Public data retains global AZ IDs such as `use1-az1`. These are never assumed to
  equal another account's AZ letter names. Public Stockholm is excluded to avoid
  an unverified cross-account AZ merge with our existing Stockholm export.
- Events are converted by backward as-of matching at hourly boundaries independently
  per month. Source-adjusted month-start anchors are documented. No backfilling,
  cross-month filling from an absent monthly series, or public October prices are
  invented. Price history is not capacity, current offerings or interruption labels.

Raw inputs: `data/raw/public-spot-import-001/`.
Filtered events and hourly matrix: `data/processed/public-region-hourly-001/`.
The [merged manifest](public-region-merged-dataset.json) references both components;
they are combined by `load_augmented` without overwriting or duplicating the
original Stockholm data. Raw/processed files and experimental weights are locally
stored and Git-ignored. Compact manifests, attribution and results are stored under `data/` for versioning.

## Frozen recipe and evaluation

The [design](public-region-experiment-design.json) was written before training or
scoring the augmented model. There is one candidate and no parameter search:
separate CPU/GPU LightGBM, L1 loss, 31 leaves, learning rate 0.04, minimum leaf size
100, L2 regularization 1, 200 rounds, seed 42, full residual correction and the
same shared-horizon causal features as the previous best. The median training
price provides target scaling independently per resource. Original pool codes
are retained; new pool IDs are appended. Known hardware categories are unchanged.

Training labels end before **2026-09-18 09:00 UTC**, with six-hour boundary purging.
Original training examples are retained and 858,690 regional examples are added:
**2,203,776 total** (CPU 1,255,500; GPU 948,276), versus 1,345,086 previously.
The public component's earliest eligible origins begin August 8 after 168-hour
warmup. Counts represent overlapping horizon labels, not independent observations.

## Like-for-like Stockholm comparison

The primary interval remains `[2026-10-10T15:00:00Z,2026-10-24T00:00:00Z)`.
All observations, origins, targets and horizons are identical to the previous
best's saved evaluation. This is a reused comparison period, not a fresh blind test.

- **CPU:** persistence MAE 6.26747822972e-05; previous-best MAE 5.6017498452e-05; augmented MAE 5.55296970894e-05. The augmented model's MAE is **0.8708% lower than the previous best**. Reduction versus persistence changes from **10.6219% to 11.4003%**. RMSE changes from 0.000100550488603 to 9.96741450139e-05. 272,160 forecasts.
  Against the previous best: 110 pools improve, 34 worsen and 0 tie.
  A descriptive joint 48-hour-block bootstrap interval for MAE reduction versus the previous best is [0.502%, 1.248%], from only 7 time blocks. This does not account for historical test reuse or all search decisions.
- **GPU:** persistence MAE 0.00498728060929; previous-best MAE 0.00445348867421; augmented MAE 0.00457420299766. The augmented model's MAE is **2.7106% higher than the previous best**. Reduction versus persistence changes from **10.7031% to 8.2826%**. RMSE changes from 0.012737194145 to 0.0132428558931. 120,960 forecasts.
  Against the previous best: 23 pools improve, 40 worsen and 1 tie.
  A descriptive joint 48-hour-block bootstrap interval for MAE reduction versus the previous best is [-2.949%, -2.500%], from only 7 time blocks. This does not account for historical test reuse or all search decisions.

CPU errors use USD/vCPU-hour; GPU errors use USD/GPU-hour. They are never combined
into one dollar-error metric. On the additional October 24 day, the new CPU model
has 1.5165% lower MAE than the previous best; GPU has 2.7511% higher MAE. One day
has insufficient time blocks for an interval, so only point estimates are reported.

## New-region historical coverage diagnostic

Public coverage ends at October 1. The new-region diagnostic therefore uses
`[2026-09-18T09:00:00Z,2026-10-01T00:00:00Z)`, with the same training cutoff and
six-hour purge. The old model has no trained support for these pools and invokes
its documented persistence fallback. Improvement here measures trained coverage
versus that fallback, not superiority over an incumbent trained in those regions.

- **CPU: 3.9977% lower MAE than persistence/old fallback**, on 96,228 forecasts. MAE 3.2745999515e-05 versus 3.41096146652e-05; RMSE 9.1371651897e-05 versus 9.81049261076e-05. 33 pools improve, 21 worsen and 0 tie.
  eu-central-1: 2.106% MAE reduction.
  eu-west-1: 2.185% MAE reduction.
  eu-west-2: 0.124% MAE reduction.
  us-east-1: 7.012% MAE reduction.
  us-west-2: 0.190% MAE reduction.
- **GPU: 6.5219% lower MAE than persistence/old fallback**, on 162,162 forecasts. MAE 0.00162326288242 versus 0.00173651656985; RMSE 0.00565195796863 versus 0.00601573124041. 59 pools improve, 26 worsen and 6 tie.
  eu-central-1: 6.623% MAE reduction.
  eu-west-1: 7.190% MAE reduction.
  eu-west-2: 2.100% MAE reduction.
  us-east-1: 7.219% MAE reduction.
  us-west-2: 7.403% MAE reduction.

These September dates precede the availability/selection cutoff of the recipe
chosen in the prior experiments. This is a retrospective model-development and
regional coverage diagnostic, **not an operational replay or a fresh prospective
test**. No original labels after the training cutoff are fitted, but historical
recipe selection and correlated market movements limit independent interpretation.
October Stockholm and September external-region scores must not be pooled into
one supposedly like-for-like test result.

## Recommendation and verification

Retain the previous GPU model for Stockholm; the new GPU candidate loses on both
October comparison periods. The augmented CPU is the better point estimate on
these periods and is a reasonable next validation candidate. The regional models
provide broader supported pools, with uneven per-pool performance. No candidate
was automatically promoted or deployed. Additional frozen, newly collected or
otherwise independent evaluation is needed before a generalization claim.
Prediction MAE gains do not establish scheduling savings.

Independent audits reconciled **212,280 public hourly values** with the preserved
monthly event stream and verified **673,974 scored forecasts** against their
source prices. Previous Stockholm predictions are reproduced exactly, and the
incumbent fallback is checked for every new-region forecast. Packaged augmented
model inference agrees with saved batch predictions. The original serving model
checksums and all recorded experiment implementation hashes match. The full
forecasting/engine suite passed 171 tests plus 53 subtests; after adding a downloader
checksum test, all five targeted public-data tests passed (172 unique tests in total).
See [audit and test validation](public-region-validation.json), [full comparison](public-region-comparison-results.json),
[import receipt](public-region-import-summary.json), and [model checksums](public-region-model-artifacts.json).

## Reproduce

The current environment includes the `zstd` command-line decoder and the existing
ML extra (`pip install -e '.[dev,ml]'`). No AWS credentials, upgrade or paid cloud
resources are needed. Source downloads need about 509 MB, plus local disk for
prepared data and models. Run from `backend/`, always with fresh output names:

```sh
.venv/bin/python -m app.forecasting.download_public_spot --design ../data/public-region-experiment-design.json --output ../data/raw/public-spot-import-NEW
```

Prepare the selected public subset:

```python
from pathlib import Path
from app.forecasting.public_spot_data import import_public
import_public(
    Path('../data/raw/public-spot-import-NEW'),
    Path('../data/processed/hourly-prices-hardware-v3-001'),
    Path('../data/raw/hardware-import-v3-001/hardware-data-v3/resource-metadata/metadata.json'),
    Path('../data/processed/public-region-hourly-NEW'),
    Path('../data/public-region-experiment-design.json'),
)
```

Fit and compare the frozen recipe:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m app.forecasting.compare_public_regions --original ../data/processed/hourly-prices-hardware-v3-001 --public ../data/processed/public-region-hourly-NEW --previous-models ../models/error-reduction-001 --output ../data/processed/public-region-comparison-NEW --models-output ../models/public-region-NEW --design ../data/public-region-experiment-design.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest tests/forecasting/test_public_spot_data.py -q
```

The candidate artifacts are in `models/public-region-001/`; each resource has a
native LightGBM text file and checksum/category/scaling metadata. Original trained
artifacts, API schemas, serving configuration, optimizer and frontend are preserved.
This work remains within Person 1's data, forecasting, evaluation and handoff scope.
