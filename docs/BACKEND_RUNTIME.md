# Milestone 4: rolling-horizon integration

Backend wiring is implemented. Genuine ML integration remains dependent on
Person 1 delivering ForecastService: their baseline and model files in this
checkout are still placeholders. No ML or frontend-owned file was changed.
There is no trained-model result, benchmark, Docker run or paid cloud operation
in this milestone.

## Runtime flow

At each scheduling tick the backend:

1. Determines/validates the logical hour and settles confirmed execution outcomes.
2. Polls and saves server-owned observations. Confirmed outcomes remain durable
   even if the market source or subsequent forecasting is unavailable.
3. Builds a chronological history containing only observations available by that
   slot. Source-provided future rows and FORECAST-as-observation rows are rejected.
4. Calls the selected ForecastService for the next six hours and validates the
   returned series, generation slot, target slots, uniqueness and full coverage.
5. Plans against fresh server-owned pending/running jobs and reservations.
6. Atomically records forecasts, decisions, evidence, and SIMULATED starts where
   explicitly selected. It then monitors again on the next poll.

The engine fingerprints observed history, jobs, reservations, slot, policy and
modes. An unchanged poll does not call models again or duplicate decisions or
starts. A new hour, job/status change, price/capacity observation, confirmed
completion/failure, config change or mode change causes forecast refresh and
replanning. POST optimize always forces a fresh planning attempt.

The default lifespan task polls every two seconds, using a worker thread for
blocking source/model/SQLite calls. It shuts down with the application. Errors
remain visible through engine/state and the task retries on later polls.
External monitor/source calls and model inference run outside SQLite writer
transactions. The final scheduling commit reads fresh jobs/reservations and
rejects changed market/history or a competing scheduling commit. New job arrivals
during inference are included in that final plan.

## Modes and provenance

- PAPER is the startup default: decisions are recorded but jobs do not start or
  complete. A plan selecting RUN is an instruction in paper mode, not execution.
- SIMULATED must be explicitly selected through optimize. Immediate starts create
  simulated reservations, and elapsed modeled duration produces explicitly
  simulated completions. This is lifecycle simulation, not a fair benchmark or
  the four-strategy replay system. Advancing several slots in one request does
  not schedule the intervening hours.
- LOCAL dispatch remains unavailable until Milestone 7. Elapsed slots never
  manufacture a local completion. A trusted execution monitor must provide it.
- ML mode requires an injected provider and returns 503 if unavailable or invalid.
  There is no silent fallback, mock ML model, or claimed trained model.
- NAIVE defaults to integration-persistence-v1 in engine/forecast_bridge.py.
  It repeats the latest known price for each series and leaves risk/uncertainty
  null. This temporary integration-owned adapter can be replaced by Person 1's
  naive implementation without changing the optimizer.

The source retains its dataKind and source fields. SIMULATED fixture observations
remain labeled SIMULATED. Decision details and engine state disclose observed,
simulated or mixed input provenance. Forecast modelVersion is retained.

Previously generated forecasts targeting the current slot may supply current
interruption-risk evidence. Their prices never override observed current prices.
Risk interpretation still follows the explicitly documented Milestone 3 scenario;
Person 1 must confirm compatible units/provenance before supplying real risk
outputs. Null risk works without such a model.

## Provider wiring for Person 1

Use existing ForecastService implementations in an application composition module:

```python
from app.main import create_app

# naive_service and ml_service are instances supplied by Person 1.
app = create_app(forecast_services={"NAIVE": naive_service, "ML": ml_service})
```

predict receives ForecastRequest with currentSlot, horizonSlots=6 and chronological
history. Return typed Forecast rows for every observed region/resource/GPU series
at each requested future slot, generated at the request's current slot. Sparse
coverage, duplicate rows, invalid intervals or unavailable predictions fail
explicitly. No trained implementation name is guessed or imported automatically.

create_app also accepts market_source, monitor, clock, optimizer_config and
tick_interval_seconds for composition/testing. Changing model internals behind
this protocol does not require optimizer changes. Model metrics still await
Person 1's evaluation contract/implementation; their endpoint remains 501.

## Source and clock configuration

- COMPUTE_MARKET_FILE: path to a server-owned JSON array of MarketSnapshot rows,
  or an object with a market array. JsonMarketSource rereads it and reveals only
  rows through the logical current slot. It does not load jobs or invent capacity.
- Without a source, market reads are empty and optimize returns
  MARKET_DATA_UNAVAILABLE (503). No fixture is silently loaded.
- COMPUTE_TICK_SECONDS: positive poll interval (default 2), or 0 to disable the
  background task. POST optimize continues to work when polling is disabled.
- COMPUTE_ORIGIN_UTC: optional aware ISO timestamp establishing slot zero for a
  new database. Default: first runtime access's UTC hour boundary. The stored
  origin survives restart; changing the environment does not rewrite that origin.
- COMPUTE_DB_PATH: database location, as documented in BACKEND_PERSISTENCE.md.

Slots remain one hour. Background time is max(last stored slot, elapsed UTC
hours). A manual optimize request can advance logical time, but cannot move it
backward. Use the scenario's actual UTC origin for real historical observations;
relative illustrative fixtures do not establish historical provenance.

## Public API

At Milestone 4 the domain responses remained unchanged. Milestone 4b subsequently
adds nullable availableUnits for unknown AWS capacity; see AWS_MARKET.md.

| Endpoint | Behavior |
| --- | --- |
| GET /api/market | Persisted observation history through the current slot |
| GET /api/forecasts | Latest current-slot batch for the active forecast mode |
| GET /api/forecasts?forecastMode=NAIVE or ML | Latest current-slot batch for that mode, or [] if none |
| POST /api/optimize | Existing OptimizeRequest; returns the existing bare Decision array |
| GET /api/decisions | Persistent decision history |

Two additive read endpoints support the frontend's next integration step:

- GET /api/engine/state: currentSlot, originUtc, forecastMode, executionMode,
  lastTickAtUtc, lastError, autoTickEnabled, mlConfigured and input dataKind.
- GET /api/decisions/details: decisionId, jobId, decidedAtSlot, forecastMode,
  executionMode, deadlineSlackSlots, forecastsUsed, costBreakdown,
  availabilityProbability, interruptionProbability, dataKind and marketSources.
  pricingAssumption additionally discloses critical-deadline persistence tails.

These are typed in api/runtime_schemas.py. Person 3 can add frontend consumers
without changing their existing Decision/Forecast types. Existing historical
decisions from before this milestone may have no corresponding detail record.

POST optimize accepts no authoritative portfolios, predictions, costs or shell
commands. It uses configured services and stored jobs. Missing source/provider,
provider failure, incomplete/invalid forecasts and unavailable LOCAL dispatch
return structured 503 errors. Backward time or inconsistent scheduling inputs
return 409. Malformed request bodies retain FastAPI's 422 format. The legacy
health response is unchanged; stage=SCAFFOLD is not a capability/readiness signal.

## Execution monitoring handoff

ExecutionMonitor.poll(current_slot) returns idempotent ExecutionOutcome values:
job ID, COMPLETED/FAILED, SIMULATED/LOCAL, observed slot and optional reason.
The runtime checks the job, running reservation, start mode and slot before
recording an outcome and releasing capacity. Repeated identical terminal
outcomes do not duplicate events. Conflicting terminal outcomes are rejected.

This is an internal trusted adapter seam, not a frontend endpoint for submitting
execution results. The Docker adapter was pending at Milestone 4; Milestone 7a
now supplies durable local monitoring (see BACKEND_EXECUTION.md). Existing local
RUNNING jobs with expired reservations require a real monitor result; they are
never auto-completed or migrated.

## Persistence and verification

New tables are created additively with CREATE TABLE IF NOT EXISTS: observations,
runtime state, forecast batches and decision details. Existing job/reservation/
decision/audit tables and payloads are preserved. General schema migration tooling
is still a later maintenance concern if existing fields change incompatibly.

Run `.\.venv\Scripts\python.exe -m pytest -q` from backend. All 83 tests pass on
Python 3.12.14; the existing Starlette/httpx deprecation warning remains.
Tests cover chronological
provider inputs, injected NAIVE/ML services, explicit missing-ML errors, malformed
provider responses, stored forecast/detail recovery, background replanning,
capacity and price changes, clock/deadline pressure, idempotent ticks, simulated
restart settlement, trusted monitor failures, durable monitoring during forecast
outages, and the distinction between simulated and local outcomes. Injected test
providers are not trained models or benchmark evidence.

At the end of Milestone 4, real ML integration, frontend consumption, replay,
benchmark accounting and Docker execution remained pending. BACKEND_REPLAY.md
documents the subsequent Milestone 5 replay implementation; real ML, frontend,
and Docker were still pending then. BACKEND_METRICS.md documents the subsequent
Milestone 6 accounting and model-report API; BACKEND_EXECUTION.md documents
Milestone 7a and its verified local Docker run.
