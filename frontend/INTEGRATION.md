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
scenario ID, default `demo`, and displays a useful error for unknown IDs.

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
- Genuine ML requires backend provider injection/configuration and its model
  artifacts. The merged default reports mlConfigured=false and ML replay UNAVAILABLE.
- Live AWS source configuration and reads are now verified for Stockholm. AWS
  prices still have unknown capacity and are not allocatable opportunities. A
  labeled live-price/simulated-capacity hybrid has not been implemented.
- A working local Docker SDK/daemon is needed for genuine LOCAL execution. This
  audit did not launch a real container or paid cloud resources.
- Same-origin proxy access is verified. An explicit cross-origin
  NEXT_PUBLIC_API_BASE_URL still requires the corresponding backend CORS origin.
