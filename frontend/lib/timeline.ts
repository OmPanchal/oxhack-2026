import type { Decision, Job } from "./types";

// Geometry for supplied plans only. No scheduling or feasibility decisions.
export function timelineWindow(job: Job, decision: Decision | undefined, currentSlot: number) {
  const start = decision?.plannedStartSlot, end = decision?.plannedEndSlot;
  const supplied = decision?.jobId === job.id && decision.decidedAtSlot <= currentSlot
    && decision.action !== "INFEASIBLE" && start != null && end != null
    && Number.isFinite(start) && Number.isFinite(end) && start >= job.arrivalSlot && end > start;
  const origin = Math.min(currentSlot, job.arrivalSlot, job.deadlineSlot, supplied ? start : currentSlot);
  const limit = Math.max(origin + 1, currentSlot, job.deadlineSlot, supplied ? end : currentSlot);
  const position = (slot: number) => (slot - origin) / (limit - origin) * 100;
  return { origin, limit, deadline: position(job.deadlineSlot), now: position(currentSlot),
    plan: supplied ? { left: position(start), width: position(end) - position(start), start, end,
      waitLeft: position(job.arrivalSlot), waitWidth: position(start) - position(job.arrivalSlot) } : null };
}
