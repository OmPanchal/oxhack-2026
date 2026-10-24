# Arbitr — Terminal foundation

Run `npm ci` and `npm run dev`, then open http://localhost:3000.

The default **Design preview** is a hand-authored visual example. It does not need a
running backend or environment file. Prices, ranges and proposed actions are labeled
SIMULATED; realized spend, savings and all benchmark counts remain unavailable.
`lib/preview.ts` owns these frontend-only examples; no backend contracts or shared
data fixtures were changed.

Try the region/resource selectors, CPU/GPU workload filter and workload ID buttons.
Selecting a workload updates the decision inspector. The selected action is a visual
fixture, not a new scheduling calculation. All charts draw horizontal/vertical slot
steps and discrete range blocks. Dense tables and charts scroll on narrow screens.

**Backend data** explicitly requests FastAPI, independently of the environment's
mock setting. Configure `NEXT_PUBLIC_API_BASE_URL` if needed. Errors remain visible;
backend mode never silently falls back to preview data. Refresh reloads API state.
Replay, shocks and execution controls await backend implementation.

The mandatory design rules are in the repository's root `AGENTS.md`. Use locally served IBM Plex Sans, square borders, comfortable spacing and the Jet Black / Blue Slate / Silver / White / Coral Glow
palette on white/light-gray surfaces, with Blue Slate as the primary accent and
Coral Glow as a secondary highlight. Theme tokens live in `app/globals.css`.
Workflows are separated into Overview, Workloads, Market, and Replay & execution
tabs. Tabs support arrow keys, Home and End; workload selection persists across tabs.

## Portfolio & workload management

Use **Add job** in Overview or Workloads to open the modal. It supports CPU batch
work and GPU jobs, integer-hour durations, **Complete within (hours)**, allowed
regions, an optional USD budget, and priority. Duration is execution time; the
completion window includes both waiting and execution. A 2-hour job completed
within 6 hours has at most 4 hours to wait. The window cannot be shorter than the
duration. Both fields accept positive whole hours to match the MVP slot size.

The frontend submits `arrivalSlot = currentSlot` and
`deadlineSlot = currentSlot + completeWithinHours`. Backend submission fetches the
latest replay slot and rebases the full window at submit time, so time spent filling
in the modal does not shorten it. No UTC origin/environment setting is required.
The API still receives the existing relative slot fields; no backend schema change
was needed. Countdown labels are relative to the scheduling clock, not a wall-clock
second timer, so replay advances them predictably.

Preview jobs stay in page memory and reset on reload; they are never posted to
FastAPI. Backend jobs use `POST /api/jobs`, and the returned job is authoritative.
Backend storage currently resets with the backend process until Person 2 implements
persistence. Creating a job does not execute it. CPU jobs submit no GPU constraints;
no user-supplied commands/images or execution task IDs are accepted by the form.

The native modal contains keyboard focus, closes with Escape when idle, and restores
focus when closed. Pending submissions are locked; validation/API errors leave the
form open for correction or retry. Search, combined resource/status filters, and
sorting by deadline/priority/name are supported. Details remain available without an
optimizer decision. Attention flags are frontend hints, not official outcome metrics.

Run `npm test` for completion-window validation, submit-time rebasing, filtering,
sorting and attention checks; run `npm run build` for production/type validation.

### Searchable hardware and region selection

GPU models and regions use searchable checkbox multi-selects. Region choices show
readable names and IDs; all listed regions are selected initially. GPU models must
be selected explicitly to avoid assuming workload compatibility. Filtering the
choices never clears existing selections. Select all and Clear affect the entire
choice list. CPU mode ignores any GPU selection retained in the form.

Options come from loaded market/job data. Preview additionally provides A100, H100,
and L4 as **illustrative model choices only**; these do not assert observed capacity.
Backend mode does not add that example catalog.

**Shared contract addition for Person 2:** Job/JobCreate now support
`allowedGpuTypes: string[]`. Several selected models are alternatives for a single
job: the scheduler may allocate `resourceUnits` GPUs of any one listed model.
Single-model jobs retain `gpuType` for compatibility. Multi-model jobs set it to
null and retain every allowed model in the array. CPU jobs submit an empty array.
The Python schema normalizes legacy singular jobs and rejects contradictory
singular/list requirements. The optimizer is still unimplemented; its future
compatibility checks must honor this list. No trained forecasts or price histories
were fabricated for the extra preview model choices.

## Regional comparison & forecast inspection

Market now compares one resource/model at a time. Choose a resource, observed versus
simulated quote data, and the units required. Current quotes, reported capacity,
next-hour predictions, quote age and data kind are shown per region. The descriptive
lowest-current-quote finding requires capacity to cover the requested units and an
observation at the current server slot; it is not an optimizer allocation or savings
metric. Stale or forecast-only regions remain visible, with unknown fields shown as
dashes. Observed, simulated and forecast-as-market rows are never mixed as quotes.

Select a region to inspect its price history and forecasts. Forecast issues are
grouped by generation slot **and model version**; one issue supplies the chart.
Future-generated forecasts are excluded, and 1/3/6-hour views expose only supplied
upcoming targets. A missing next-hour prediction stays missing rather than using a
cheaper later target. Gaps in observations break the step line. No continuous curves
or backfilled prices are fabricated.

Click chart slots, use chart arrow keys, or use the inspection dropdown. The detail
panel distinguishes quotes from predictions and shows the value, supplied bounds,
model version, generation slot/age, and risk probabilities. Missing risk is Unknown;
a genuine zero is 0.0%. Ranges have no invented coverage/confidence level. A fresh
forecast issue does not make a stale market quote current. History uses the last six
scheduling hours and comparisons respect the backend's current slot, not browser time.

Preview adds explicitly hand-authored CPU quotes/forecasts and an earlier GPU issue
in `lib/preview.ts` to exercise these controls. They are not historical observations
or trained-model output. Backend mode continues to use `/api/market` and
`/api/forecasts` and shows empty data without falling back. No backend/schema files
were changed. Unit checks are in `tests/market.test.mjs`.

## Selected workload execution plan

Select a workload in Workloads to see its action, explanation, region, projected
cost, planned start/completion and deadline buffer above the job requirements.
The buffer is a display calculation from the supplied planned end and deadline;
it is not a feasibility certification. Relative labels use scheduling time.
The panel selects the latest decision issued at or before the current slot and
warns when the decision was issued in an earlier slot.

Decision details expose the issue slot, execution mode and reason code. The current
Decision contract does not link forecast issues, uncertainty bounds or risk inputs,
so these remain explicitly unavailable rather than being inferred from market
forecasts. Preview plans remain hand-authored examples; jobs without decisions
show an empty state. No scheduling, execution or savings calculation is performed.

## Replay & execution preview

Design preview now includes three fixed storyboards: normal conditions, a
simulated price spike, and a simulated capacity loss/interruption. Next event
advances to the next supplied snapshot (slots can be skipped); Play advances at
the selected number of events per second. Reset returns to the first snapshot;
changing scenario also resets and pauses. Switching tabs pauses playback and
preserves the selected event. Switching data source resets the preview.

The scenario has its own clock, separate from the portfolio preview. It does not
schedule added jobs or modify the portfolio, market inspection or forecasts.
All snapshots, decisions, task states and logs live in `lib/preview.ts` and are
hand-authored examples. No scheduler, simulator, trained model or Docker task runs.
The execution monitor shows pending/running/completed/failed examples, nullable
start/end, nullable exit code, failure reason, stdout and stderr. Failed work is
explicitly unfinished. Policy metrics remain unavailable; no benchmark is invented.

Backend data shows only its supplied ReplayState, with actions disabled pending
integration. It never displays storyboard events or execution samples. Existing
replay API methods remain available for future coordinated integration; mutations
and detailed execution/event response shapes still require agreement with Person 2.
The presentation components and local view types in `lib/replay-view.ts` can be
fed by an adapter once these contracts exist; those types do not amend the API.

## Visual refinement

Market shows a prominent selected-region quote with its supplied source, data kind
and slot age; stale quotes remain labeled as last supplied quotes. The chart adds
a Blue Slate crosshair and compact readout with only supplied price bounds. Arrow
keys plus Home/End inspect available slots; missing observations remain gaps.

Workloads adds a compact timeline below the queue. Planned execution bars share
one hourly axis and reuse lanes when they do not overlap. A dashed current-slot
marker and grouped coral deadline dots locate key times. Only supplied valid plan windows
are drawn; missing/future/infeasible decisions never acquire a fabricated bar.
Bars are plans, not execution history or a feasibility certification.

Views fade briefly on entry and existing market values receive a restrained outline
when they change. Both effects honor reduced-motion settings. Empty states explain
what is missing in context; policy results remain unavailable. The accepted fonts,
neutral surfaces and palette are preserved.

### Unified replay layout

Replay controls now share a full-width toolbar above a horizontal event timeline.
The timeline exposes the current event and allows review of earlier events, pausing
playback when selected; upcoming event descriptions stay hidden. A compact state
strip shows the selected snapshot's slot, workload, quote and capacity. Execution
plan and Task logs use one detail area with keyboard-accessible tabs (arrows,
Home/End). Policy comparison remains a separate section below. Backend mode uses
the same layout while keeping unavailable events and execution data empty.


The workload timeline uses one shared hourly axis with compact execution lanes.
Supplied windows are sorted deterministically by start/end/ID and reuse a lane
whenever the preceding window ends at or before the next start. Only overlapping
execution needs another lane; waiting intervals are omitted. Coral deadline dots are
grouped by slot above the lanes, including jobs with no execution plan. Unplanned
jobs remain listed separately without acquiring invented execution bars.

Hover or focus on a task/deadline for a hover panel with requirements, supplied
plan, explanation, cost and deadline buffer. Shared-deadline panels list every
associated task. Panels remain open while hovered/focused, allow scrolling, and
close with Escape. Selecting a task or Open full details opens the existing
modal, including on touch screens. The timeline scrolls within its own frame.

### Workload details modal

Selecting a workload name from the overview, queue, or shared timeline opens its
execution plan and job requirements in a native modal. The workload queue and
timeline now use the full content width. Close or Escape dismisses the modal;
focus returns to the triggering control, background interaction is blocked, and
page scrolling is locked while open. On narrow screens the plan and requirements
stack inside the scrollable modal. Missing decisions keep the existing empty state.

### Market inspection modal

Select a region name in the market comparison to open its price chart and slot
inspection together in a popup. Forecast issue, 1/3/6-hour horizon, chart keyboard
navigation and slot selection remain inside the modal. Close or Escape dismisses
it and returns focus to the region button. The native modal contains focus,
blocks background interaction, locks page scrolling and stacks the two sections
on narrower screens. Data provenance, gaps and unknown values are unchanged.

Deadline dots replace the visible Due labels and full-height deadline guides.
Each dot keeps the same exact slot position and groups shared deadlines. Hover,
keyboard focus, or a tap on a shared dot exposes its tasks and deadline values;
selecting an individual task still opens its full details. Only the dot is small;
its keyboard/touch target stays larger.

### Workload views

Within Workloads, Queue and Timeline tabs show one view at a time. The selected
view, queue filters and workload selection persist when switching views or top-level
tabs. The inner tabs support arrow keys, Home and End. Creating a job returns to
Queue; both views retain the same workload-details modal.
