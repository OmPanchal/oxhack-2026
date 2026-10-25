import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
async function load(file) {
  const source = await readFile(new URL(file, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}
const { replayCapacityAtSlot, replayProgress } = await load("../lib/replay-view.ts");

test("capacity inspection exposes only the last processed slot, preserving zero and unknown", () => {
  const row = { region: "eu-north-1", resourceType: "GPU", gpuType: "A10G", dataKind: "SIMULATED" };
  const market = [
    { ...row, slot: 0, availableUnits: 2 },
    { ...row, slot: 1, availableUnits: 0 },
    { ...row, slot: 1, gpuType: "T4", availableUnits: null },
    { ...row, slot: 2, availableUnits: 99 },
  ];
  assert.deepEqual(replayCapacityAtSlot(market, 0), []);
  const visible = replayCapacityAtSlot(market, 2);
  assert.deepEqual(visible.map(r => r.availableUnits), [0, null]);
  assert.ok(visible.every(r => r.slot === 1));
  assert.equal(market.length, 4);
});

test("historical progress excludes warm-up and keeps normal replay clocks unchanged", () => {
  assert.deepEqual(replayProgress(168, 168, 192), { elapsed: 0, total: 24 });
  assert.deepEqual(replayProgress(192, 168, 192), { elapsed: 24, total: 24 });
  assert.deepEqual(replayProgress(1, undefined, 8), { elapsed: 1, total: 8 });
});
