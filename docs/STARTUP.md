# Reliable local startup

From the repository root on macOS/Linux:

```sh
./dev
```

Wait for `Arbitr ready`, open http://127.0.0.1:3000 on the same computer, select
**Backend data**, then **Market**. Keep the terminal open. Ctrl+C stops both servers
and their child processes. If either server exits, the launcher stops the other
and reports its log path. It never kills an unrelated existing server.

## First-time dependencies

Install Python 3.11+ (3.11/3.12 recommended), Node.js 20.9+ with npm, and AWS CLI v2.
Browser login requires AWS CLI 2.32+. Then run:

```sh
./dev --setup
```

This creates `backend/.venv` if absent, installs backend dev/AWS dependencies plus
`botocore[crt]`, installs the frontend lockfile with `npm ci`, then launches both
servers. It requires internet access. It does not install Docker. Add `--ml` to
install/enable the selected ML provider (`./dev --setup --ml` on first use, then
`./dev --ml`). On macOS, LightGBM additionally needs OpenMP: `brew install libomp`.
See the [official installation guide](https://lightgbm.readthedocs.io/en/stable/Installation-Guide.html#macos).
Normal startup does not install packages. Existing `backend/.venv` takes precedence
over the Python environment used to invoke the launcher; otherwise it uses that
Python environment. No `.env` file is required or modified.

## AWS login

The defaults are profile `arbitr`, region `eu-north-1`, and GPU instance types
`g4dn.xlarge,g5.xlarge`. Login with the existing project:

```sh
./dev --login
```

Complete browser authorization, selecting your project. Login then continues into
normal startup. Combine with `--setup` on a fresh machine if needed. Authentication
failures do not silently launch example data. Credentials stay in the AWS CLI's
local storage; the launcher never copies them into frontend configuration.

Check prerequisites and credentials without starting or stopping servers:

```sh
./dev --check
```

An explicitly configured alternative can use `--profile NAME --region REGION`.
The current project's selected region is Stockholm; this option does not grant
access to other regions. Verify access before changing it.

## What startup checks

- Required commands, Node version, Python version and backend/frontend dependencies.
- `aws sts get-caller-identity` with the chosen profile; old shell access keys are
  removed from child environments so they cannot override it.
- Ports 8000 and 3000 are free before spawning either server.
- Backend health, then actual AWS capabilities and observed quotes through the
  frontend proxy. Readiness requires READY responses for the configured region.
- Both owned server processes remain running after readiness.

The launcher sets live AWS mode, a two-second backend polling interval and the
local frontend proxy. It clears inherited JSON-source and UTC-origin overrides.
Automatic local Docker dispatch is disabled. Existing jobs/database are retained;
an explicit `COMPUTE_DB_PATH` remains supported. The launcher does not change the
persisted forecast mode. `--ml` validates the selected artifacts, enables the
provider for engine/replay and uses fixed instance/AZ live GPU pools. Plain `./dev`
disables that provider and retains the regional price index. Select ML in the UI
after enabling it. Short/mismatched histories produce labeled persistence
fallbacks; previously selecting unavailable ML can still produce an engine
error which must be resolved in the UI.

Readiness confirms live pricing, not GPU inventory or cloud allocation. Unknown
AWS capacity remains unknown. The UI continues to expose missing ML and execution
capabilities, and starts in isolated Design preview until Backend data is selected.

## Troubleshooting

| Message or symptom | Action |
| --- | --- |
| Missing dependencies | Run `./dev --setup` using supported Python and Node versions. |
| AWS authentication failed | Run `./dev --login`; check internet/profile configuration if it persists. |
| Browser does not open | Use `aws login --remote --region eu-north-1 --profile arbitr`, complete authorization, then retry `./dev`. |
| Port already in use | Stop the old server from its terminal. The error supplies an `lsof` command to identify the listener. |
| Live readiness timeout | Inspect `.arbitr/backend.log`, `/api/capabilities` and `/api/market/aws/spot`; check permissions, connection and supported regional offerings. |
| Missing `libomp.dylib` | Install the macOS OpenMP runtime with `brew install libomp`, then retry `./dev --ml`. |
| `MissingDependencyException` | The active backend environment needs `botocore[crt]`; rerun `./dev --setup`. |
| Frontend stops or build fails | Inspect `.arbitr/frontend.log`; the launcher also stops its backend. |
| Runtime credentials expire after startup | The UI shows API/source errors. Stop with Ctrl+C, then run `./dev --login`. |

Logs live in ignored `.arbitr/backend.log` and `.arbitr/frontend.log` and are
replaced on each launch. The launcher does not continuously renew browser sessions
or automatically restart crashed servers. Use the reported error to fix the cause.

Windows manual commands remain documented in [AWS_MARKET.md](AWS_MARKET.md).

## Verification

Recorded on 25 October 2026: actual live launch reached readiness, Ctrl+C released
both ports, `./dev --setup --check` installed a fresh backend environment and
frontend lockfile successfully, and repeat startup reached live readiness again.
Five startup regressions passed. Backend tests in the new environment: 174 passed,
1 skipped (optional Docker SDK absent), with an existing Starlette/httpx warning.
The `--login` shortcut was not forced during this run because credentials remained
valid; it uses the AWS CLI browser flow verified during earlier project setup.


Startup regressions:

```sh
python3 -m unittest discover -s scripts -p test_dev.py -v
```

The suite checks real occupied-port handling, child-failure cleanup, authentication
recovery messages, profile isolation and rejection of simulated/mismatched readiness.
Live startup, Ctrl+C cleanup and repeat startup require the local network and an
authenticated AWS profile; they are separate from these tests.
