# Arbitr frontend review

## Scope and direction

Applied `design-taste-frontend` using its **app-screen** workflow. This is a focused
polish of the accepted design, not a new product layout. Only frontend styling and
the overview's finding sentence changed. Backend files were not changed.

Dealt style: **Achromatic Ledger**, seed **241026**, with palette and type kept.
No redraws. The suggested icon rail, near-black primary and smaller app title were
not adopted because the user explicitly chose the combined wordmark/tab header,
Blue Slate controls, neutral white surfaces, and a prominent 36px Arbitr wordmark.
These accepted constraints take precedence over the skill's defaults.

Face: locally served IBM Plex Sans. Signature element: deadline pressure next to
the workload it affects, with a computed overview finding and inspectable plans.
The live workflow is Add job → inspect requirements, with a searchable selection
of acceptable hardware and regions and a relative completion window.

## Data inventory

- Buy-side compute scheduling for a firm's workload portfolio.
- Six explicit preview workloads, not execution results.
- CPU batch work and GPU jobs with counts of resource units.
- A100 price examples in eu-west-1, eu-central-1, and us-east-1.
- Hourly non-preemptive durations and relative completion windows.
- Decisions WAIT, RUN and ROUTE are hand-authored visual examples.
- Deadline pressure is a UI hint computed from remaining scheduling slack.
- Budgets in USD; no realized spend or savings claimed.
- Multiple acceptable GPU models are alternatives for one job.
- Real backend mode remains separate from preview memory.

Sample content remains in `frontend/lib/preview.ts`: embedding-batch-v4,
risk-simulation, finetune-adapter, feature-materialize, vision-evaluation, and
archive-compression; all price curves, forecast ranges and sample decisions in that
file must be replaced by real API outputs for an operational demo. H100 and L4 are
illustrative catalog choices in preview, not observed available capacity.
No photographs, illustrations, external testimonials or invented performance
benchmarks were added.

## Questions by screen

- Overview: which workloads need attention now?
- Workloads: what requirements and plan belong to the selected job?
- Market: how do this region's slot prices and forecasts compare?
- Replay & execution: are scenario controls and execution results available?
- Add job: what resources and completion window should the scheduler accept?

## Changes and checks

| Check | Before | Final |
| --- | --- | --- |
| Inspector, 1440 / 768 / 390 | 2 distinct failures, 3 warnings | 0 failures, 1 warning |
| Text under 11px | 12 blocks | 0 |
| Smallest CSS text size | 10px | 12px |
| Phone last tab | Clipped at the right edge | All four labels fit |
| Heavy panel-border warning | Present | Absent |
| Typeface | IBM Plex Sans | IBM Plex Sans, verified loaded |
| Brand size | 36px | 36px, preserved by explicit user preference |
| Frontend unit tests | — | 9 passed |
| Production build | — | Passed, including TypeScript |

The inspector's remaining `no-data-hue` warning is a false positive: its regular
expression treats `.metric-strip` as a chart because it matches `strip`. Overview
contains a numeric KPI grid, not a plot. The actual Market chart was inspected
separately and renders slate historical steps, a dashed coral forecast and labeled
ranges. The warning remains visible in the raw report; it was not hidden by a
source rename or fabricated chart.

The single inspector allowance is `app-title-size`, justified by the user's request
for the larger Arbitr wordmark. Source lint has 0 failures and 3 warnings:
functional hover inset strokes (not decorative resting shadows), zero-padded
hourly slot labels (not decorative index numbering), and em dashes for missing
backend measurements (not invented zeros).

## Screenshot critique

1. **Hierarchy:** the computed “3 workloads need attention · 6 pending” finding
   replaces generic overview instructions. The action remains one click away.
2. **Frame:** equal outer margins and the accepted panel structure remain. Colored
   card-top borders were removed; the fields retain stronger interactive borders.
3. **Color:** the user palette is preserved. Neutral surfaces stay neutral; no new
   decorative imagery or color system was introduced.
4. **Arithmetic:** six preview jobs = six pending, zero running, zero completed,
   zero failed/infeasible. Three pressure hints come from the same job rows used by
   the attention list. Browser-created test jobs increased the queue to seven.
5. **States:** zeros remain zeros, missing benchmark values remain dashes, and
   unavailable replay/execution controls remain disabled. No execution was faked.
6. **Charts:** discrete slot paths remain horizontal/vertical steps. Forecasts
   retain distinct dash and color treatments. The market view is intentionally
   horizontally scrollable on narrow screens.
7. **Phone:** tab clipping is fixed and touch targets enlarged. Dense tables still
   require horizontal scrolling; a future dedicated phone list/detail treatment
   would improve usability. This pass preserved the user's accepted tab layout.

Every image in `before/`, `final/`, and `states/` was opened for visual review.
The interim `after/` inspection was superseded by `final/` after label refinements.

## Interaction verification

`exercise.mjs` tested 1440px, 768px, and 390px:

- Open the native job modal.
- Hover the GPU selector: white background with an inset border.
- Select two GPU models and search without losing selections.
- Escape closes the selector while keeping the job modal open.
- Create a CPU preview job and verify its selected details and seven queue rows.
- Switch to Market and verify a step path.
- Switch to Replay and verify unavailable controls remain disabled.
- Record zero JavaScript exceptions at all three widths.

The initial interaction script used a missing DOM autofocus attribute as its name
field locator; it was corrected to the actual labeled field and the whole check
was rerun successfully. All jobs created during these checks were ephemeral
browser-preview jobs. No API jobs or cloud resources were created.

Artifacts: `before/report.json`, `final/report.json`, and `states/checks.json`.
Production preview: http://127.0.0.1:3001. Development preview remains on port 3000.
