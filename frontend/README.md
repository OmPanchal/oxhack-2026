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
