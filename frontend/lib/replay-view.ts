import type { Decision, Job, MarketSnapshot } from "./types";

// Frontend presentation types, not a proposed backend API contract.
export type ExecutionView = {
  jobId: string; taskName: string; status: "PENDING" | "STARTING" | "RUNNING" | "COMPLETED" | "FAILED";
  mode: "SIMULATED" | "LOCAL"; startedAt: string | null; completedAt: string | null;
  exitCode: number | null; failureReason: string | null; stdout: string[]; stderr: string[];
  monitorError?: string | null; stdoutTruncated?: boolean; stderrTruncated?: boolean; timeoutRequested?: boolean;
};
export type ReplayFrame = {
  slot: number; event: string; jobs: Job[]; decisions: Decision[];
  market: MarketSnapshot[]; execution: ExecutionView;
};
export type ReplayScenario = { id: string; name: string; description: string; frames: ReplayFrame[] };

export function nextFrame(index: number, count: number): number {
  return Math.min(index + 1, Math.max(0, count - 1));
}

export function replayCapacityAtSlot(market: MarketSnapshot[], nextSlot: number): MarketSnapshot[] {
  // Replay's clock points at the next unprocessed interval, not an observation.
  if (nextSlot <= 0) return [];
  return market.filter(row => row.slot === nextSlot - 1)
    .sort((a, b) => a.region.localeCompare(b.region) || a.resourceType.localeCompare(b.resourceType)
      || (a.gpuType ?? "").localeCompare(b.gpuType ?? ""));
}
