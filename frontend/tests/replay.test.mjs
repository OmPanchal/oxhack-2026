import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
async function load(file) {
  const source = await readFile(new URL(file, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}
const { replayScenarios, previewData } = await load("../lib/preview.ts");
const { nextFrame } = await load("../lib/replay-view.ts");

test("prepared playback stops at the final event and reset can select the original snapshot", () => {
  for (const scenario of replayScenarios) {
    let index = 0;
    for (let tick = 0; tick < 30; tick++) index = nextFrame(index, scenario.frames.length);
    assert.equal(index, scenario.frames.length - 1);
    assert.equal(nextFrame(index, scenario.frames.length), index);
    assert.equal(scenario.frames[0].slot, 8);
  }
});

test("prepared scenarios have chronological slots, simulated quotes and no future decisions", () => {
  assert.equal(new Set(replayScenarios.map(row => row.id)).size, 3);
  for (const scenario of replayScenarios) {
    let previous = -1;
    for (const frame of scenario.frames) {
      assert.ok(frame.slot > previous);
      previous = frame.slot;
      assert.ok(frame.market.every(row => row.slot === frame.slot && row.dataKind === "SIMULATED"));
      assert.ok(frame.decisions.every(row => row.decidedAtSlot <= frame.slot && row.executionMode === "SIMULATED" && row.jobId === frame.jobs[0].id));
      assert.equal(frame.execution.mode, "SIMULATED");
      assert.equal(frame.execution.jobId, frame.jobs[0].id);
      if (frame.execution.status === "PENDING" || frame.execution.status === "RUNNING") assert.equal(frame.execution.exitCode, null);
    }
  }
});

test("failure storyboard exposes failed unfinished work, logs and exit code; success retains genuine zero", () => {
  const failure = replayScenarios.find(row => row.id === "capacity-loss").frames.at(-1);
  assert.equal(failure.jobs[0].status, "FAILED");
  assert.equal(failure.execution.status, "FAILED");
  assert.equal(failure.execution.exitCode, 137);
  assert.ok(failure.execution.failureReason);
  assert.ok(failure.execution.stderr.length);
  const success = replayScenarios.find(row => row.id === "normal").frames.at(-1);
  assert.equal(success.jobs[0].status, "COMPLETED");
  assert.equal(success.execution.exitCode, 0);
  assert.equal(previewData.replay.currentSlot, 8);
  assert.ok(previewData.jobs.every(row => row.status === "PENDING"));
});
