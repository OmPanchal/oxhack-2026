import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

// Exercise the actual TypeScript helper without introducing a separate test runner.
const source = await readFile(new URL("../lib/workloads.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { prepareJob, formatTimeLeft, rebaseJob, deadlineAttention, filterJobs } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const draft = { name: "Training run", resourceType: "GPU", resourceUnits: "2", gpuTypes: ["A100"], durationHours: "2", completeWithinHours: "2", regions: ["eu-west-1", "us-east-1", "eu-west-1"], budget: "", priority: "1" };
const create = (changes = {}, clock = 8) => prepareJob({ ...draft, ...changes }, clock, "test-job");

test("completion windows map directly to slots without a UTC origin", () => {
  assert.equal(create().payload.deadlineSlot, 10);
  assert.equal(create({}, 0).payload.deadlineSlot, 2);
  assert.equal(create({ completeWithinHours: "6" }).payload.deadlineSlot, 14);
});
test("duration may equal the window; invalid or too-short windows are rejected", () => {
  assert.ok(create().payload);
  assert.ok(create({ completeWithinHours: "1" }).errors.completeWithinHours);
  for (const completeWithinHours of ["", "0", "-1", "1.5", "NaN", "Infinity"]) {
    assert.ok(create({ completeWithinHours }).errors.completeWithinHours);
  }
  assert.ok(create({ completeWithinHours: String(Number.MAX_SAFE_INTEGER) }).errors.completeWithinHours);
});
test("invalid scheduling clocks cannot create a job", () => {
  for (const slot of [null, NaN, -1, .5, Infinity]) assert.ok(create({}, slot).errors.clock);
});
test("GPU and CPU requirements map to the existing create-job contract", () => {
  const gpu = create().payload;
  assert.deepEqual(gpu.allowedRegions, ["eu-west-1", "us-east-1"]);
  assert.equal(gpu.maxBudgetUsd, null);
  assert.equal(gpu.dockerTaskId, null);
  assert.equal(gpu.arrivalSlot, 8);
  assert.equal(create({ resourceType: "CPU", gpuTypes: ["A100", "H100"], budget: "0" }).payload.gpuType, null);
  assert.equal(create({ budget: "0" }).payload.maxBudgetUsd, 0);
  assert.ok(create({ gpuTypes: [] }).errors.gpuTypes);
});
test("invalid requirements are rejected before sending a request", () => {
  for (const resourceUnits of ["0", "-1", "1.5", "NaN", "Infinity"]) assert.ok(create({ resourceUnits }).errors.resourceUnits);
  for (const durationHours of ["0", "1.5", ""]) assert.ok(create({ durationHours }).errors.durationHours);
  assert.ok(create({ name: " " }).errors.name);
  assert.ok(create({ regions: [] }).errors.regions);
  assert.ok(create({ budget: "-2" }).errors.budget);
  assert.ok(create({ budget: "Infinity" }).errors.budget);
});
test("search/filter/sort remain deterministic and never mutate backend job arrays", () => {
  const base = { ...create().payload, status: "PENDING" };
  const jobs = [{ ...base, id: "b", name: "CPU batch", resourceType: "CPU", priority: 2 }, { ...base, id: "a" }];
  const filters = { query: "", resource: "ALL", status: "ALL", sort: "deadline" };
  assert.deepEqual(filterJobs(jobs, filters).map(job => job.id), ["a", "b"]);
  assert.equal(jobs[0].id, "b");
  assert.deepEqual(filterJobs(jobs, { ...filters, resource: "CPU", query: "BATCH" }).map(job => job.id), ["b"]);
  assert.equal(filterJobs(jobs, { ...filters, status: "FAILED" }).length, 0);
  assert.equal(filterJobs(jobs, { ...filters, sort: "priority" })[0].id, "b");
  assert.equal(filterJobs(jobs, { ...filters, query: "us-east-1" }).length, 2);
});
test("attention includes unfinished deadlines and failures without flagging completed jobs", () => {
  const base = { ...create().payload, status: "PENDING" };
  assert.equal(deadlineAttention(base, 8), "Deadline pressure");
  assert.equal(deadlineAttention({ ...base, status: "COMPLETED" }, 12), null);
  assert.equal(deadlineAttention({ ...base, status: "FAILED" }, 8), "Execution failed");
  assert.equal(deadlineAttention({ ...base, status: "INFEASIBLE" }, 8), "Infeasible");
  assert.equal(deadlineAttention({ ...base, status: "RUNNING" }, 9), null);
  assert.equal(deadlineAttention(base, 10), "Deadline reached");
});

test("multiple GPU alternatives are preserved as one job; CPU strips all GPU constraints", () => {
  const multi = create({ gpuTypes: ["A100", "H100", "A100"] }).payload;
  assert.deepEqual(multi.allowedGpuTypes, ["A100", "H100"]);
  assert.equal(multi.gpuType, null);
  assert.equal(multi.id, "test-job");
  assert.equal(multi.resourceUnits, 2);
  assert.deepEqual(create({ resourceType: "CPU", gpuTypes: ["A100", "H100"] }).payload.allowedGpuTypes, []);
  const jobs = [{ ...multi, status: "PENDING" }];
  assert.equal(filterJobs(jobs, { query: "H100", resource: "GPU", status: "ALL", sort: "deadline" }).length, 1);
});

test("submission rebases the full window onto the latest backend slot", () => {
  const payload = create({ completeWithinHours: "6" }).payload;
  const submitted = rebaseJob(payload, 12);
  assert.equal(submitted.arrivalSlot, 12);
  assert.equal(submitted.deadlineSlot, 18);
  assert.equal(submitted.durationSlots, 2);
  assert.equal(submitted.id, payload.id);
  assert.equal(payload.arrivalSlot, 8);
  assert.equal(payload.deadlineSlot, 14);
  assert.throws(() => rebaseJob(payload, NaN));
  assert.throws(() => rebaseJob(payload, Number.MAX_SAFE_INTEGER));
  assert.equal(formatTimeLeft(14, 8), "6h left");
  assert.equal(formatTimeLeft(8, 8), "Due now");
  assert.equal(formatTimeLeft(7, 8), "1h past deadline");
});


test("allowlisted local tasks map to their fixed CPU requirements without stale GPU constraints", () => {
  const task = { id: "cpu-hash-v1", name: "Local hash", resourceType: "CPU", resourceUnits: 1, region: "local" };
  const result = prepareJob({ ...draft, gpuTypes: ["H100"], regions: [] }, 12, "local-job", task);
  assert.ok(result.payload);
  assert.equal(result.payload.dockerTaskId, task.id);
  assert.equal(result.payload.resourceType, "CPU");
  assert.equal(result.payload.resourceUnits, 1);
  assert.deepEqual(result.payload.allowedRegions, ["local"]);
  assert.deepEqual(result.payload.allowedGpuTypes, []);
  assert.equal(result.payload.gpuType, null);
});
