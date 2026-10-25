# Arbitr chat handoff — 25 October 2026

Latest frontend simplification: Replay & execution now has Demo replay and Local
execution tabs. Demo replay shows Workload → Decision → Outcome → Policy comparison
on one page. Settings, source receipts, capacity, detailed plans/history and shocks
are collapsed; play/restart remain visible. Live engine controls are collapsed and
explicitly separate; the replay view no longer shows the live market banner/clock.
Selected-example disclosure and simulated provenance remain visible. Only backend
decisions, outcomes and comparison totals are used. Earlier requests to hide
persistence and the pairwise savings paragraphs remain respected.

Browser check confirmed the narrative, advanced disclosure and preserved local
execution view. That view now contains a user-run COMPLETED local task, exit 0,
started 2026-10-25T06:35:50.274534Z, finished 06:35:50.814317Z, with SHA-256 stdout.
This supersedes earlier notes saying current local execution was still unverified;
the agent inspected the existing record, without launching another task. All 45
frontend tests passed. The final production build passed after retrying outside
the sandbox, which had denied a generated Next output-directory creation.

Latest UI change: at the user's request, persistence optimization is removed
from the frontend policy table, comparison paragraphs and replay policy selector.
The UI now presents FIFO, Cheapest now and ML; ML is the default inspected policy.
Persistence remains in backend replay and saved benchmarks for ablation validation.
Actual ML fallback provenance labels remain visible when relevant.

The user also requested removal of the text section below the policy table:
pairwise savings paragraphs and the accounting footer are removed. The table,
outcome counts, data provenance and actual ML/fallback labels remain.

Latest runtime update: following the user's report that the frontend still tied,
the backend was restarted on port 8000 with the selected-ml-demo-002 bundle and
LEGACY waiting. Replay was backed up to `.arbitr/replay-before-selected-demo.json`,
reset with seed 44 and completed through port 3000's frontend proxy. Verified:
14 completed and zero missed for every policy; ML $4.7819, other policies $4.8115.
Current localhost is therefore the selected demo, overriding earlier descriptions
below that say it was unchanged. Restore CAUTIOUS after the demo; its environment
setting affects live optimization too. Proxy evidence:
`.arbitr/selected-demo-proxy-metrics.json`. Backend logs: `.arbitr/backend-selected-demo*.log`.

Workspace: `C:\Users\trish\Downloads\oxhack-2026`, branch `main`.
Read `AGENTS.md` and inspect `git status --short` before editing. There is a large
uncommitted diff, including new result files and intentional preview deletions.
Preserve it. No commits or pushes were made in this conversation.

## Current position

The user wanted a working, understandable demo, genuine ML, valid historical
replay, fair saved benchmarks, and an explanation of ML underperformance.

- Fixed replay accounting losing the GPU model chosen for flexible jobs.
- Installed ML dependencies; fixed Windows LF/checksum issues without changing
  model weights; added `.gitattributes` protection.
- Fixed misleading ML labels: actual ML, persistence fallback and mixed use are
  distinguished. Model READY alone does not mean a replay used ML.
- Removed Design preview and mock frontend mode; the UI reads backend state.
- Added validated historical replay, warm-up, scenario catalog, fair benchmark
  runner, exact reproducibility checks and independent source/ledger audits.
- Added CAUTIOUS waiting to avoid speculative delays for tiny predicted savings.
  It affects scheduling preference, not actual billing or projected compute cost.
- Evaluated longer and mixed deadlines. More flexibility alone did not establish
  ML savings in the selected low-movement, single-choice price pools.
- Latest: prepared a **retrospectively selected genuine ML winning example**.
  See [SELECTED_ML_DEMO.md](SELECTED_ML_DEMO.md). It completes the same 14 jobs for
  $4.7819 vs $4.8115, saving $0.0296 / 0.615193%. It explicitly uses LEGACY waiting,
  not active CAUTIOUS. Fresh runs reproduced exactly. Localhost was not switched.

## Evidence and interpretation

| Suite | Baselines | ML |
| --- | --- | --- |
| Original 27-case fair benchmark | 444/468 jobs, $167.8166 | Legacy 411 jobs, $149.2914; fewer jobs means no overall savings claim |
| Paired waiting-policy evaluation | 444/468, $164.4093 | Legacy 408; cautious matches 444 and baseline cost |
| Latest flexible/mixed suite | 462/486, $184.6857 | Legacy 460, $187.7344; both cautious variants match baseline |

Latest experiment: 27 input cases × 3 configurations × 4 policies × 2 repeats =
648 strategy replays. All repeated states/metrics match and all three independent
audits passed. Genuine ML throughout. These are observed prices with simulated
jobs/capacity, not real cloud spend; evaluation dates were previously reused.

FIFO/cheapest/persistence tie because each job has only one eligible pool and
persistence gives no reason to wait. Cautious ML's predicted savings are below
its waiting preference. Legacy did wait, often for tiny gains, and created backlog.
Original suite had 350 idle pool-hours with feasible waiting work under legacy
versus zero for persistence. Cautious removes that harmful behavior but has not
demonstrated incremental ML savings.

Across all 486 latest submitted jobs, hindsight independent scheduling ignoring
capacity finds only $0.7264 (~0.36%) price-timing headroom. This is not an
executable portfolio plan and must not be compared directly to costs covering
only 462 completed jobs. No full benchmark results were hidden for the selected
winning demo. Do not turn that selected win into a general performance claim.

Detailed reports:

- [HISTORICAL_REPLAY.md](HISTORICAL_REPLAY.md)
- [FAIR_BENCHMARK.md](FAIR_BENCHMARK.md)
- [CAUTIOUS_WAITING.md](CAUTIOUS_WAITING.md)
- [FLEXIBLE_WORKLOAD_EXPERIMENT.md](FLEXIBLE_WORKLOAD_EXPERIMENT.md)
- [SELECTED_ML_DEMO.md](SELECTED_ML_DEMO.md)

## Runtime and data

Last configured frontend: http://127.0.0.1:3000, backend: http://127.0.0.1:8000.
Check health and port ownership before assuming they remain running. Preserve
`backend/state/engine.sqlite3`; live and replay states are independent.

Backend startup environment was `COMPUTE_ENABLE_ML=1`,
`COMPUTE_WAITING_POLICY=CAUTIOUS`, `COMPUTE_MARKET_SOURCE=json`,
`COMPUTE_MARKET_FILE=C:\Users\trish\Downloads\oxhack-2026\data\scenarios\demo.json`,
`COMPUTE_ALLOW_LOCAL_DISPATCH=0`. From `backend/`, run
`.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
Frontend uses `API_PROXY_TARGET=http://127.0.0.1:8000`; from `frontend/`, run
`node node_modules/next/dist/bin/next dev --webpack --hostname 127.0.0.1 --port 3000`.
The `./dev` launcher is for macOS/Linux; manual startup was used on Windows.
Logs are under `.arbitr/`. Background processes were launched hidden.

AWS credentials/CLI were not configured here. The live/PAPER source is explicitly
SIMULATED. Historical replay separately uses real imported prices with simulated
capacity. No paid resources were provisioned and no genuine local Docker task was
run in this session. Replay does not launch Docker. Current UI historical replay
was ten jobs per policy at $2.6348 under CAUTIOUS; batch suites are saved reports.

User supplied `data/processed/hourly-prices-hardware-v3-001.zip`, extracted to
the same-named directory. Dataset: 444,288 rows, 208 series, July 28–Oct 25, 2026;
hash `618ed38329ec8b4934c7fd40a0e77e61b3dcd9d3850b2df87299af5827903a36`.
Selected pools: T4/g4dn.xlarge/eu-north-1a and A10G/g5.xlarge/eu-north-1b,
Linux/UNIX. Model artifacts: `models/error-reduction-001/`, serving config:
`data/forecast-serving.json`. GPU model:
`lightgbm-price-l1-v1-gpu-734be7a557de`. Needs 168 prior consecutive hours plus
current observation; forecasts 1–6 hours. Old year-2000 scenarios correctly fall
back. Strict held-out model metrics being unavailable is intentional for the
packaged exploratory evaluation.

Dataset and full evidence under `data/processed/` are Git-ignored and need
separate transfer for a fresh clone. Compact design/results/audits under `data/`
are uncommitted. Full runs include fair-benchmark-001, waiting-policy-* and
flexible-workload-* folders; selected-ml-demo-002 is the newest demo evidence.
Never overwrite old outputs; use fresh directories.

## Verification and next steps

Previous engine/API run: 188 tests passed, followed by 12 focused tests after
hindsight-audit extensions. Earlier frontend tests/builds passed for UI changes;
latest work is backend/demo tooling. Selected-demo runner executed successfully
using the real model and two distinct replay batch sizes. Do not confuse these
checks with a complete browser/demo rehearsal or genuine Docker verification.

On Windows, expand frontend test files explicitly (`Get-ChildItem tests -Filter
'*.test.mjs'`) and pass the paths to `node --test`; the package script wildcard
was treated literally. Use `npm.cmd run build` for types/compilation. Backend
TestClient needed the approved execution environment and fresh state basetemp;
the sandbox previously hung. Existing Windows launcher test fails on missing
`os.killpg`; other launcher tests passed. Preserve LF-normalized checksummed
artifacts; some show modified status with no Git content diff.

User understands completion windows include both waiting and execution. The MVP
uses whole-hour slots: a 1.5-hour estimate needs two slots; replay does not model
early finishes. We recommended retaining this for the demo and separating finer
execution/accounting from hourly forecasts in a future version.

Next credible work: rehearse the explicitly selected demo; verify local Docker
separately if needed; find actual customer workload traces and verified
interchangeable pools to test routing value. Do not fabricate extra pools,
future-aware forecasts, or keep tuning until a benchmark appears to win.
Current active cautious policy should not silently change for a selected example.
