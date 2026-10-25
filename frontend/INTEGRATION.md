# Current ML merge integration

Selected LightGBM artifacts are now present. Use `./dev --ml`, then select ML in
engine controls. The model provider is linked to the persistent engine and replay;
clock offsets and GPU aliases are adapted, and live ML uses fixed instance/AZ
pools. Short history/source mismatch yields named persistence fallbacks. Market
shows serving readiness; policy comparison reports actual model/fallback versions.

`GET /api/forecasts` remains engine-owned and persistent. Explicit POST inference
uses supplied observations and the native model clock without mutating live or
replay state. Native serving metadata is at `/api/models/status`; strict official
model metrics do not mislabel the exploratory packaged report as held-out evidence.
See [the current README](../README.md) and [model serving](../data/forecast-serving.md).

The audit below records earlier verification and counts. Its missing-model remarks
are superseded by this merge; browser interaction and current local execution
still need their separate verification.

# Frontend/backend integration audit — 25 October 2026

The merged backend's implemented contracts are now consumed by Backend data.
Design preview remains isolated. No trained ML provider, paid cloud provisioning,
or genuine Docker run was introduced by this work.

## Current live AWS verification — 25 October 2026

Subsequent to the isolated simulated-data checks below, authenticated AWS access
was verified using profile `arbitr`, selected region `eu-north-1`, and instance
filter `g4dn.xlarge,g5.xlarge`. Both servers were started and their actual Next.js
proxy returned:

- `/api/capabilities`: READY, no regional errors, T4/A10G and two offerings.
- `/api/market/aws/spot`: READY, five observed instance/AZ quotes.
- `/api/market`: two OBSERVED regional GPU price indices, capacity null.
- `/api/forecasts`: twelve `integration-persistence-v1` predictions; no ML provider.
- `/api/engine/state`: PAPER, auto-tick enabled, OBSERVED data, no last error.

The new browser-login credential provider initially failed with
`MissingDependencyException`. Installing `botocore[crt]` and restarting the backend
resolved it. The `aws` extra alone currently omits this optional dependency.
See [AWS operation](../docs/AWS_MARKET.md) for restart/login instructions. These
are recorded verification results, not a claim that a server is always running.

Earlier backend milestone reports record genuine LOCAL Docker execution. It was
not repeated through the current frontend on this Mac. No cloud resources were
launched. The UI flow still needs browser verification; live price reads do not
establish schedulable capacity, multi-region access or model quality.

## Fixed integration gaps

| Area | Before | Now |
| --- | --- | --- |
| API transport | Browser called localhost:8000 directly; 127.0.0.1 frontend could fail backend CORS | Same-origin `/api` rewrite proxies to `API_PROXY_TARGET`, default 127.0.0.1:8000 |
| Scheduling time | Portfolio and job submission used independent replay time | Engine state supplies live currentSlot; refreshed immediately before job submission |
| Updates | One read on mode switch/manual refresh | Non-overlapping five-second polls, retained selection, visible errors, retry |
| Optional failures | One failed request hid the whole portfolio | Jobs and engine are required; individual auxiliary failures remain explicit |
| GPU/region choices | Only loaded observations/jobs | Server capabilities plus loaded observations/jobs; no illustrative backend additions |
| Unknown capacity | Type asserted capacity always existed | Null preserved, displayed unavailable, excluded from opportunity ranking |
| Decisions | First decision in a slot; evidence unavailable | Latest persisted same-slot replan; linked server evidence when ordered snapshots match |
| Replay | Backend controls disabled | Reset/step/serialized playback, registered scenario ID/seed, policy/workload inspection |
| Shocks | Prepared preview variants only | Backend simulated price spike, capacity shortage and interruption forms |
| Policy accounting | Empty shell | Server totals and comparability explanations; no client savings calculation |
| Execution | Preview state/logs only | Allowlisted task catalog, explicit task creation/start, polled LOCAL telemetry |
| Dispatch | Not exposed | Server-confirmed pause/resume and replan; running outcomes keep polling |
| Model metrics | Not read | Server evaluation status/metrics exposed in Market; missing ML stays unavailable |

The public backend JSON schema was not changed. TypeScript now mirrors its
additive monitoring, replay, metric and execution responses. Detailed types list
the fields the UI uses; extra server response fields are not rejected.

### GPU alternatives integration correction

The merged schema accepted `allowedGpuTypes`, but the optimizer and immediate
policies still compared only singular `gpuType`, and reservation commits copied
that potentially null value. Multi-model jobs consequently had no compatible
allocation.

The existing contract is now enforced: each candidate selects one acceptable GPU
model, all requested units come from that pool, capacity remains shared, running
reservations validate against alternatives, and live/replay commits retain the
chosen model. Legacy singular jobs and unrestricted GPU requirements still work.

`OptimizationPlan.allocations` and the optional `immediate_policy` allocation
collector are internal interfaces for retaining this selection. Public Decision,
Job, reservation and API schemas stay unchanged. The chosen model is also named
in optimizer explanations.

## Runtime behavior

The page starts in Design preview. Select Backend data to use FastAPI. Reads and
mutations in that mode never fall back to preview, even if the environment mock
flag is set. Core API outages leave an explicit error; a later polling read can
recover. Auxiliary failures show their own messages, not fabricated results.

Engine and replay clocks/portfolios are independent. Creating a live job always
uses `/api/engine/state`, never `/api/replay/state`. Replay's currentSlot is the
next unprocessed interval; stepping processes one hour and does not advance live
time. Replay mutations are serialized. Leaving the Replay subview or main tab
pauses playback. Reset does not clear live jobs.

Backend reads:
- `/api/jobs`, `/api/engine/state`, `/api/market`, `/api/forecasts`, `/api/decisions`
- `/api/decisions/details`, `/api/capabilities`
- `/api/replay/state`, `/api/metrics?scope=REPLAY`, `/api/metrics?scope=LIVE`
- `/api/models/metrics`, `/api/execution/tasks`, `/api/executions`

Backend mutations:
- `/api/jobs`, `/api/optimize`, `/api/engine/pause`, `/api/engine/resume`
- `/api/replay/reset`, `/api/replay/step`, `/api/replay/shock`
- `/api/execute/{jobId}` (server-allowlisted tasks only)

The UI exposes three regional replay shock kinds. The backend's JOB_ARRIVAL and
DEADLINE_PRESSURE payloads are typed in the client, but have no dedicated form.
The current backend has no scenario-list endpoint: the UI accepts a registered
scenario ID, defaulting to `capacity-pressure` when no replay exists. The named selector
also offers `demo` and custom IDs, with useful errors for unknown registrations.

Decision responses have no ID. Evidence is displayed only when ordered decision
and detail collections form a complete one-to-one matching snapshot by job, slot
and execution mode. A concurrent/incomplete read leaves evidence unavailable until
the next poll instead of associating unrelated forecasts. No schema extension
was introduced to bypass this limitation.

Local tasks come exclusively from the backend catalog. Selecting a task supplies
its CPU count, local region and task ID; GPU constraints are stripped. The UI never
accepts commands/images. Manual starts are locked while pending and blocked when
backend dispatch is paused. STARTING is distinct from RUNNING. Logs preserve zero
exit codes, monitor errors, truncation and timeout warnings. Local execution never
claims regional cloud execution or realized financial savings.

## Verification completed

- Backend: `python3 -m pytest -q` — **173 passed, 2 skipped**.
- Frontend: `npm test` — **39 passed**.
- Frontend: `npm run build` — passed compilation, TypeScript and prerendering.
- `git diff --check` — clean.
- Used the actual TypeScript API client through the running Next.js `/api` proxy
  against a real FastAPI process with isolated temporary SQLite and explicitly
  SIMULATED observations. Confirmed:
  - Live slot 7 and independent replay slot 0 remain distinct.
  - Create/reload retains two GPU alternatives, null singular model, arrival 7
    and the full six-hour deadline window ending at 13.
  - A two-GPU job selects H100 when only one A100 is available; PAPER keeps it pending.
  - Decision detail joins, unknown-capacity handling and pause/resume round trips.
  - Missing ML and deliberately disabled Docker return explicit 503 codes; no fallback.
  - Replay reset/step/shock, all four policy statuses and official metrics.
  - Repeating seed 42 and the same shock produces identical replay metrics.
  - Actual process restart retains jobs, resource alternatives, deadlines, engine
    clock and replay accounting.
- New backend regressions cover mixed-model prohibition, shared capacity,
  running alternative-model reservations, unrestricted legacy GPU jobs, API
  persistence and replay policy reservation/charging.

The isolated HTTP check deliberately disabled Docker before any start could be
submitted. Its 503 check is error-path evidence, not genuine execution evidence.
The temporary scripts/database/results are under
`/private/tmp/arbitr-link-check-lc9y3zc6/` and are not production app state.

## Remaining limits

- No browser is connected to the automation session, so modal interactions,
  visual layout, and playback UI timing have not been browser-verified.
- Selected ML artifacts and the clock/source integration now exist. Plain startup
  leaves ML disabled; `./dev --ml` enables it. Genuine live inference additionally
  requires sufficient matching history. The packaged report is exploratory.
- Live AWS source configuration and reads are now verified for Stockholm. AWS
  prices still have unknown capacity and are not allocatable opportunities. A
  labeled live-price/simulated-capacity hybrid has not been implemented.
- A working local Docker SDK/daemon is needed for genuine LOCAL execution. This
  audit did not launch a real container or paid cloud resources.
- Same-origin proxy access is verified. An explicit cross-origin
  NEXT_PUBLIC_API_BASE_URL still requires the corresponding backend CORS origin.

## Capacity pressure scenario — 25 October 2026

Added the server-registered `capacity-pressure` simulation with seven workloads,
three region/GPU pools and eight hourly intervals. The frontend offers named
presets/custom IDs and shows last-processed-slot pool capacity. It never exposes
future capacity and preserves zero/unknown values. Live AWS state stays isolated.
See [scenario assumptions and checks](../docs/CAPACITY_SCENARIOS.md).

Recorded checks: backend 184 passed / 1 skipped; frontend logic 40 passed;
production build passed compilation, types and prerendering. These are separate from the earlier test counts and do not establish a browser
interaction walkthrough or a new genuine Docker run.

## ML merge verification — 25 October 2026

The original conflict was in `backend/app/main.py`: the ML branch's process-local
API overlapped the persistent backend composition. Resolution retained SQLite,
engine/replay/execution endpoints, detailed quote archival and frontend behavior,
then connected the selected models through `SelectedModelProvider`.

Changed integration contracts:

- Optional factory `forecast_service` injection remains supported. Deployment uses
  `COMPUTE_ENABLE_ML=1`, supplied by `./dev --ml`; model absence stays explicit.
- Native model origin maps to engine/replay origin without changing public slots.
  GPU aliases map back to the caller's API key. Live selected-model pricing uses
  fixed instance/AZ identity and refuses regional-index history as model input.
- Explicit POST inference is separate from persisted GET engine forecasts.
- New `/api/models/status` carries serving provenance; strict `/api/models/metrics`
  is preserved. The original report is experimental and not promoted into a clean
  held-out evaluation.
- Replay accumulates `modelVersionsUsed` so warm-up/fallback predictions remain
  disclosed after genuine inference begins. Current metrics and the policy UI
  show the cumulative versions. Older persisted sessions default this list safely.

Verification includes real saved-weight parity after origin/GPU mapping, persisted
forecasts after reopening the database, decision evidence, source-identity rejection,
ML replay warm-up and completion, and fixed AZ selection despite a cheaper other AZ.
The live app reports READY LightGBM artifacts, enabled ML, no engine error and fixed
Stockholm T4/A10G quotes. A PAPER replan retained explicit source-history fallback;
old index observations were not reclassified as matching model data.
Twelve genuine forecasts from the packaged SIMULATED example were verified through
the actual Next.js proxy without overwriting official live forecasts.

Frontend: 40 tests passed and production compilation/types/prerendering passed.
Startup: 5 regressions passed; `./dev --check --ml` and live `./dev --ml` passed.
OpenMP was missing on this Mac and was installed before real-model verification.
Two offline experiment tests used exact float/JSON byte equality; they now allow
only 1e-12 absolute floating-point rounding while keeping structure, identities,
integer counts, selections and protected-period checks exact. No trained weights,
feature implementation, evaluation report or protected data were changed.

No browser interaction, new Docker run, cloud allocation, live ML accuracy gain or
scheduler savings is claimed by this merge verification.

Final combined backend rerun: **354 passed, 1 skipped, 53 subtests passed**.
Existing Starlette/httpx and physical-core-detection warnings remain.

## Automatic live history — 25 October 2026

The live AWS ML source now backfills and persists missing fixed-pool historical
boundaries, uses 168 prior observations plus the current quote, and repairs the
rolling window after hour changes/downtime. Runtime history stays separate from
replay; retrieval timestamps prevent retrospective data from becoming earlier
known observations. Model status and the Market details disclose input readiness,
per-pool counts and sanitized failures. `./dev --ml` checks that readiness.

Actual frontend-proxy verification: T4 in eu-north-1a and A10G in eu-north-1b both
reported 168/168 historical inputs. SQLite retained 336 samples/two source fetches.
GET /api/forecasts returned 12 genuine saved LightGBM outputs; engine ML mode had
no last error, and live capacity remained null. This is genuine live inference,
not just the earlier packaged SIMULATED example. No accuracy/savings claim follows.

Tests: backend 360 passed / 1 skipped / 53 subtests passed; frontend 40 passed;
startup 5 passed; frontend production build passed. Existing warnings remain.

Real process restart reused all 336 inputs/two source receipts without new
historical requests and continued returning 12 genuine forecasts.
