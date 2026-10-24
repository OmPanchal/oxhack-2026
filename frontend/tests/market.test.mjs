import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../lib/market.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { resourceKey, marketResources, compareRegions, lowestCurrentQuote, forecastRuns, upcomingPoints, plotPoints, stepPath, bounds, probability, price, priceAxis } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const quote = (overrides = {}) => ({ slot: 8, region: "eu-west-1", resourceType: "GPU", gpuType: "A100", priceUsdPerUnitHour: 1.4, availableUnits: 4, carbonKgPerUnitHour: null, source: "test observations", dataKind: "OBSERVED", ...overrides });
const prediction = (overrides = {}) => ({ generatedAtSlot: 8, targetSlot: 9, region: "eu-west-1", resourceType: "GPU", gpuType: "A100", predictedPriceUsdPerUnitHour: 1.2, priceLowerBound: 1, priceUpperBound: 1.4, availabilityProbability: null, interruptionProbability: null, modelVersion: "model-v1", ...overrides });
const resource = resourceKey(quote());

test("comparison never mixes CPU, GPU models, simulated quotes or future observations", () => {
  const rows = compareRegions([
    quote(), quote({ slot: 9, priceUsdPerUnitHour: .01 }),
    quote({ region: "cpu", resourceType: "CPU", gpuType: null, priceUsdPerUnitHour: .001 }),
    quote({ region: "h100", gpuType: "H100", priceUsdPerUnitHour: .01 }),
    quote({ region: "simulated", dataKind: "SIMULATED", priceUsdPerUnitHour: .01 }),
    quote({ region: "forecast-disguised-as-quote", dataKind: "FORECAST", priceUsdPerUnitHour: .01 }),
  ], [], resource, "OBSERVED", 8);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].quote.priceUsdPerUnitHour, 1.4);
  assert.notEqual(resourceKey(quote({ resourceType: "CPU", gpuType: null })), resourceKey(quote({ gpuType: "CPU" })));
});
test("lowest current quote excludes stale and insufficient capacity, retaining zero prices", () => {
  const rows = compareRegions([
    quote({ region: "stale", slot: 7, priceUsdPerUnitHour: .1 }),
    quote({ region: "short", availableUnits: 0, priceUsdPerUnitHour: .2 }),
    quote({ region: "enough", availableUnits: 2, priceUsdPerUnitHour: 0 }), quote(),
  ], [], resource, "OBSERVED", 8);
  assert.equal(lowestCurrentQuote(rows, 8, 2).region, "enough");
  assert.equal(lowestCurrentQuote(rows, 8, 3).region, "eu-west-1");
  assert.equal(lowestCurrentQuote(rows, 8, 5), null);
  assert.equal(lowestCurrentQuote(rows, 8, NaN), null);
});
test("forecast issues do not leak future generation times or mix model versions", () => {
  const rows = [prediction(), prediction({ targetSlot: 10 }), prediction({ modelVersion: "model-v2", predictedPriceUsdPerUnitHour: 9 }),
    prediction({ generatedAtSlot: 7, targetSlot: 9, modelVersion: "older" }),
    prediction({ generatedAtSlot: 9, targetSlot: 10, modelVersion: "future" }), prediction({ targetSlot: 16 })];
  const runs = forecastRuns(rows, resource, "eu-west-1", 8);
  assert.equal(runs.length, 3);
  assert.equal(runs[0].issued, 8);
  assert.ok(runs.every(run => run.points.every(point => point.modelVersion === run.model && point.generatedAtSlot === run.issued)));
  assert.deepEqual(runs[0].points.map(row => row.targetSlot), [9, 10]);
  assert.equal(upcomingPoints(runs[0], 8, 1).length, 1);
  assert.equal(upcomingPoints(runs[2], 12, 6).length, 0);
});
test("comparison uses next-slot forecast, not the cheapest distant prediction", () => {
  const rows = compareRegions([quote()], [prediction({ targetSlot: 10, predictedPriceUsdPerUnitHour: .1 })], resource, "OBSERVED", 8);
  assert.equal(rows[0].next, null);
});
test("forecast-only regions retain missing quote/capacity rather than synthetic zeros", () => {
  const rows = compareRegions([], [prediction()], resource, "OBSERVED", 8);
  assert.equal(rows[0].quote, null);
  assert.equal(rows[0].next.predictedPriceUsdPerUnitHour, 1.2);
  assert.equal(lowestCurrentQuote(rows, 8, 1), null);
  assert.equal(price(null), "—");
  assert.equal(price(0), "$0.000");
  assert.equal(price(.0004), "$0.000400");
});
test("uncertainty bounds and risk distinguish missing values from genuine zeros", () => {
  assert.equal(bounds(prediction({ priceLowerBound: null })), null);
  assert.equal(bounds(prediction({ priceLowerBound: 2, priceUpperBound: 1 })), null);
  assert.deepEqual(bounds(prediction({ priceLowerBound: 0, priceUpperBound: 0 })), [0, 0]);
  assert.equal(probability(null), "Unknown");
  assert.equal(probability(0), "0.0%");
  assert.equal(probability(1), "100.0%");
  assert.equal(probability(2), "Unknown");
});
test("hourly plot geometry never draws a continuous line across missing observations", () => {
  const points = plotPoints([quote({ slot: 4, priceUsdPerUnitHour: 1 }), quote({ slot: 6, priceUsdPerUnitHour: 2 }), quote({ slot: 7, priceUsdPerUnitHour: 3 }), quote({ slot: 9 })], [], 8);
  assert.deepEqual(points.map(point => point.slot), [4, 6, 7]);
  const path = stepPath(points, n => n, n => n);
  assert.equal(path, "M4 1 H5 M6 2 H7 V3 H8");
  assert.ok(!/[CQ]/.test(path));
});
test("resources and axis ticks remain honest for empty, flat and very cheap data", () => {
  assert.deepEqual(marketResources([quote({ slot: 9 })], [prediction({ generatedAtSlot: 9 })], 8), []);
  for (const values of [[], [0], [1.2, 1.2], [.003, .004], [1.18, 1.62]]) {
    const ticks = priceAxis(values);
    assert.ok(ticks.length >= 2);
    assert.ok(ticks.every(Number.isFinite));
    assert.ok(ticks[ticks.length - 1] > ticks[0]);
    assert.ok(!values.length || ticks[0] <= Math.min(...values));
    assert.ok(!values.length || ticks[ticks.length - 1] >= Math.max(...values));
  }
});
