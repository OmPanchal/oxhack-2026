import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../lib/timeline.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { timelineWindow, sharedTimeline, packedTimeline } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
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


test("shared timeline aligns identical slots across tasks with different deadlines", () => {
  const other = { ...job, id: "b", arrivalSlot: 4, deadlineSlot: 18 };
  const shared = sharedTimeline([{ job, decision }, { job: other, decision: { ...decision, jobId: "b" } }], 8);
  assert.equal(shared.origin, 4);
  assert.equal(shared.limit, 18);
  assert.equal(shared.rows[0].window.plan.left, shared.rows[1].window.plan.left);
  assert.equal(shared.rows[0].window.plan.width, shared.rows[1].window.plan.width);
  assert.equal(shared.rows[0].window.now, shared.rows[1].window.now);
  assert.ok(shared.rows[0].window.deadline < shared.rows[1].window.deadline);
  assert.equal(shared.ticks[0], 4);
  assert.equal(shared.ticks.at(-1), 18);
});

test("shared timeline includes late plans and unplanned tasks without fabricating bars", () => {
  const shared = sharedTimeline([{ job, decision: { ...decision, plannedEndSlot: 22 } },
    { job: { ...job, id: "missing", deadlineSlot: 28 } }], 20);
  assert.equal(shared.limit, 28);
  assert.equal(shared.rows[1].window.plan, null);
  assert.equal(shared.rows[0].window.origin, shared.rows[1].window.origin);
  assert.ok(shared.rows.every(row => row.window.now >= 0 && row.window.now <= 100));
  const empty = sharedTimeline([], 0);
  assert.deepEqual(empty.rows, []);
  assert.equal(empty.limit, 1);
});


function entry(id, start, end, deadline = 24) {
  return { job: { ...job, id, arrivalSlot: 0, deadlineSlot: deadline },
    decision: { ...decision, jobId: id, plannedStartSlot: start, plannedEndSlot: end } };
}

test("packing reuses a lane at half-open boundaries and needs lanes only for overlap", () => {
  const packed = packedTimeline([entry("a", 8, 10), entry("b", 10, 12), entry("c", 9, 11)], 8);
  assert.equal(packed.lanes.length, 2);
  assert.deepEqual(packed.lanes[0].map(row => row.job.id), ["a", "b"]);
  for (const lane of packed.lanes) for (let i = 1; i < lane.length; i++) {
    assert.ok(lane[i - 1].window.plan.end <= lane[i].window.plan.start);
  }
  assert.equal(packedTimeline([entry("a", 8, 9), entry("b", 9, 10), entry("c", 10, 11)], 8).lanes.length, 1);
});

test("packing is deterministic and matches maximum overlap regardless of input ordering", () => {
  const entries = [entry("d", 10, 15), entry("a", 8, 12), entry("c", 9, 11), entry("b", 8, 12), entry("e", 15, 16)];
  const packed = packedTimeline(entries, 8);
  const encode = result => result.lanes.map(lane => lane.map(row => row.job.id));
  assert.deepEqual(encode(packed), encode(packedTimeline([...entries].reverse(), 8)));
  const peak = Math.max(...Array.from({ length: 24 }, (_, slot) => entries.filter(row => row.decision.plannedStartSlot <= slot && row.decision.plannedEndSlot > slot).length));
  assert.equal(packed.lanes.length, peak);
  assert.equal(packed.lanes.flat().length, entries.length);
});

test("deadlines group without creating execution lanes, including jobs without plans", () => {
  const packed = packedTimeline([entry("a", 8, 10, 14), entry("b", 10, 12, 14),
    { job: { ...job, id: "unplanned", deadlineSlot: 18 } }], 8);
  assert.equal(packed.lanes.length, 1);
  assert.deepEqual(packed.deadlines.map(group => [group.slot, group.jobs.length]), [[14, 2], [18, 1]]);
  assert.deepEqual(packed.unplanned.map(row => row.job.id), ["unplanned"]);
  const empty = packedTimeline([], 8);
  assert.equal(empty.lanes.length, 0);
  assert.deepEqual(empty.deadlines, []);
});
