import type { Job, JobCreate } from "./types";

export function formatTimeLeft(deadlineSlot: number, currentSlot: number): string {
  const hours = deadlineSlot - currentSlot;
  if (hours === 0) return "Due now";
  return hours > 0 ? `${hours}h left` : `${Math.abs(hours)}h past deadline`;
}

export type JobDraft = {
  name: string; resourceType: "CPU" | "GPU"; resourceUnits: string;
  gpuTypes: string[]; durationHours: string; completeWithinHours: string;
  regions: string[]; budget: string; priority: string;
};
export type DraftErrors = Partial<Record<keyof JobDraft | "clock", string>>;

export function prepareJob(draft: JobDraft, currentSlot: number, id: string): { payload: JobCreate | null; errors: DraftErrors } {
  const errors: DraftErrors = {};
  if (!Number.isSafeInteger(currentSlot) || currentSlot < 0) errors.clock = "The current scheduling slot is unavailable. Refresh and try again.";
  const units = Number(draft.resourceUnits);
  const hours = Number(draft.durationHours);
  const budget = draft.budget.trim() === "" ? null : Number(draft.budget);
  const priority = Number(draft.priority);
  const regions = [...new Set(draft.regions.map(region => region.trim()).filter(Boolean))];
  const gpuTypes = [...new Set(draft.gpuTypes.map(model => model.trim()).filter(Boolean))];
  if (!draft.name.trim()) errors.name = "Enter a job name.";
  if (!Number.isSafeInteger(units) || units < 1) errors.resourceUnits = "Use a positive whole number of resource units.";
  if (!Number.isSafeInteger(hours) || hours < 1) errors.durationHours = "Use a positive whole number of hours.";
  if (draft.resourceType === "GPU" && !gpuTypes.length) errors.gpuTypes = "Select at least one acceptable GPU model.";
  if (!regions.length) errors.regions = "Choose at least one allowed region.";
  if (budget !== null && (!Number.isFinite(budget) || budget < 0)) errors.budget = "Enter a nonnegative USD budget or leave it empty.";
  if (!Number.isSafeInteger(priority) || priority < 0) errors.priority = "Choose a valid priority.";
  const window = Number(draft.completeWithinHours);
  const deadlineSlot = currentSlot + window;
  if (!Number.isSafeInteger(window) || window < 1 || !Number.isSafeInteger(deadlineSlot)) {
    errors.completeWithinHours = "Use a positive whole number of hours.";
  } else if (!errors.durationHours && hours > window) {
    errors.completeWithinHours = "The completion window must be at least as long as the job duration.";
  }
  if (Object.keys(errors).length) return { payload: null, errors };
  return { errors, payload: {
    id, name: draft.name.trim(), resourceType: draft.resourceType, resourceUnits: units,
    gpuType: draft.resourceType === "GPU" && gpuTypes.length === 1 ? gpuTypes[0] : null,
    allowedGpuTypes: draft.resourceType === "GPU" ? gpuTypes : [],
    durationSlots: hours, arrivalSlot: currentSlot, deadlineSlot, allowedRegions: regions,
    maxBudgetUsd: budget, priority, dockerTaskId: null,
  } };
}

export function deadlineAttention(job: Job, currentSlot: number): string | null {
  if (job.status === "FAILED" || job.status === "INFEASIBLE") return job.status === "FAILED" ? "Execution failed" : "Infeasible";
  if (job.status === "COMPLETED") return null;
  if (job.deadlineSlot <= currentSlot) return "Deadline reached";
  if (job.status === "PENDING" && job.deadlineSlot - currentSlot - job.durationSlots <= 1) return "Deadline pressure";
  return null;
}

export type JobFilters = { query: string; resource: string; status: string; sort: string };
export function filterJobs(jobs: Job[], filters: JobFilters): Job[] {
  const query = filters.query.trim().toLowerCase();
  return jobs.filter(job => (filters.resource === "ALL" || job.resourceType === filters.resource)
    && (filters.status === "ALL" || job.status === filters.status)
    && [job.id, job.name, job.gpuType ?? "", ...(job.allowedGpuTypes ?? []), ...job.allowedRegions].join(" ").toLowerCase().includes(query))
    .sort((a, b) => {
      const primary = filters.sort === "priority" ? b.priority - a.priority : filters.sort === "name" ? a.name.localeCompare(b.name) : a.deadlineSlot - b.deadlineSlot;
      return primary || a.id.localeCompare(b.id);
    });
}

export function jobHardware(job: Job): string {
  return job.resourceType === "CPU" ? "CPU" : job.allowedGpuTypes?.length ? job.allowedGpuTypes.join(" / ") : job.gpuType ?? "GPU";
}

export function rebaseJob(payload: JobCreate, currentSlot: number): JobCreate {
  const window = payload.deadlineSlot - payload.arrivalSlot;
  const deadlineSlot = currentSlot + window;
  if (!Number.isSafeInteger(currentSlot) || currentSlot < 0 || !Number.isSafeInteger(window) || window < payload.durationSlots || !Number.isSafeInteger(deadlineSlot)) {
    throw new Error("The scheduling clock is unavailable. Refresh and try again.");
  }
  return { ...payload, arrivalSlot: currentSlot, deadlineSlot };
}
