# Milestone 7: local execution and dispatch pause

Approved split: **7a** implements manual local Docker execution and monitoring;
**7b** adds persistent pause/resume and dispatch controls before autonomous real
execution. Milestone 7a is implemented and a genuine local run passed; see
BACKEND_EXECUTION.md. Backend Milestone 7b is implemented and verified; see
BACKEND_DISPATCH.md for controls, race semantics and frontend handoff. Frontend
integration remains Person 3's work. A benchmark manifest is optional.

## Backend — Person 2

- [x] Implement the predefined Docker task/image/command allowlist. Frontend
  users cannot submit shell commands.
- [x] Persist execution IDs, job/container associations, UTC start/completion,
  exit code, stdout/stderr, truncation and failure reason.
- [x] Make dispatch idempotent; repeated calls cannot launch a second container.
- [x] Integrate real monitor outcomes with job status, reservation release and
  replanning. A simulated region is not actual cloud execution.
- [x] Add persisted live-engine pause/resume state that survives restart.
- [x] Enforce pause for new automatic and manual execution starts at the final
  dispatch boundary. Already-running jobs continue and remain monitored.
- [x] Continue observing markets, refreshing forecasts and producing plans while
  paused; show planned actions separately from actual execution status.
- [x] On resume, replan using current observations/jobs/reservations before
  dispatching. Never blindly execute stale plans.
- [x] Expose pause/resume/status endpoints and test the gate, monitoring during
  pause, restart persistence and resumption. Historical replay keeps independent
  step/play controls.
- [x] Execute at least one genuine local Docker workload and capture its result.

## Frontend — Person 3

- [ ] Add clear Pause new starts / Resume controls and backend-confirmed status.
- [ ] Explain that running work continues; expose its status/logs while paused.
- [ ] Display dispatch pause distinctly from replay playback and paper mode.

## ML — Person 1

No pause-specific model changes are required. Forecasting continues through the
existing interface; model/provenance integration remains its own team handoff.

## Completion gate

Real autonomous dispatch must not be enabled until the pause gate and execution
allowlist work. These prerequisites are verified. Milestone 8 now provides opt-in
automatic LOCAL dispatch; resume alone does not enable that capability. No paid AWS provisioning
is authorized by this milestone. Local
execution is labeled LOCAL and is not proof of a cloud run or actual cloud spend.
