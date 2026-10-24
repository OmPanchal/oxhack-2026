import { mockData } from "./mock";
import type {
  Decision, Forecast, Health, Job, JobCreate, MarketSnapshot, OptimizeRequest,
  ReplayResetRequest, ReplayState, ReplayStepRequest, ShockRequest, TerminalData,
} from "./types";

export const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${baseUrl}/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store",
  });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status} — ${await response.text()}`);
  return response.json() as Promise<T>;
}
// Mutations always call FastAPI. Mock mode only supplies read-only terminal fixtures.
export const api = {
  health: () => request<Health>("/health"),
  jobs: () => request<Job[]>("/jobs"),
  createJob: (job: JobCreate) => request<Job>("/jobs", job),
  market: () => request<MarketSnapshot[]>("/market"),
  forecasts: () => request<Forecast[]>("/forecasts"),
  optimize: (input: OptimizeRequest) => request<Decision[]>("/optimize", input),
  decisions: () => request<Decision[]>("/decisions"),
  replayState: () => request<ReplayState>("/replay/state"),
  resetReplay: (input: ReplayResetRequest = {}) => request<unknown>("/replay/reset", input),
  stepReplay: (input: ReplayStepRequest = {}) => request<unknown>("/replay/step", input),
  shock: (input: ShockRequest) => request<unknown>("/replay/shock", input),
  metrics: () => request<unknown>("/metrics"),
  modelMetrics: () => request<unknown>("/models/metrics"),
  execute: (jobId: string) => request<unknown>(`/execute/${encodeURIComponent(jobId)}`, {}),
};
export async function loadTerminal(): Promise<TerminalData> {
  if (useMocks) return structuredClone(mockData);
  const [jobs, market, forecasts, decisions, replay] = await Promise.all([
    api.jobs(), api.market(), api.forecasts(), api.decisions(), api.replayState(),
  ]);
  return { jobs, market, forecasts, decisions, replay };
}
