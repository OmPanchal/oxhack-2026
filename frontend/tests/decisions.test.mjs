import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../lib/decisions.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { latestDecision, slotLabel, deadlineBuffer } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

test("plan selection excludes future decisions and selects the newest issue for this job", () => {
  const old = { jobId: "a", decidedAtSlot: 4, action: "RUN" };
  const current = { jobId: "a", decidedAtSlot: 8, action: "WAIT" };
  const future = { jobId: "a", decidedAtSlot: 9, action: "ROUTE" };
  const rows = [old, future, current, { jobId: "b", decidedAtSlot: 8 }];
  assert.equal(latestDecision(rows, "a", 8), current);
  assert.equal(latestDecision(rows, "a", 7), old);
  assert.equal(latestDecision(rows, "missing", 8), undefined);
  assert.equal(latestDecision(rows, null, 8), undefined);
  assert.equal(latestDecision([future], "a", 8), undefined);
  assert.equal(rows[0], old);
});

test("relative plan labels follow scheduling time and preserve slot zero", () => {
  assert.equal(slotLabel(0, 0), "Slot 0 · now");
  assert.equal(slotLabel(10, 8), "Slot 10 · in 2h");
  assert.equal(slotLabel(10, 11), "Slot 10 · 1h ago");
});

test("deadline buffer accepts exact deadlines and preserves missing or late planned ends", () => {
  assert.equal(deadlineBuffer(14, 12), "2h before deadline");
  assert.equal(deadlineBuffer(14, 14), "Ends at deadline");
  assert.equal(deadlineBuffer(14, 16), "2h after deadline");
  assert.equal(deadlineBuffer(14, null), "Unavailable");
  assert.equal(deadlineBuffer(0, 0), "Ends at deadline");
});
