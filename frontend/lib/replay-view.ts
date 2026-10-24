import type { Decision, Job, MarketSnapshot } from "./types";

// Frontend presentation types, not a proposed backend API contract.
export type ExecutionView = {
  jobId: string; taskName: string; status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  mode: "SIMULATED" | "LOCAL"; startedAt: string | null; completedAt: string | null;
  exitCode: number | null; failureReason: string | null; stdout: string[]; stderr: string[];
};
export type ReplayFrame = {
  slot: number; event: string; jobs: Job[]; decisions: Decision[];
  market: MarketSnapshot[]; execution: ExecutionView;
};
export type ReplayScenario = { id: string; name: string; description: string; frames: ReplayFrame[] };

export function nextFrame(index: number, count: number): number {
  return Math.min(index + 1, Math.max(0, count - 1));
}
