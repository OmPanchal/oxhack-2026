import type { Decision, Forecast, Job, MarketSnapshot, TerminalData } from "./types";

// Hand-authored visual fixtures only. No training, scheduling, execution or benchmark occurred.
export const previewSlot = 8;
const jobRows = [
  ["WK-001", "embedding-batch-v4", "GPU", "A100", 2, 2, 14, 24],
  ["WK-002", "risk-simulation", "CPU", null, 8, 3, 12, 12],
  ["WK-003", "finetune-adapter", "GPU", "A100", 1, 4, 16, 30],
  ["WK-004", "feature-materialize", "CPU", null, 4, 1, 10, 5],
  ["WK-005", "vision-evaluation", "GPU", "A100", 1, 2, 11, 10],
  ["WK-006", "archive-compression", "CPU", null, 2, 2, 18, 4],
] as const;
const jobs: Job[] = jobRows.map(([id, name, resourceType, gpuType, resourceUnits, durationSlots, deadlineSlot, maxBudgetUsd], i) => ({
  id, name, resourceType, gpuType, resourceUnits, durationSlots, deadlineSlot, maxBudgetUsd,
  arrivalSlot: 6, allowedRegions: ["eu-west-1", "eu-central-1", "us-east-1"], priority: i < 2 ? 2 : 1,
  status: "PENDING", dockerTaskId: null,
}));
const curves = {
  "eu-west-1": [1.48, 1.48, 1.62, 1.62, 1.44, 1.36, 1.36, 1.42, 1.42],
  "eu-central-1": [1.32, 1.32, 1.28, 1.28, 1.36, 1.36, 1.22, 1.22, 1.18],
  "us-east-1": [1.12, 1.12, 1.26, 1.26, 1.26, 1.34, 1.34, 1.30, 1.30],
};
const market: MarketSnapshot[] = Object.entries(curves).flatMap(([region, prices]) => prices.map((price, slot) => ({
  slot, region, resourceType: "GPU", gpuType: "A100", priceUsdPerUnitHour: price,
  availableUnits: region === "eu-central-1" ? 2 : 4, carbonKgPerUnitHour: null,
  source: "Hand-authored visual preview", dataKind: "SIMULATED",
})));
const futures = {
  "eu-west-1": [1.36, 1.28, 1.28, 1.22, 1.22, 1.26],
  "eu-central-1": [1.14, 1.06, 1.06, 1.10, 1.10, 1.16],
  "us-east-1": [1.26, 1.20, 1.20, 1.24, 1.28, 1.28],
};
const forecasts: Forecast[] = Object.entries(futures).flatMap(([region, prices]) => prices.map((price, i) => ({
  generatedAtSlot: previewSlot, targetSlot: previewSlot + i + 1, region, resourceType: "GPU", gpuType: "A100",
  predictedPriceUsdPerUnitHour: price, priceLowerBound: +(price - .10).toFixed(2), priceUpperBound: +(price + .10).toFixed(2),
  availabilityProbability: null, interruptionProbability: null, modelVersion: "illustrative-not-trained",
})));
// Additional hand-authored CPU examples exercise resource filtering, not real capacity.
for (const [region, base] of [["eu-west-1", .06], ["eu-central-1", .05], ["us-east-1", .07]] as const) {
  for (let slot = 0; slot <= previewSlot; slot++) market.push({
    slot, region, resourceType: "CPU", gpuType: null,
    priceUsdPerUnitHour: +(base + (slot < 4 ? .01 : 0)).toFixed(3),
    availableUnits: region === "eu-west-1" ? 32 : 16, carbonKgPerUnitHour: null,
    source: "Hand-authored CPU visual preview", dataKind: "SIMULATED",
  });
  for (let horizon = 1; horizon <= 6; horizon++) forecasts.push({
    generatedAtSlot: previewSlot, targetSlot: previewSlot + horizon, region, resourceType: "CPU", gpuType: null,
    predictedPriceUsdPerUnitHour: base, priceLowerBound: +(base - .01).toFixed(3), priceUpperBound: +(base + .01).toFixed(3),
    availabilityProbability: null, interruptionProbability: null, modelVersion: "illustrative-cpu-not-trained",
  });
}
const earlierGpuIssue = forecasts.filter(row => row.resourceType === "GPU" && row.targetSlot <= previewSlot + 5).map(row => ({
  ...row, generatedAtSlot: previewSlot - 1, modelVersion: "illustrative-earlier-not-trained",
  predictedPriceUsdPerUnitHour: +(row.predictedPriceUsdPerUnitHour + .05).toFixed(3),
  priceLowerBound: +(row.priceLowerBound! + .05).toFixed(3), priceUpperBound: +(row.priceUpperBound! + .05).toFixed(3),
}));
forecasts.push(...earlierGpuIssue);
const decisions: Decision[] = [
  { jobId: "WK-001", decidedAtSlot: 8, action: "WAIT", region: "eu-central-1", plannedStartSlot: 10, plannedEndSlot: 12,
    projectedCostUsd: 4.24, reasonCode: "EXAMPLE_LOWER_PRICE_WINDOW", explanation: "Example plan: wait two slots for the illustrated $1.06/unit-hour window. Two GPUs × two hours gives $4.24 projected compute cost. Completion at slot 12 retains two slots before the deadline. Risk is unknown; overhead is excluded.", executionMode: "SIMULATED" },
  { jobId: "WK-003", decidedAtSlot: 8, action: "ROUTE", region: "us-east-1", plannedStartSlot: 8, plannedEndSlot: 12,
    projectedCostUsd: null, reasonCode: "EXAMPLE_REGION_SELECTION", explanation: "Illustrative routing action before execution. This is a visual example; no optimizer or cloud execution has run.", executionMode: "SIMULATED" },
  { jobId: "WK-005", decidedAtSlot: 8, action: "RUN", region: "eu-west-1", plannedStartSlot: 8, plannedEndSlot: 10,
    projectedCostUsd: null, reasonCode: "EXAMPLE_DEADLINE_PRESSURE", explanation: "Illustrative urgent execution recommendation. One slot remains between the planned end and deadline. No container has been started.", executionMode: "SIMULATED" },
];
export const previewData: TerminalData = {
  jobs, market, forecasts, decisions,
  replay: { status: "NOT_IMPLEMENTED", currentSlot: previewSlot, seed: 42,
    strategies: ["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"] },
};
