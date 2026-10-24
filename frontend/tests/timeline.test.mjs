import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../lib/timeline.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { timelineWindow } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const job = { id: "a", arrivalSlot: 6, deadlineSlot: 14 };
const decision = { jobId: "a", decidedAtSlot: 8, action: "WAIT", plannedStartSlot: 10, plannedEndSlot: 12 };

test("timeline positions supplied waiting and execution windows without changing their duration", () => {
  const window = timelineWindow(job, decision, 8);
  assert.equal(window.origin, 6);
  assert.equal(window.limit, 14);
  assert.equal(window.now, 25);
  assert.equal(window.deadline, 100);
  assert.equal(window.plan.left, 50);
  assert.equal(window.plan.width, 25);
  assert.equal(window.plan.waitWidth, 50);
});

test("timeline does not invent plans for missing, foreign, future, infeasible or malformed decisions", () => {
  for (const input of [undefined, { ...decision, jobId: "b" }, { ...decision, decidedAtSlot: 9 },
    { ...decision, action: "INFEASIBLE" }, { ...decision, plannedStartSlot: null },
    { ...decision, plannedStartSlot: 5 }, { ...decision, plannedEndSlot: 9 }, { ...decision, plannedEndSlot: NaN }]) {
    assert.equal(timelineWindow(job, input, 8).plan, null);
  }
});

test("late ends and elapsed deadlines stay visible, while slot zero and zero-length domains remain finite", () => {
  const late = timelineWindow(job, { ...decision, plannedEndSlot: 16 }, 8);
  assert.equal(late.limit, 16);
  assert.ok(late.deadline < late.plan.left + late.plan.width);
  const elapsed = timelineWindow(job, decision, 20);
  assert.equal(elapsed.limit, 20);
  assert.equal(elapsed.now, 100);
  const zero = timelineWindow({ ...job, arrivalSlot: 0, deadlineSlot: 0 }, undefined, 0);
  assert.equal(zero.limit, 1);
  assert.equal(zero.deadline, 0);
  assert.ok(Number.isFinite(zero.now));
});
