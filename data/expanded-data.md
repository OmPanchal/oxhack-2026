# Expanded regional GPU and CPU data

The prepared collection targets 42 region/instance pairs, before availability-zone
expansion. This is a requested scope, not a claim that AWS offers every combination
or that the account can access every region. Live collection has not run locally:
this workspace has neither boto3 nor configured AWS credentials. Use the supplied
CloudShell bundle with the AWS session used for the original export.

## Requested scope

The editable [configuration](expanded-collection.json) targets:

- Regions: Stockholm `eu-north-1`, Frankfurt `eu-central-1`, Ireland `eu-west-1`,
  N. Virginia `us-east-1`, Oregon `us-west-2`, Singapore `ap-southeast-1`.
- GPU instance candidates: `g4dn.xlarge`, `g5.xlarge`, `g6.xlarge`, `p3.2xlarge`.
- CPU instance candidates: `m5.xlarge`, `c6i.xlarge`, `r6i.xlarge`.
- Product: Linux/UNIX, fixed across every series.
- History: 89 days ending at the latest completed UTC hour when the run begins.
  This boundary is frozen for the entire run and recorded in `receipt.json`.

Hardware names, GPU counts/memory and vCPU counts come from the provider metadata
API, rather than being inferred from the requested instance names. Current regional
offerings are checked before price collection. A `NOT_OFFERED` result means absent
from this current offering query, not proof of historical unavailability.

The three operations are read-only:
`ec2:DescribeInstanceTypeOfferings`, `ec2:DescribeInstanceTypes` and
`ec2:DescribeSpotPriceHistory`. The collector never launches instances. AWS's
[Spot history API](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html)
accepts start times up to the preceding 90 days; using 89 days leaves runtime margin.

## Run in CloudShell

Upload `expanded-collector.zip` from this workspace's ignored `data/raw/` directory
to CloudShell. The archive contains only the configuration, these instructions and
the collector source files. It contains no credentials, original exports, models
or virtual environment. Then run:

```sh
unzip expanded-collector.zip
cd expanded-collector
PYTHONPATH=backend python3 -m app.forecasting.collect_expanded \
  --config expanded-collection.json --output expanded-data
python3 -m zipfile -c expanded-data.zip expanded-data
```

The bundle requires Python 3.11+ and boto3. Check with `python3 --version` and
`python3 -c 'import boto3'`. If boto3 is absent, install it with
`python3 -m pip install --user boto3`. No FastAPI, ML libraries or Docker are needed
to collect. Uses the existing AWS credential chain; no profile flag is needed in
CloudShell. A normal configured machine can pass `--profile PROFILE_NAME`.

Download `expanded-collector/expanded-data.zip` from CloudShell and provide that
archive for local validation/preparation. Do not include the CloudShell home
directory or AWS configuration files. If interrupted, archive the existing
`expanded-data` directory too: completed per-pair shards remain inspectable.

Each new run requires a new output directory; existing data is never overwritten.
If the run reports `NO_DATA`, its exit status is 2 and the receipt records each
failure. Permissions to additional regions must be granted through the account;
changing a region list cannot bypass an account or IAM restriction.

## Export behavior and audit trail

The collector treats each region/instance pair independently, retaining successful
data if another pair fails. It uses sequential requests with bounded SDK retries,
keeps full pagination, and does not synthesize missing prices or risk labels.

`receipt.json` records the exact requested scope, fixed window and one outcome for
every pair: `COLLECTED`, `NOT_OFFERED`, `EMPTY_PRICE_HISTORY` or `ERROR`. Provider
error codes are retained; raw SDK exception messages are omitted. The receipt is
updated after each pair. Filesystem errors stop the run and preserve earlier shards.
It is not a resumable collector: use a fresh directory to rerun a failed subset.

- `shards/<region>/<instance>/spot-collection/`: original price events and manifest.
- `shards/<region>/<instance>/resource-metadata/`: verified hardware metadata,
  normalized prices and checksums.
- `spot-collection/` and `resource-metadata/`: combined data for explicitly
  collected pairs, compatible with the existing local preparation pipeline.
- `receipt.json`: omissions, status (`COMPLETE`, `PARTIAL`, `NO_DATA`), hardware,
  event coverage per zone, and hashes of combined files.

A `PARTIAL` export can be useful but must be reported as partial. Combined manifests
repeat all excluded pairs. Pagination completeness applies to the included subset;
it does not claim that inaccessible pools were collected. Empty price history does
not mean zero available compute capacity. Price history still cannot establish
interruption probabilities.

All price series retain region, Availability Zone, instance type and product.
GPU prices are converted per device and CPU prices per vCPU only after verifying
metadata. Original instance prices and whole-instance allocation sizes remain
authoritative for scheduling/accounting. Different GPU models or CPU families do
not become interchangeable merely because normalized prices share dollar units.

## Local preparation and evaluation after import

First validate the ZIP and receipt, every file hash, raw-to-normalized conversions,
observed coverage, missing hours and number of distinct pools. Prepare all included
series over the receipt's recorded UTC interval with the existing tool:

```sh
cd backend
.venv/bin/python -m app.forecasting.hourly_data \
  --collection ../data/raw/EXPANDED_IMPORT/expanded-data/resource-metadata \
  --start START_TIME_FROM_RECEIPT --end END_TIME_FROM_RECEIPT \
  --output ../data/processed/hourly-prices-expanded-001
```

Replace the uppercase placeholders using the actual import path and receipt. Do
not run forecasts against an unchecked or incomplete transfer.

Freeze the existing best LightGBM recipe and compare it against persistence on
the same per-pool origins/horizons, with shared calendar boundaries and label
purging. Report CPU and GPU accuracy separately, and break down GPU models,
instance types, regions and AZ pools. A pooled absolute-dollar MAE can be dominated
by expensive GPUs; also inspect per-pool relative MAE and pool coverage rather
than interpreting a changed resource mix as a modeling improvement.

**Preserve earlier holdouts:** the original Stockholm/T4 calibration and test
window starts at `2026-10-01T18:00:00Z` and ends at `2026-10-24T00:00:00Z`.
Do not blindly rerun percentage-based splitting on a shifted collection window:
that could move previously protected labels into model selection. Agree fixed
UTC evaluation boundaries before training the expanded comparison. New locations
are broader coverage, not permission to tune on the original final test.

The collection does not train models or modify the default forecast service.
No expanded-data model results exist until the actual export has been imported
and the frozen comparison has run.

## Offline verification

```sh
cd backend
.venv/bin/python -m pytest tests/forecasting/test_collect_expanded.py \
  tests/forecasting/test_collect_spot.py tests/forecasting/test_resource_metadata.py \
  tests/forecasting/test_hourly_data.py -q
```

37 tests and 20 subtests passed using synthetic provider responses. They verify
error isolation, hardware mapping, checksums, preserved shards and compatibility
with hourly preparation; these checks are not live AWS collection results.
