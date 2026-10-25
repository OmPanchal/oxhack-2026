# arbitr — compute execution terminal

Run `npm ci` and `npm run dev`, then open http://localhost:3000.

The page starts in **Design preview**, using labeled hand-authored examples in
`lib/preview.ts`. Preview job creation remains in page memory; examples are never
submitted to FastAPI and do not represent model results, benchmarks or execution.

Select **Backend data** to use the merged FastAPI services. Full endpoint mapping,
verification and limitations are recorded in [INTEGRATION.md](INTEGRATION.md).

## Local backend connection

From the repository root, start FastAPI in a Python environment with the backend
installed:

```sh
cd backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend requests use a same-origin `/api` proxy, so both localhost:3000 and
127.0.0.1:3000 work without different browser CORS settings. The default proxy
target is `http://127.0.0.1:8000`. Copy `.env.local.example` to `.env.local` to
customize `API_PROXY_TARGET`, then restart Next.js after changing it. An explicit
`NEXT_PUBLIC_API_BASE_URL` bypasses that proxy and needs matching backend CORS.

Backend mode polls every five seconds and never substitutes example data. Read
errors remain visible. Market/ML configuration errors are distinct from failed
connections. The default backend needs a market source configured for live
planning; an actual ML provider is optional and its absence is explicit.

## Current live setup

Profile `arbitr` in `eu-north-1` has verified live T4/A10G quotes. Follow
[the AWS setup guide](../docs/AWS_MARKET.md) to start the backend with that source;
starting FastAPI without those settings does not automatically select AWS.
Forecasts currently use persistence. Unknown Spot capacity prevents live pool
allocation; simulated replay remains separate. No cloud provisioning is implemented.

## Views

- **Overview:** portfolio counts, server projected cost, attention items and
  upcoming jobs. Projections are not realized spend or savings.
- **Workloads:** Queue and Timeline tabs. Workload selection opens a modal with
  requirements, execution plan and available backend evidence.
- **Market:** compare matching resources/GPUs and separate observed/simulated
  quotes. Selecting a region opens history, forecast issue/horizon and slot
  inspection. Unknown capacity is never treated as schedulable capacity.
- **Replay & execution:** Replay, Policy comparison and Execution views. Backend
  reset, step, playback and simulated shocks use the independent replay clock.
  Accounting and comparison eligibility come from the server. Real LOCAL task
  records stay separate from simulated replay and prepared preview states.

The accepted light theme, IBM Plex Sans, BROKEN PIXELS wordmark, square borders,
neutral panels, Blue Slate controls and restrained coral charts/deadlines remain.
Theme tokens live in `app/globals.css`; the font license is alongside its asset in
`app/fonts/`. BROKEN PIXELS is used for personal/non-commercial preview.

## Jobs and execution

Add job uses a modal with separate integer-hour Duration and Complete within
inputs. The completion window includes waiting and execution. Backend submission
refreshes `/api/engine/state` and rebases the complete requested window immediately
before POSTing. SQLite owns persistence across refresh and backend restart.

Regions and GPU models use searchable checkbox multi-selects. Search preserves
selections; all listed regions start selected, while GPU choices require explicit
selection. Multiple GPU models are alternatives: all resource units must come
from one acceptable model. CPU jobs strip GPU constraints. The backend optimizer,
reservations and replay policies enforce this contract.

Backend Add job also offers server-allowlisted LOCAL CPU tasks. Selecting a task
uses its fixed hardware and local region. Execution follows the backend dispatch
policy, or an explicit Run local task action in the Execution view. Users cannot
enter commands/images. Engine controls show backend-confirmed pause/resume,
forecast availability, current mode and errors. Pausing new starts does not stop
running work or monitoring.

## Charts, timeline and inspection

Charts use discrete hourly steps, one forecast issue/model at a time, supplied
bounds and visible missing-data gaps. Click/arrow keys/Home/End or the slot selector
inspect values. Quote age and forecast issue age remain distinct. No confidence
coverage, risk probabilities or savings are invented.

The compact workload timeline packs only overlapping execution windows into extra
lanes. Jobs without plans remain listed without invented bars. All plans share one
hourly axis. Coral deadline dots sit above the plot; shared dots retain every task.
Hover/focus shows details, and click/tap opens the full modal. Reduced-motion
settings disable the subtle view/value animations.

Native modals contain focus, close with Escape and restore focus to the triggering
control. Inner and main tabs support arrows/Home/End. Dense timeline/table content
scrolls within its own frame on small screens.

## Checks

```sh
npm test
npm run build
```

These checks cover API paths/payloads/errors, clock separation, job requirements,
market matching, null capacity, forecast grouping, decision evidence, interval
packing and preview fixtures. A build is not browser or genuine Docker evidence.
See the integration report for the actual HTTP/process-restart verification.
