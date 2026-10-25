# Arbitr — regional comparison and forecast inspection

Kept the accepted app direction: neutral light surfaces, IBM Plex Sans, Blue Slate,
Coral Glow forecasts, square borders, the prominent Arbitr wordmark and the shared
tab header. Reused the existing Achromatic Ledger direction (seed 241026); no new
draw or redraw for these components. User-approved brand/header rules take
precedence over the skill's generic app-title limit.

## Questions and substance

- Comparison: which matching regional quote is lowest *now* and reports enough
  units for the request?
- Trajectory: what was quoted and what does one specific model issue predict?
- Inspection: what exact value, bounds, provenance and risk belong to this slot?

The finding is computed from current-slot quotes, separated by resource/GPU model
and observed/simulated kind. Insufficient or stale quotes cannot become the lowest
current opportunity. This is descriptive price comparison, never a reservation,
optimizer decision, benchmark or realized savings claim.

## Interface and interaction

Resource, quote-kind and unit controls scope the regional table. Region selection
opens that region's step plot and inspection. Issue controls keep generation/model
runs separate; horizons are 1, 3 and 6 hours. Slot selection works by click, arrow
keys, or native select. Small screens use paired regional facts rather than a
wide clipped table; chart geometry adapts to its actual container width without
shrinking labels or requiring horizontal chart scrolling.

The inspector shows quote sources, quote ages, model versions, generation times,
supplied bounds and probabilities. Null risk is Unknown; zero is 0.0%. No coverage
level, calibration score or trained model is invented. Missing observations break
paths, and future-generated rows are excluded. A forecast-only region has missing
quote/capacity values, not fake zeros.

## Evidence

- 17 frontend unit tests pass, including 8 new market tests.
- Production build and its TypeScript validation pass.
- New component source lint: 0 failures, 0 warnings.
- Skill browser probes/rules on the Market view at 1440, 768 and 390px:
  **0 failures, 0 warnings** after the phone numeric-alignment fix.
- The explicit `app-title-size` allowance preserves the user's 36px wordmark.
- The browser harness clicks the Market tab before applying the skill's exported
  probe/layout/app measurements and rules. This is not a claim that the stock
  inspector CLI navigates the product's tabs automatically.
- Browser interaction checks pass at all three widths: unit capacity changes,
  region selection, issue/horizon changes, quote inspection, arrow-key navigation,
  CPU isolation, observed/simulated separation, and no JavaScript exceptions.
- The empty-backend case is an isolated browser fetch fixture; it proves no mock
  fallback and does not claim real backend integration has been exercised.

Artifacts: `checks.json`, default and CPU screenshots at all three widths, and
`empty-backend.jpg`. Every final screenshot was opened and reviewed.

## Seven-pass visual critique

1. Hierarchy: matching regional prices/capacity come first, with the finding next
   to the controls. Region trajectory and exact evidence follow together.
2. Frame: shared outer margins and 24px panel spacing remain. Inspector retains its
   content height rather than adding blank space to match the plot.
3. Color: slate historical steps and coral dashed forecast retain the approved
   palette; the range swatch and the plot share the same 12% tint.
4. Arithmetic: quotes and forecasts are per unit-hour, with no invented workload
   costs. Frankfurt's A100 example quote is $1.180 for 2 available units; a request
   for 3 units excludes it and makes N. Virginia's $1.300 / 4-unit quote lowest.
5. States: missing measurements remain dashes/Unknown; real zeros are retained.
   Forecast generation age and quote age remain independent.
6. Geometry: horizontal/vertical slot steps have real gaps, a y scale and a forecast
   boundary. The selected value has a marker; a separate selector provides exact
   values without requiring a pointer. Bounds have no claimed confidence level.
7. Phone: regional facts remain readable and numerical fields align right; plots
   resize rather than clip. Inspection is stacked below the plot, so the mobile
   view requires vertical scrolling but retains every field.

## Samples and remaining integration limits

Existing GPU preview curves/decisions remain hand-authored. Added CPU quote/forecast
examples for the same three regions and one earlier GPU issue in
`frontend/lib/preview.ts` solely to exercise filters and model freshness. None is
observed history or trained output. Backend mode still reads the existing API
responses with the backend's current scheduling slot; it adds no datasets on its
own. No backend files or schemas changed. Actual live-data freshness, trained model
quality/calibration, and scheduling remain the backend team's responsibilities.
No photos, invented testimonials, cloud execution or benchmark results were added.
