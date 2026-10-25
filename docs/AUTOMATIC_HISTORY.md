# Automatic live model history

Run `./dev --ml`. No daily download command is needed.

For each configured model instance/AZ currently quoted by AWS, startup checks the
168 preceding hourly boundaries in SQLite. It requests the missing span through
`DescribeSpotPriceHistory`, including AWS's effective-price anchor, consumes all
pages, and reconstructs the price effective at each boundary. Whole-instance
prices are divided by the verified GPU count. The current live quote supplies
the final observation, giving the model 169 consecutive inputs.

On each UTC hour rollover only newly required missing boundaries are fetched. A
restart reuses persisted samples; downtime causes a fetch of the missing part of
the rolling window, not another full-week download. Successful observations are
retained in `model_price_history`; complete source events and request/retrieval
provenance are retained in `model_history_fetches`. Current quote archival remains
separate in `aws_quote_batches`. Existing regional index rows are not relabeled.

The unit of identity is region, instance type, AZ, Linux product, GPU model and
GPUs per whole instance. A different pool cannot fill a missing hour. An unchanged
price is valid when anchored by an actual preceding AWS event; no anchor means
missing data. Zero remains zero. Failed pagination commits no partial fetch.

## Live use and temporal safety

Historical prices fetched now are known **now**, not when their effective price
first applied. Every sample and raw fetch retains its receipt time. Only the live
provider receives this history reader, and it rejects requests for a past/future
scheduling hour. Replay gets a separate provider without a live reader. A later
backfill cannot silently improve an earlier replay decision.

The engine's ordinary slot origin may be yesterday; model inputs have their own
UTC boundary keys and are mapped to the model's July origin at inference. This
avoids negative API scheduling slots. Live `/api/market` still represents what
the runtime observed; a retrospective week is not inserted there as live history.

This enables inference without retraining. It is not a historical benchmark or
evidence that ML improves costs. Existing experimental model provenance remains.

## Failure and readiness

Missing anchors, denied reads or other fetch failures leave inputs incomplete.
Current quote ingestion remains available; ML reports an explicit persistence
fallback until inputs are sufficient. Retries are backed off for 60 seconds per
pool. Storage errors are not treated as successful archival.

`GET /api/models/status` includes a `history` object with readiness, each exact
pool's available/required hours, missing boundaries and a sanitized error code.
Market's Forecast model details show the input readiness/counts. `./dev --ml`
waits for historical-input readiness as well as live quote readiness; it times out
with recovery guidance instead of claiming ML inputs are ready. Plain `./dev`
remains a persistence-only alternative.

Collection and recovery require a running backend, valid credentials and the
existing read-only Spot-history permissions. No capacity values or cloud
resources are created. The model's allowlist/availability/zero-price checks still
apply even when the history window is complete.

## Verification — 25 October 2026

Live AWS verification filled 168 prior hours for T4 / eu-north-1a and A10G /
eu-north-1b. SQLite stored 336 inputs and two complete source fetch receipts.
The actual frontend proxy returned 12 genuine LightGBM forecasts with no engine
error. A real process restart retained the inputs, issued no additional historical
fetches and continued producing genuine forecasts. Unit/API checks cover hour
rollover, offline gaps, partial pagination, missing anchors, zero values, unit
conversion, retrieval cutoffs and replay isolation.

Backend suite: 360 passed / 1 skipped / 53 subtests passed. Frontend: 40 passed;
production build passed. Startup regressions: 5 passed. Existing warnings remain.
This verifies live inference and data recovery, not accuracy, cost savings or a
new browser/Docker/cloud-execution demonstration.
