# Person 1 Milestone 1: forecasting and hourly data contract

This document records the implemented Person 1 integration defaults. The existing
shared API schemas remain the source of truth. Person 2 and Person 3 still need
to confirm these defaults for engine and frontend integration; this document does
not claim that team review has happened. The public forecast service signature
is unchanged.

## 1. Clock, prices, and resources

- Slots are integer UTC hours relative to a recorded scenario/dataset origin.
  For origin `2026-10-24T00:00:00Z`, slot 2 starts at `02:00:00Z`. Origins and
  scheduling boundaries must align exactly to UTC hours; ambiguous naive times
  and silent rounding are rejected.
- Execution intervals are `[startSlot, endSlot)`. A job ending exactly at its
  deadline is feasible. Forecast target slot `t` means the price effective at
  the start of that hour, not a retrospectively known hourly average.
- A decision at slot `t` may use observations at or before `t`. A requested
  horizon of six returns targets `t+1` through `t+6` for each represented pool.
- Prices are USD per GPU-hour or vCPU-hour after verified hardware conversion.
  Preserve original instance prices, instance identity, and allocation size.
  Whole AWS instances must still be allocated/billed as whole instances.
- Unknown capacity is not zero capacity. Hourly price records have no
  `availableUnits` field and are not automatically API `MarketSnapshot` objects.

The executable checks are in
[contracts.py](../backend/app/forecasting/contracts.py). UTC conversion, forecast
coverage, duplicate detection, hardware identity, and null/bound handling are
covered by the Person 1 test suite.

## 2. Exact pool selection before API projection

The data pipeline retains separate series for `(region, availabilityZone,
instanceType, productDescription)`. It never picks the cheapest zone retrospectively.
The current API only identifies a pool by `(region, resourceType, gpuType)`.

For the MVP, Person 2's adapter must configure one fixed compatible instance/AZ/
product series per API pool key before evaluating the replay. Two source series
cannot silently collapse into that one key. Changing that selection is an explicit
configuration/replay change. GPU model names alone do not prove all job memory,
architecture, or instance requirements are satisfied.

The contract fixture records two example selections. Both are simulated; they
are not verification of current AWS offerings. The existing UI fixture remains
unchanged and may use different GPU types.

If historical prices are combined with simulated capacity, the projected market
record is `SIMULATED`. Retain separate price/capacity provenance in the dataset
envelope. Otherwise obtain genuine capacity before constructing an observed
market record. Person 2 owns this adapter integration.

## 3. Forecast request and response behavior

The service remains `ForecastService.predict(ForecastRequest) -> list[Forecast]`.
Use `current_observations` before inference and `validate_forecasts` on output:

- Empty history has no represented pools and produces an empty forecast list.
  Do not invent prices for a new or missing resource.
- Every represented pool requires a snapshot at `currentSlot`. An older snapshot
  raises an explicit stale-input error. This differs from an unchanged price-change
  event: reconstructing that event at a current boundary can still produce a
  valid current observation when the source history is complete.
- Identical duplicate snapshots are harmless. Conflicting price, capacity, or
  provenance for one pool/slot raises an error. Inputs may arrive out of order.
- GPU pools require a specific nonblank `gpuType`; CPU pools require null.
- Shared request validation rejects future rows and forecast-as-history rows.
  Source collection and feature builders must also respect those time boundaries.
- Return exactly one forecast per represented pool and requested target. Generation
  time must equal `currentSlot`; duplicate, missing, and out-of-horizon outputs
  are rejected. Model provenance must be nonblank.
- Leave both uncertainty bounds null until justified. If provided, both bounds
  must be present and bracket the predicted price. Unknown risk remains null.
- Requests beyond six hours are rejected by the existing schema. Do not extend a
  forecast by silently repeating its last value. The engine must not commit an
  execution window containing unpriced hours without a separately configured
  supported quote/fallback. Person 2 must surface unsupported pricing coverage
  rather than claiming those windows are reliably priced.

These checks are reusable for the persistence and ML services in Milestone 2.
Both services are now implemented separately; see [the Milestone 2 handoff](milestone2.md).
The contract demonstration itself still uses hand-authored predictions.

## 4. Historical hourly reconstruction and charging

[hourly_data.py](../backend/app/forecasting/hourly_data.py) consumes the normalized
price events from Dataset Step 2. At each boundary it selects only the latest
event timestamp at or before that boundary. Events exactly at the next hour do
not affect the previous hour. A pre-window effective-price anchor is retained.

A missing earlier event yields `NO_PAST_PRICE` and null prices; the pipeline never
backfills from the future. An old unchanged price is not itself evidence of a
collection gap. Within a fully collected source window, carry-forward assumes
the provider's price-change history is complete.

Known collection gaps can be supplied explicitly as a JSON array. Every gap names
the four source identity fields and timezone-aware `startTime`/`endTime`. The gap
is half-open. A start price affected by the gap is `INGESTION_GAP` and remains
unknown after the gap until a reliable event at or after the gap end appears.
The pipeline cannot detect an unreported provider or ingestion failure merely
from an event-free interval.

The MVP proposed replay convention is to hold each slot-start price for one hour.
`slot_cost` uses the original instance price and positive whole-instance allocations
to implement that convention. For a four-vCPU instance priced at USD 0.20/hour,
four allocated units cost USD 0.20, eight cost USD 0.40, and a fractional-instance
allocation is rejected. Person 2 must confirm this convention in the replay engine.

The separate `timeWeightedAveragePriceUsdPerUnitHour` diagnostic integrates all
changes during a full hour. It is only known retrospectively and must not be
passed to a model at that hour's start. For example, a GPU price of USD 0.30 until
00:30 and USD 0.60 after 00:30 has a slot-start price of USD 0.30 and a full-hour
average of USD 0.45. The MVP slot-based replay charge is an explicit approximation
and is not a claim about actual AWS invoicing. Changing replay to integrated
charging requires an explicit convention update and consistent comparisons.

Every prepared dataset reports per-series event counts, resource mapping, known
and missing hourly prices, gap counts, duplicates, source hashes, and whether it
has at least 60 usable days. No availability or interruption labels are inferred.
Historical event timestamps are assumed to reflect when source prices became
known; delayed publication would require additional availability timestamps.

## 5. Data access and preparation commands

The chosen primary source is authenticated, read-only AWS Spot price history.
The configured candidates are three regions and a common GPU type, with optional
CPU expansion. The source documentation, retrieval commands, and metadata
collection are in [provenance.md](provenance.md). Actual regional offerings and
usable coverage must be verified after collection; they are not asserted here.

The user has collected and supplied a genuine CloudShell export. It contains
89 days for `g4dn.xlarge` in Stockholm (`eu-north-1`) across three Availability
Zones. Raw prices, hardware metadata, and conversions have been checked locally.
See the [collection record](provenance.md#real-collection-001--imported-24-october-2026).
The requested three-region coverage is not met; the three zones are all within
one region. Do not claim real forecasting performance until evaluation is run.

From `backend/`, after Steps 1 and 2 have produced a checksummed collection:

```sh
python3 -m app.forecasting.hourly_data \
  --collection ../data/raw/resource-metadata-001 \
  --start YOUR_UTC_HOURLY_START --end YOUR_UTC_HOURLY_END \
  --output ../data/processed/hourly-prices-001
```

Step 2 now records `inputPriceWindow` and its source-pagination completeness in
the metadata manifest. Recreate older Step 2 outputs missing that field. The
preparation command verifies metadata and normalized-price hashes, rechecks the
metadata joins/conversions, and rejects a requested window outside the complete
source window. An existing preparation directory is never overwritten.

To demonstrate reconstruction offline:

```sh
python3 -m app.forecasting.hourly_data \
  --fixture ../data/examples/hourly-price-events.simulated.json \
  --start 2026-10-24T00:00:00Z --end 2026-10-24T04:00:00Z \
  --output ../data/processed/hourly-example
```

This creates eight explicitly simulated records from two series, with
`hourly-prices.jsonl` and `manifest.json`. The checked-in
[prepared example](examples/prepared-hourly-simulated/manifest.json) demonstrates
the quality-report format and does not satisfy the real-data coverage target.

## 6. Callable forecast fixture and milestone handoff

[forecast-contract.simulated.json](examples/forecast-contract.simulated.json)
contains an origin, fixed pool selections, a valid request, and twelve hand-authored
forecast outputs: six future targets for each of two pools. Prices are illustrative;
bounds and risk probabilities remain null. Versions start `contract-fixture-`.

With the existing backend dependencies installed, Person 2 can call it in Python:

```python
import json
from pathlib import Path
from app.api.schemas import ForecastRequest
from app.forecasting.contracts import FixtureForecastService

path = Path("../data/examples/forecast-contract.simulated.json")
request = ForecastRequest.model_validate(json.loads(path.read_text())["request"])
forecasts = FixtureForecastService(path).predict(request)
```

The fixture service accepts only that exact demonstration request and returns
fresh validated objects. It deliberately cannot masquerade as a general forecaster.
Person 2 can build against the shared response schema now, then replace this
service with the persistence/ML implementations described in [Milestone 2](milestone2.md).

Run the Milestone 1 checks from `backend/`:

```sh
python3 -m pytest tests/forecasting/test_milestone1_contracts.py tests/forecasting/test_hourly_data.py -q
```

Handoff status:

- Step 1: executable conventions and documented defaults delivered; teammate
  confirmation remains pending.
- Step 2: acquisition/audit tooling delivered and the first genuine export
  imported and checked. Three-region expansion remains pending access.
- Step 3: hourly reconstruction, missing/gap handling, and hand-calculated cost
  checks delivered.
- Step 4: labeled request/response fixture and callable service delivered and
  checked against the existing forecast and optimizer input schemas.

Milestone 1 implementation and the initial one-region data preparation are ready
for review. Team agreement and the original three-region data target remain open.
Model training, forecast accuracy metrics, and replay savings belong to subsequent
milestones.
