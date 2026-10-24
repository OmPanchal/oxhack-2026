import fixture from "../../data/scenarios/demo.json";
import type { Job, MarketSnapshot, TerminalData } from "./types";
// One shared fixture for Python contract checks and independent UI development.
export const mockData: TerminalData = {
  jobs: fixture.jobs as Job[], market: fixture.market as MarketSnapshot[],
  forecasts: [], decisions: [], replay: {
    status: "NOT_IMPLEMENTED", currentSlot: 0, seed: 42,
    strategies: ["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"],
  },
};
