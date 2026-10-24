# Step 4: optional capacity and interruption evidence

This importer accepts an existing, authorized operational export and produces
validated records, an evidence summary, and checksums. It does not provision cloud
resources or collect new execution outcomes. No genuine operational export is
currently included in the repository.

The example file is explicitly **SIMULATED** and exists to exercise the importer.
Its counts and runtime are not empirical cloud reliability measurements.

## Run the example

Use a Python environment with the project's existing backend dependencies
installed, including Pydantic. From `backend/`:

```sh
python3 -m app.forecasting.operational_data \
  --input ../data/examples/operational-observations.simulated.json \
  --output ../data/processed/operational-example
```

For an authorized real export, replace `--input` with its file path and choose a
new output directory. The input must follow the same versioned format. Existing
output directories are never overwritten. Add, for example,
`--as-of 2026-10-24T10:00:00Z` to summarize only records available at that time.

The example has five capacity requests and four execution episodes, including one
simulated interruption and 6.5 observed episode-hours. These are hand-authored
software test inputs. The summary keeps both risk probabilities null.

## Input format

Use the [complete synthetic example](examples/operational-observations.simulated.json)
as the structural reference and [import schemas](../backend/app/forecasting/operational_schemas.py)
as the validation source of truth. JSON names use camelCase. The top-level fields
are `schemaVersion`, `provenance`, `fulfillmentObservations`, and
`executionObservations`. Empty observation lists are allowed; omit neither list.

Provenance must include:

- `source`: a traceable export identifier, path, or source URL, without credentials.
- `retrievedAt`: when this export was obtained, with an explicit timezone.
- `dataKind`: `OBSERVED` for genuine operational records, or `SIMULATED` for tests.
- `collectionConditions`: what was logged, selection/sampling rules, workload or
  fleet configuration, observation window, known gaps, and filtering applied.
- `labelDefinitions`: separate descriptions for fulfillment, interruption, and
  censoring, including how those outcomes were established in the source logs.
- `authorizedForUse`: boolean `true`, declaring that this export may be used.

Authorization and provenance are caller declarations; the importer cannot prove
the truth of an export. Never relabel the supplied fixture as genuine evidence.
Store real exports under ignored `data/raw/` paths and normalized outputs under
ignored `data/processed/` paths. Do not commit credentials or private raw logs.

Every observation retains an ID, region, optional Availability Zone, instance
type, resource type, optional GPU type, `observedUntil`, and `recordedAt`. GPU
records require a GPU manufacturer/model name; CPU records require null
`gpuType`. Units are GPU counts or vCPU counts consistently with Steps 1–2, not
unconverted instance counts. Preserve instance identity and verified hardware
mapping when preparing an export; the importer does not infer hardware from names.

### Capacity fulfillment records

Also provide `requestedAt`, positive integer `requestedUnits`, integer
`fulfilledUnits`, and one of these final observation outcomes:

- `FULFILLED`: all requested units were supplied.
- `PARTIAL`: a terminal partial result supplied more than zero but fewer than all
  requested units. An ongoing request with partial fulfillment is `CENSORED`.
- `UNAVAILABLE`: the provider explicitly could not supply capacity; zero supplied.
- `ERROR`: a failure unrelated to a capacity outcome, such as authorization or
  malformed input; zero supplied. It is not evidence of unavailable capacity.
- `CENSORED`: observation ended while the final outcome remained unknown. Any
  partially fulfilled units may be recorded, but full fulfillment is resolved.

`observedUntil` is the result time or the observation cutoff for an unresolved
request. It cannot precede `requestedAt`. `recordedAt` is when the source record
became available and cannot precede `observedUntil`.

The summary counts `FULFILLED`, `PARTIAL`, and `UNAVAILABLE` as resolved capacity
labels. It reports errors and censored requests separately. Results are grouped
by location, hardware identity, and requested size; a two-GPU request does not
silently become evidence about an eight-GPU request.

### Execution records

Also provide `startedAt`, positive integer `resourceUnits`, `interruptedAt`
(nullable), and one outcome:

- `COMPLETED`: execution completed within the observed interval.
- `INTERRUPTED`: an explicit provider interruption ended the execution.
  `interruptedAt` must equal `observedUntil`.
- `FAILED`: another execution failure. It does not establish a provider interruption.
- `CENSORED`: observation stopped before execution's eventual outcome was known.

An advance interruption warning or placement score is not an actual termination
label. Non-interrupted records must have null `interruptedAt`. Execution duration
must be positive. Retries are distinct execution episodes with distinct IDs;
do not count overlapping monitoring fragments of the same episode as new runs.

Observed episode-hours equal `observedUntil - startedAt`, including observed time
for failed and censored episodes. Grouped resource-unit-hours multiply that time
by the fixed resource count. GPU-hours and vCPU-hours are never combined into one
resource-hour total. Episode counts describe runs or fleet episodes, not numbers
of independent GPU interruption events. Changing resource counts requires an
upstream representation that preserves episode identity; this format assumes a
fixed count per execution episode.

Neither a failed nor a censored execution becomes a negative interruption label.
The importer does not estimate an hourly hazard or assume a future job duration
from these counts. Completed episodes also have different durations, so their
counts alone do not define a common-horizon interruption probability.

## Validation and time boundaries

- All timestamps must include a timezone and are normalized to UTC.
- IDs must be unique within each record category, even for identical duplicate
  rows. Re-export duplicates must be removed upstream, not counted twice.
- Use one observation per request or execution episode in an export. Incremental
  updates with repeated IDs are not supported. For rolling snapshots, prepare a
  separate export for each cutoff and do not add totals across snapshots.
- Future terminal outcomes are omitted entirely from an earlier `asOf` summary,
  even when the corresponding request/run started before the cutoff. Use recorded
  censored snapshots from that earlier time when such exposure is needed.
- `recordedAt` must not exceed the export's `retrievedAt`; `asOf` cannot exceed it
  either. For historical analysis, use the actual source-record availability time,
  never a retrospectively invented timestamp.
- Unknown fields, missing provenance, inconsistent resource counts, impossible
  timestamps/outcomes, and placement scores supplied as outcome labels are rejected.
- Validation finishes before files are written. Filesystem errors may still leave
  a partial output directory; verify the manifest and hashes before use.

## Outputs and future integration

`observations.json` preserves the complete normalized export, including its
provenance. `summary.json` contains counts and exposure available at `asOf`.
`manifest.json` contains input/output checksums, provenance, and transformations.
The complete export may include records after `asOf`; do not feed it directly to
a historical forecaster. Use `summarize_evidence(dataset, as_of=...)` for a bounded
summary. It does not claim that these source logs were ingested by this application
at the historical time.

This is a Person 1 dataset interface, not a shared API schema change. Person 2
can consume the report once integration is agreed. The risk diagnostic object has
its own `modelVersion`; it must not overwrite a price forecast's model version.
Only `availabilityProbability` and `interruptionProbability` map directly to the
existing nullable `Forecast` risk fields.

Risk probabilities remain null in all three evidence states:

- `NO_OBSERVATIONS`: no records are available at the selected cutoff.
- `SIMULATED_ONLY`: available records are explicitly synthetic.
- `OBSERVED_UNCALIBRATED`: the export declares real observations, but an empirical
  risk model still needs training, chronological evaluation, and calibration.

A large sample count alone does not pass that model-validation gate. Zero observed
interruptions do not become zero predicted risk. No Brier score, calibration
metric, or other model-performance number is produced without a fitted model and
genuine evaluation labels.

When genuine logs are unavailable, use the existing [simulation suite](scenarios/README.md)
for deterministic operational assumptions. Its shortages and interruption events
are explicit test inputs, not inferred probabilities. Optional AWS placement
scores may be retained separately as context; they are not accepted here as
fulfillment/interruption labels and are never divided by ten to create a probability.

## Tests

From `backend/`, with the existing dev dependencies installed:

```sh
python3 -m pytest tests/forecasting/test_operational_data.py -q
```

Tests cover all outcome types, hand-calculated exposure, censored/error handling,
UTC conversion, unavailable future labels, distinct hardware/request sizes,
duplicate rejection, provenance, checksums, and unknown-risk defaults. All test
observations are synthetic, including tests of the `OBSERVED` validation branch.
