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
