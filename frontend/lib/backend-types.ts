import type { Decision, ExecutionMode, Forecast, Job, JobCreate, ResourceType, Strategy } from "./types";

export type ModelStatus = {
  status: "READY" | "UNAVAILABLE"; reason?: string; engineEnabled: boolean; engineForecastMode: "NAIVE" | "ML";
  modelFamily?: string; lookbackHours?: number; originUtc?: string; validationStatus?: string;
  marketReadErrors?: { region: string; instanceType: string; resourceType: string; code: string }[];
  history?: { status: "READY" | "WARMING" | "PARTIAL"; lookbackHours: number;
    pools: { region: string; instanceType: string; availabilityZone: string; gpuType: string | null; resourceType?: "CPU" | "GPU";
      status: "READY" | "PARTIAL"; requiredHours: number; availableHours: number; errorCode: string | null }[] } | null;
};

export type EngineState = {
  acquisitionMode?: 'DISABLED' | 'SIMULATED'; simulationSlotSeconds?: number | null;
  currentSlot: number; wallClockSlot?: number; originUtc: string; forecastMode: "NAIVE" | "ML"; executionMode: ExecutionMode;
  lastTickAtUtc: string | null; lastError: { code: string; message: string } | null;
  autoTickEnabled: boolean; mlConfigured: boolean; dataKind: "OBSERVED" | "SIMULATED" | "MIXED" | null;
  dispatch: { paused: boolean; revision: number; changedAtUtc: string | null; lastResumedAtUtc: string | null;
    lastResumeError: { code: string; message: string } | null; automaticLocalDispatchEnabled: boolean };
};
export type Acquisition = {
  id: string; jobId: string; region: string; resourceType: 'CPU' | 'GPU'; gpuType: string | null;
  resourceUnits: number; requestedAtSlot: number; endSlot: number;
  status: 'ACQUIRED' | 'REJECTED' | 'COMPLETED'; executionMode: 'SIMULATED'; reason: string; stages: string[];
};
export type DecisionDetail = {
  decisionId: number; jobId: string; decidedAtSlot: number; forecastMode: "NAIVE" | "ML" | null;
  executionMode: ExecutionMode; deadlineSlackSlots: number | null; forecastsUsed: Forecast[];
  costBreakdown: Record<string, number> | null; availabilityProbability: number | null;
  interruptionProbability: number | null; dataKind: "OBSERVED" | "SIMULATED" | "MIXED" | null;
  marketSources: string[]; pricingAssumption: string | null; dispatchBlocked: boolean; dispatchBlockReason: string | null;
};
export type MarketCapabilities = { provider: "AWS" | "CONFIGURED_MARKET" | "NONE";
  status: "READY" | "PARTIAL" | "UNAVAILABLE" | "NOT_CONFIGURED"; fetchedAtUtc: string | null;
  configuredRegions: string[]; allowedGpuTypes: string[]; allowedRegions: string[];
  capacityStatus: "UNKNOWN" | "SOURCE_DEFINED"; errors: { region: string; code: string; message: string }[] };
export type LocalTask = { id: string; name: string; image: string; resourceType: "CPU";
  resourceUnits: number; region: "local"; timeoutSeconds: number };
export type TaskCatalog = { tasks: LocalTask[]; automaticDispatchEnabled: boolean };
export type LocalExecution = {
  id: string; jobId: string; taskId: string; executionMode: "LOCAL"; region: "local";
  status: "STARTING" | "RUNNING" | "COMPLETED" | "FAILED"; containerName: string;
  containerId: string | null; imageId: string; requestedAtUtc: string; startedAtUtc: string | null;
  dockerEndpoint?: string | null;
  completedAtUtc: string | null; exitCode: number | null; stdout: string; stderr: string;
  stdoutTruncated: boolean; stderrTruncated: boolean; failureReason: string | null;
  lastMonitorError: string | null; timeoutRequested: boolean;
};
export type ReplayCounters = {
  computeSpendUsd: number; startupCostUsd: number; transferCostUsd: number; carbonCostUsd: number;
  recoveryCostUsd: number; totalSpendUsd: number; completedJobs: number; failedJobs: number;
  infeasibleJobs: number; pendingJobs: number; runningJobs: number; unfinishedJobs: number; missedDeadlines: number;
};
export type ReplayStrategy = { strategy: Strategy; status: "ACTIVE" | "UNAVAILABLE" | "ERROR";
  error: string | null; jobs: Job[]; decisions: Decision[]; forecasts: Forecast[]; metrics: ReplayCounters;
  outcomes: { jobId: string; slot: number; status: "COMPLETED" | "FAILED" | "INFEASIBLE"; reason: string }[];
  missedDeadlineIds: string[]; modelVersionsUsed?: string[] };
export type ReplayShock = { kind: "PRICE_SPIKE" | "CAPACITY_SHORTAGE" | "INTERRUPTION" | "DEADLINE_PRESSURE" | "JOB_ARRIVAL";
  slot: number; region?: string | null; magnitude: number; dataKind: "SIMULATED"; durationSlots?: number;
  resourceType?: ResourceType | null; gpuType?: string | null; jobId?: string | null; job?: JobCreate | null; eventId: string };
export type ReplayMetrics = { scope: "REPLAY"; status: "NOT_INITIALIZED" | "IN_PROGRESS" | "COMPLETED";
  executionMode: "SIMULATED"; costBasis: "SIMULATED_REALIZED"; dataKind: "SIMULATED";
  currency: "USD"; scenarioId: string | null; asOfSlot: number; endSlot: number | null;
  strategies: { strategy: Strategy; status: "ACTIVE" | "UNAVAILABLE" | "ERROR"; error: string | null;
    modelVersions: string[]; totals: ReplayCounters; completedJobIds: string[]; failedJobIds: string[];
    infeasibleJobIds: string[]; unfinishedJobIds: string[]; missedDeadlineJobIds: string[] }[];
  comparisons: { strategy: Strategy; baseline: Strategy; comparable: boolean; reasonCode: string; explanation: string;
    baselineSpendUsd: number | null; strategySpendUsd: number | null; costDifferenceUsd: number | null;
    savingsUsd: number | null; savingsPercent: number | null; sameCompletedJobs: boolean;
    sameOutcomes: boolean; allJobsCompleted: boolean }[] };
export type LiveMetrics = { scope: "LIVE"; costBasis: "PROJECTED"; currency: "USD"; asOfSlot: number;
  activeExecutionMode: ExecutionMode; jobCounts: { pendingJobs: number; runningJobs: number; completedJobs: number;
    failedJobs: number; infeasibleJobs: number; unfinishedJobs: number; missedDeadlines: number };
  knownProjectedCostUsd: number; projectedPortfolioCostUsd: number | null; unpricedOutstandingJobIds: string[];
  realizedSpendUsd: null; realizedSavingsUsd: null };
export type ModelMetrics = { status: "UNAVAILABLE" | "EVALUATED"; reason: string | null;
  evaluation: { modelVersion: string; dataSource: string; sampleCount: number; mae: number; rmse: number;
    persistenceMae: number; persistenceRmse: number; evaluatedAtUtc: string } | null;
  maeImprovement: number | null; rmseImprovement: number | null;
  maeImprovementPercent: number | null; rmseImprovementPercent: number | null };
