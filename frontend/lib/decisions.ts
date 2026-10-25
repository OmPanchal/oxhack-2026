import type { Decision } from "./types";

export function decisionSummary(decision?: Decision): { label: string; detail: string } {
  if (!decision) return { label: 'Awaiting plan', detail: '' };
  if (decision.reasonCode === 'LOCAL_EXECUTION_REQUIRED')
    return {label: 'READY FOR LOCAL', detail: 'Start with Run local task · Docker Desktop required'};
  const blockers: Record<string, string> = {
    LOCAL_EXECUTION_REQUIRED: 'Start this task with Run local task (real Docker)',
    CAPACITY_UNKNOWN: 'Available capacity is unverified',
    CAPACITY_UNAVAILABLE: 'Insufficient available capacity',
    NO_COMPATIBLE_MARKET_DATA: 'No matching region/hardware prices',
    FORECAST_COVERAGE_MISSING: 'Forecast coverage is incomplete',
    PORTFOLIO_CAPACITY_CONFLICT: 'Capacity is reserved by other workloads',
    CARBON_DATA_UNAVAILABLE: 'Required carbon data is unavailable',
    BUDGET_EXCEEDED: 'No affordable execution window',
  };
  if (decision.action === 'WAIT' && decision.plannedStartSlot === null && blockers[decision.reasonCode])
    return { label: 'BLOCKED', detail: blockers[decision.reasonCode] };
  return { label: decision.action, detail: decision.action === 'WAIT' ? `Planned start: slot ${decision.plannedStartSlot ?? 'unknown'}` : '' };
}

// Presentation only: select an issued decision, never calculate an allocation.
export function latestDecision(decisions: Decision[], jobId: string | null, currentSlot: number): Decision | undefined {
  return decisions.filter(row => row.jobId === jobId && row.decidedAtSlot <= currentSlot)
    .reduce<Decision | undefined>((latest, row) => !latest || row.decidedAtSlot >= latest.decidedAtSlot ? row : latest, undefined);
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


// The current Decision response has no ID. Match evidence only when the two
// ordered collections form a complete, consistent one-to-one snapshot.
export function linkedDecisionDetail(decisions: Decision[], details: import("./backend-types").DecisionDetail[], decision?: Decision) {
  if (!decision || decisions.length !== details.length) return undefined;
  const ordered = [...details].sort((a, b) => a.decisionId - b.decisionId);
  if (!decisions.every((row, index) => row.jobId === ordered[index].jobId
    && row.decidedAtSlot === ordered[index].decidedAtSlot && row.executionMode === ordered[index].executionMode)) return undefined;
  const index = decisions.indexOf(decision);
  return index < 0 ? undefined : ordered[index];
}
