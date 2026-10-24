// Person 3 owns this mirror of backend/app/api/schemas.py. Coordinate contract edits.
export type ResourceType = "CPU" | "GPU";
export type JobStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "INFEASIBLE";
export type ExecutionMode = "SIMULATED" | "PAPER" | "LOCAL";
export type Strategy = "FIFO" | "CHEAPEST_NOW" | "OPTIMIZER_WITH_NAIVE_FORECAST" | "OPTIMIZER_WITH_ML";
export type Job = {
  id: string; name: string; arrivalSlot: number; durationSlots: number;
  deadlineSlot: number; resourceType: ResourceType; resourceUnits: number;
  gpuType?: string | null; allowedGpuTypes?: string[]; allowedRegions: string[]; maxBudgetUsd: number | null;
  priority: number; status: JobStatus; dockerTaskId: string | null;
};
export type JobCreate = Omit<Job, "status">;
export type MarketSnapshot = {
  slot: number; region: string; resourceType: ResourceType; gpuType?: string | null;
  priceUsdPerUnitHour: number; availableUnits: number; carbonKgPerUnitHour: number | null;
  source: string; dataKind: "OBSERVED" | "FORECAST" | "SIMULATED";
};
export type Forecast = {
  generatedAtSlot: number; targetSlot: number; region: string; resourceType: ResourceType;
  gpuType?: string | null; predictedPriceUsdPerUnitHour: number;
  priceLowerBound: number | null; priceUpperBound: number | null;
  availabilityProbability: number | null; interruptionProbability: number | null; modelVersion: string;
};
export type Decision = {
  jobId: string; decidedAtSlot: number; action: "WAIT" | "RUN" | "ROUTE" | "FALLBACK" | "INFEASIBLE";
  region: string | null; plannedStartSlot: number | null; plannedEndSlot: number | null;
  projectedCostUsd: number | null; reasonCode: string; explanation: string; executionMode: ExecutionMode;
};
export type OptimizeRequest = { currentSlot: number; forecastMode?: "NAIVE" | "ML"; executionMode?: ExecutionMode };
export type ReplayResetRequest = { seed?: number; scenarioId?: string };
export type ReplayStepRequest = { slots?: number };
export type ShockRequest = {
  kind: "PRICE_SPIKE" | "CAPACITY_SHORTAGE" | "INTERRUPTION" | "DEADLINE_PRESSURE" | "JOB_ARRIVAL";
  slot: number; region?: string | null; magnitude?: number; dataKind?: "SIMULATED";
};
export type ReplayState = {
  status: "NOT_IMPLEMENTED" | "READY" | "RUNNING" | "COMPLETED";
  currentSlot: number; seed: number; strategies: Strategy[];
};
export type Health = { status: "ok"; stage: "SCAFFOLD" };
export type TerminalData = { jobs: Job[]; market: MarketSnapshot[]; forecasts: Forecast[]; decisions: Decision[]; replay: ReplayState };
