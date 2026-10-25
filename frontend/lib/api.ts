import { mockData } from "./mock";
import type { Decision, Forecast, Health, Job, JobCreate, MarketSnapshot, OptimizeRequest,
  ReplayResetRequest, ReplayState, ReplayStepRequest, ShockRequest, TerminalData } from "./types";
import type { DecisionDetail, EngineState, LocalExecution, MarketCapabilities, TaskCatalog,
  ReplayMetrics, LiveMetrics, ModelMetrics, ModelStatus, ReplayShock } from "./backend-types";

export const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
export class ApiError extends Error {
  constructor(public status: number, public code: string | null, message: string) { super(message); this.name = "ApiError"; }
}
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${baseUrl}/api${path}`, {
    method: body === undefined ? "GET" : "POST", signal: AbortSignal.timeout(15000),
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store",
  });
  if (!response.ok) {
    const raw = await response.text();
    let detail: unknown;
    try { detail = JSON.parse(raw).detail; } catch { detail = raw; }
    const error = detail && typeof detail === "object" && !Array.isArray(detail) ? detail as { code?: string; message?: string } : null;
    const message = error?.message ?? (typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(item => `${item.loc?.join(".") ?? "Request"}: ${item.msg}`).join("; ") : raw);
    throw new ApiError(response.status, error?.code ?? null, `${path}: ${message || `HTTP ${response.status}`}`);
  }
  return response.json() as Promise<T>;
}
export const api = {
  health: () => request<Health>("/health"), jobs: () => request<Job[]>("/jobs"),
  createJob: (job: JobCreate) => request<Job>("/jobs", job),
  market: () => request<MarketSnapshot[]>("/market"), forecasts: () => request<Forecast[]>("/forecasts"),
  optimize: (input: OptimizeRequest) => request<Decision[]>("/optimize", input),
  decisions: () => request<Decision[]>("/decisions"), decisionDetails: () => request<DecisionDetail[]>("/decisions/details"),
  engineState: () => request<EngineState>("/engine/state"),
  pause: () => request<EngineState>("/engine/pause", {}), resume: () => request<EngineState>("/engine/resume", {}),
  capabilities: () => request<MarketCapabilities>("/capabilities"),
  replayState: () => request<ReplayState>("/replay/state"),
  resetReplay: (input: ReplayResetRequest = {}) => request<ReplayState>("/replay/reset", input),
  stepReplay: (input: ReplayStepRequest = {}) => request<ReplayState>("/replay/step", input),
  shock: (input: ShockRequest) => request<ReplayShock>("/replay/shock", input),
  metrics: () => request<ReplayMetrics>("/metrics?scope=REPLAY"),
  liveMetrics: () => request<LiveMetrics>("/metrics?scope=LIVE"), modelMetrics: () => request<ModelMetrics>("/models/metrics"),
  modelStatus: () => request<ModelStatus>("/models/status"),
  taskCatalog: () => request<TaskCatalog>("/execution/tasks"), executions: () => request<LocalExecution[]>("/executions"),
  execute: (jobId: string) => request<LocalExecution>(`/execute/${encodeURIComponent(jobId)}`, {}),
};

// Live portfolio time and replay time are independent. Core state must succeed;
// auxiliary failures remain visible without hiding a successfully loaded portfolio.
export async function loadBackendTerminal(): Promise<TerminalData> {
  const [engine, jobs] = await Promise.all([api.engineState(), api.jobs()]);
  const errors: string[] = [];
  async function optional<T>(label: string, read: () => Promise<T>, fallback: T): Promise<T> {
    try { return await read(); } catch (error) { errors.push(`${label}: ${error instanceof Error ? error.message : String(error)}`); return fallback; }
  }
  const [market, forecasts, decisions, replay, capabilities, decisionDetails, taskCatalog, executions, replayMetrics, liveMetrics, modelMetrics, modelStatus] = await Promise.all([
    optional("Market", api.market, []), optional("Forecasts", api.forecasts, []), optional("Decisions", api.decisions, []),
    optional<ReplayState>("Replay", api.replayState, { status: "NOT_IMPLEMENTED", currentSlot: 0, seed: 42, strategies: [] }),
    optional("Capabilities", api.capabilities, undefined), optional("Decision details", api.decisionDetails, []),
    optional("Task catalog", api.taskCatalog, undefined), optional("Executions", api.executions, []),
    optional("Replay metrics", api.metrics, undefined), optional("Portfolio metrics", api.liveMetrics, undefined), optional("Model metrics", api.modelMetrics, undefined),
    optional("Model status", api.modelStatus, undefined),
  ]);
  return { engine, jobs, market, forecasts, decisions, replay, capabilities, decisionDetails, taskCatalog, executions, replayMetrics, liveMetrics, modelMetrics, modelStatus, errors };
}
export async function loadTerminal(): Promise<TerminalData> {
  return useMocks ? structuredClone(mockData) : loadBackendTerminal();
}
