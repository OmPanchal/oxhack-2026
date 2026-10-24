import type { Decision } from "./types";

// Presentation only: select an issued decision, never calculate an allocation.
export function latestDecision(decisions: Decision[], jobId: string | null, currentSlot: number): Decision | undefined {
  return decisions.filter(row => row.jobId === jobId && row.decidedAtSlot <= currentSlot)
    .reduce<Decision | undefined>((latest, row) => !latest || row.decidedAtSlot > latest.decidedAtSlot ? row : latest, undefined);
}

export function slotLabel(slot: number, currentSlot: number): string {
  const delta = slot - currentSlot;
  return `Slot ${slot} · ${delta === 0 ? "now" : delta > 0 ? `in ${delta}h` : `${Math.abs(delta)}h ago`}`;
}

export function deadlineBuffer(deadlineSlot: number, endSlot: number | null): string {
  if (endSlot === null) return "Unavailable";
  const hours = deadlineSlot - endSlot;
  return hours === 0 ? "Ends at deadline" : hours > 0 ? `${hours}h before deadline` : `${Math.abs(hours)}h after deadline`;
}
