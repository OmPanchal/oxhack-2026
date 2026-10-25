import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import ts from "typescript";

const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
async function compile(file, dependencies = {}) {
  const source = await readFile(new URL(file, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
  } }).outputText;
  const exports = {};
  new Function("require", "exports", "React", compiled)(id => dependencies[id] ?? require(id), exports, React);
  return exports;
}
const dependencies = {
  "@/lib/api": { api: {} },
  "@/lib/decisions": await compile("../lib/decisions.ts"),
  "@/lib/replay-view": await compile("../lib/replay-view.ts"),
  "@/lib/policy-labels": await compile("../lib/policy-labels.ts"),
  "./DecisionInspector": { DecisionInspector: () => null },
  "./BackendExecution": { BackendExecution: () => null },
};
dependencies["./PolicyComparison"] = await compile("../components/PolicyComparison.tsx", dependencies);
const { BackendReplayWorkspace } = await compile("../components/BackendReplayWorkspace.tsx", dependencies);
const job = { id: "test", name: "Training batch", resourceType: "GPU", resourceUnits: 1,
  gpuType: "T4", allowedRegions: ["eu-north-1"], arrivalSlot: 168, durationSlots: 2,
  deadlineSlot: 192, status: "COMPLETED" };
const run = { strategy: "OPTIMIZER_WITH_ML", status: "ACTIVE", jobs: [job],
  forecasts: [], modelVersionsUsed: ["lightgbm-price-test"],
  decisions: [{ jobId: job.id, decidedAtSlot: 168, action: "WAIT", explanation: "Predicted cheaper window." },
    { jobId: job.id, decidedAtSlot: 170, action: "RUN", explanation: "Start the batch." }],
  outcomes: [{ jobId: job.id, slot: 172, status: "COMPLETED", reason: "SIMULATED_DURATION_ELAPSED" }] };
const replay = { initialized: true, status: "COMPLETED", scenarioId: "historical-t4-a10g",
  seed: 44, currentSlot: 216, startSlot: 168, endSlot: 216,
  description: "SELECTED SUCCESS EXAMPLE: test", strategies: [run.strategy], strategyStates: [run], events: [] };
const render = state => renderToStaticMarkup(React.createElement(BackendReplayWorkspace,
  { data: { replay: state }, active: true, onRefresh() {} }));

test("replay tells the workload, decision, outcome and comparison story in order", () => {
  const html = render(replay);
  const headings = ["Workload", "Decision", "Outcome", "Policy comparison"].map(text => html.indexOf(`<h2>${text}</h2>`));
  assert.ok(headings.every((position, i) => position >= 0 && (i === 0 || position > headings[i - 1])));
  assert.match(html, /2 hours/);
  assert.match(html, /24 hours of arrival/);
  assert.match(html, /Earlier decision at slot 168: WAIT/);
  assert.match(html, /Finished 4 hours after arrival/);
  assert.match(html, /Selected historical success example/);
  assert.match(html, /<details class="replay-more"><summary>Replay settings and data sources/);
  assert.match(html, /<details class="replay-more"><summary>Capacity by pool/);
  assert.match(html, /<details class="replay-more"><summary>Simulated shocks/);
});

test("unavailable ML and absent outcomes remain explicit without fabricated completion", () => {
  const html = render({ ...replay, status: "RUNNING", description: null,
    strategyStates: [{ ...run, status: "UNAVAILABLE", error: "Provider unavailable", jobs: [], decisions: [], outcomes: [] }] });
  assert.match(html, /Provider unavailable/);
  assert.match(html, /No arrived workloads for this policy/);
  assert.doesNotMatch(html, /Finished 4 hours|Selected historical success example/);
});
