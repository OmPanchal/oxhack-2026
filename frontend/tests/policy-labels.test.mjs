import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
import { createRequire } from "node:module";

const source = await readFile(new URL("../lib/policy-labels.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const labels = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const { policyPresentation, policyLabel } = labels;
const ml = "OPTIMIZER_WITH_ML";
const learned = "lightgbm-price-l1-v1-gpu-734be7a557de";
const fallback = "persistence-v1:fallback-model-not-available";

test("frontend presents only FIFO, cheapest now and ML", () => {
  assert.deepEqual(labels.visiblePolicies, ["FIFO", "CHEAPEST_NOW", ml]);
});

test("fallback-only replay is explicitly labeled ML not used", () => {
  const usage = policyPresentation(ml, [fallback, fallback], "ACTIVE");
  assert.equal(usage.label, "Optimizer / persistence fallback");
  assert.match(usage.note, /ML not used/);
  assert.match(usage.note, /predates/);
  assert.equal(policyLabel(ml, ["persistence-v1:fallback-insufficient-history"]), usage.label);
  assert.equal(policyLabel(ml, ["integration-persistence-v1"]), usage.label);
});

test("cumulative fallback history prevents a mixed run being labeled ML-only", () => {
  const usage = policyPresentation(ml, [fallback, learned]);
  assert.equal(usage.label, "Optimizer / ML + persistence fallback");
  assert.match(usage.note, /not an ML-only result/);
  assert.equal(policyLabel(ml, [learned]), "Optimizer / ML");
});

test("missing providers, unstarted runs and unknown versions do not claim ML usage", () => {
  assert.equal(policyLabel(ml, [], "UNAVAILABLE"), "Optimizer / ML unavailable");
  assert.match(policyPresentation(ml, []).note, /No forecasts recorded/);
  assert.equal(policyLabel(ml, ["unrecognized-model"]), "Optimizer / ML requested");
  assert.match(policyPresentation(ml, [learned, "unrecognized-model"]).note, /unverified/);
  assert.equal(policyLabel("FIFO"), "FIFO");
  assert.equal(policyLabel("OPTIMIZER_WITH_NAIVE_FORECAST"), "Optimizer / persistence");
});

test("comparison keeps provenance labels in rows without comparison paragraphs", async () => {
  const require = createRequire(import.meta.url);
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const component = await readFile(new URL("../components/PolicyComparison.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(component, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
  } }).outputText;
  const exports = {};
  new Function("require", "exports", "React", compiled)(id => id === "@/lib/policy-labels" ? labels : require(id), exports, React);
  const metrics = {
    status: "COMPLETED",
    strategies: [{ strategy: ml, status: "ACTIVE", modelVersions: [fallback], totals: { totalSpendUsd: 5 } }],
    comparisons: [
      { strategy: ml, baseline: "FIFO", comparable: false, explanation: "Different outcomes." },
      { strategy: ml, baseline: "OPTIMIZER_WITH_NAIVE_FORECAST", comparable: false, explanation: "Hidden ablation comparison." },
      { strategy: "OPTIMIZER_WITH_NAIVE_FORECAST", baseline: "FIFO", comparable: false, explanation: "Hidden persistence result." },
    ],
  };
  const html = renderToStaticMarkup(React.createElement(exports.PolicyComparison, { metrics }));
  assert.match(html, /ML not used/);
  assert.match(html, /Optimizer \/ persistence fallback/);
  assert.match(html, /<summary>Model versions<\/summary>/);
  assert.match(html, /\$5\.0000/);
  assert.doesNotMatch(html, /vs FIFO|Different outcomes\.|Backend accounting/);
  assert.doesNotMatch(html, /Hidden ablation|Hidden persistence|Optimizer \/ persistence<\/td>/);
});
