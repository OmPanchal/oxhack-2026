import type { Decision, Job } from "./types";

// Geometry for supplied plans only. No scheduling or feasibility decisions.
export function timelineWindow(job: Job, decision: Decision | undefined, currentSlot: number, domain?: { origin: number; limit: number }) {
  const start = decision?.plannedStartSlot, end = decision?.plannedEndSlot;
  const supplied = decision?.jobId === job.id && decision.decidedAtSlot <= currentSlot
    && decision.action !== "INFEASIBLE" && start != null && end != null
    && Number.isFinite(start) && Number.isFinite(end) && start >= job.arrivalSlot && end > start;
  const origin = Math.min(currentSlot, job.arrivalSlot, job.deadlineSlot, supplied ? start : currentSlot, domain?.origin ?? Infinity);
  const limit = Math.max(origin + 1, currentSlot, job.deadlineSlot, supplied ? end : currentSlot, domain?.limit ?? -Infinity);
  const position = (slot: number) => (slot - origin) / (limit - origin) * 100;
  return { origin, limit, deadline: position(job.deadlineSlot), now: position(currentSlot),
    plan: supplied ? { left: position(start), width: position(end) - position(start), start, end,
      waitLeft: position(job.arrivalSlot), waitWidth: position(start) - position(job.arrivalSlot) } : null };
}

export function sharedTimeline(entries: { job: Job; decision?: Decision }[], currentSlot: number) {
  const windows = entries.map(({ job, decision }) => timelineWindow(job, decision, currentSlot));
  const origin = Math.min(currentSlot, ...windows.map(window => window.origin));
  const limit = Math.max(origin + 1, currentSlot, ...windows.map(window => window.limit));
  const step = Math.max(1, Math.ceil((limit - origin) / 6));
  const ticks = Array.from({ length: Math.floor((limit - origin) / step) + 1 }, (_, i) => origin + i * step);
  // Avoid crowding the last tick while retaining the exact end of the range.
  if (ticks[ticks.length - 1] !== limit) {
    if (limit - ticks[ticks.length - 1] < step / 2) ticks.pop();
    ticks.push(limit);
  }
  return { origin, limit, ticks, rows: entries.map(({ job, decision }) => ({
    job, window: timelineWindow(job, decision, currentSlot, { origin, limit }),
  })) };
}

// Interval packing is visual layout only; touching half-open windows share a lane.
export function packedTimeline(entries: { job: Job; decision?: Decision }[], currentSlot: number) {
  const shared = sharedTimeline(entries, currentSlot);
  const planned = shared.rows.filter(row => row.window.plan !== null).sort((a, b) =>
    a.window.plan!.start - b.window.plan!.start || a.window.plan!.end - b.window.plan!.end || a.job.id.localeCompare(b.job.id));
  const lanes: typeof planned[] = [];
  for (const row of planned) {
    const lane = lanes.find(items => items[items.length - 1].window.plan!.end <= row.window.plan!.start);
    if (lane) lane.push(row);
    else lanes.push([row]);
  }
  const deadlines = new Map<number, Job[]>();
  for (const { job } of entries) deadlines.set(job.deadlineSlot, [...(deadlines.get(job.deadlineSlot) ?? []), job]);
  return { ...shared, lanes, unplanned: shared.rows.filter(row => row.window.plan === null),
    deadlines: [...deadlines].sort(([a], [b]) => a - b).map(([slot, jobs]) => ({ slot, jobs: jobs.sort((a, b) => a.id.localeCompare(b.id)) })) };
}
