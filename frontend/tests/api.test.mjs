import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
// The preview module is irrelevant to explicit backend reads; keep this loader independent of JSON module flags.
const source = (await readFile(new URL("../lib/api.ts", import.meta.url), "utf8"))
  .replace('import { mockData } from "./mock";', 'const mockData = { previewSentinel: true };');
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { api, loadBackendTerminal, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

test("API client sends the backend's actual endpoint paths, scopes, camelCase payloads and encoded IDs", async t => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => { calls.push({ url, ...options }); return Response.json({}); });
  await api.engineState(); await api.metrics(); await api.liveMetrics(); await api.decisionDetails();
  await api.capabilities(); await api.taskCatalog(); await api.executions(); await api.pause(); await api.resume();
  await api.resetReplay({ scenarioId: "demo", seed: 42 }); await api.stepReplay({ slots: 1 });
  await api.shock({ kind: "PRICE_SPIKE", slot: 3, magnitude: 2, dataKind: "SIMULATED" });
  await api.execute("id /?");
  assert.deepEqual(calls.slice(0, 7).map(row => row.url), ["/api/engine/state", "/api/metrics?scope=REPLAY", "/api/metrics?scope=LIVE", "/api/decisions/details", "/api/capabilities", "/api/execution/tasks", "/api/executions"]);
  assert.equal(calls[9].method, "POST");
  assert.deepEqual(JSON.parse(calls[9].body), { scenarioId: "demo", seed: 42 });
  assert.deepEqual(JSON.parse(calls[10].body), { slots: 1 });
  assert.equal(calls.at(-1).url, "/api/execute/id%20%2F%3F");
  assert.equal(calls.at(-1).body, "{}");
});

test("explicit backend load keeps live and replay clocks separate and retains useful state on auxiliary failure", async t => {
  t.mock.method(globalThis, "fetch", async url => {
    if (url === "/api/engine/state") return Response.json({ currentSlot: 12 });
    if (url === "/api/jobs") return Response.json([{ id: "real-job" }]);
    if (url === "/api/replay/state") return Response.json({ currentSlot: 2, initialized: true });
    if (url === "/api/forecasts") return Response.json({ detail: { code: "FORECAST_PROVIDER_UNAVAILABLE", message: "No ML provider" } }, { status: 503 });
    return Response.json([]);
  });
  const result = await loadBackendTerminal();
  assert.equal(result.engine.currentSlot, 12);
  assert.equal(result.replay.currentSlot, 2);
  assert.equal(result.jobs[0].id, "real-job");
  assert.deepEqual(result.forecasts, []);
  assert.ok(result.errors.some(error => error.includes("No ML provider")));
});

test("a core backend failure rejects instead of substituting preview data", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "Offline" }, { status: 503 }));
  await assert.rejects(loadBackendTerminal(), /Offline/);
});

test("backend errors preserve their status/code and expose FastAPI field validation messages", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ detail: { code: "DISPATCH_PAUSED", message: "Starts are paused" } }, { status: 409 }));
  await assert.rejects(api.execute("a"), error => error instanceof ApiError && error.code === "DISPATCH_PAUSED" && error.status === 409);
  globalThis.fetch.mock.mockImplementation(async () => Response.json({ detail: [{ loc: ["body", "durationSlots"], msg: "Must be positive" }] }, { status: 422 }));
  await assert.rejects(api.createJob({}), /body.durationSlots: Must be positive/);
});


test("network failures identify the endpoint and never retry writes automatically", async t => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => { calls++; throw new TypeError("Failed to fetch"); });
  await assert.rejects(api.modelStatus(), error => error.code === "BACKEND_UNREACHABLE" && error.message.includes("/models/status"));
  await assert.rejects(api.createJob({}), /request outcome is unknown/i);
  assert.equal(calls, 2);
});


test("auxiliary outages preserve last known data with a stale warning", async t => {
  t.mock.method(globalThis, "fetch", async url => {
    if (url === "/api/engine/state") return Response.json({currentSlot:12, forecastMode:"ML"});
    if (url === "/api/jobs") return Response.json([]);
    if (url === "/api/market" || url === "/api/forecasts") return Response.json({detail:"temporarily offline"},{status:503});
    return Response.json([]);
  });
  const old = {engine:{forecastMode:"ML"},market:[{slot:11}],forecasts:[{modelVersion:"old-ML"}]};
  const result = await loadBackendTerminal(old);
  assert.deepEqual(result.market,old.market);
  assert.deepEqual(result.forecasts,old.forecasts);
  assert.ok(result.errors.some(error => error.includes("may be stale")));
  const changed = await loadBackendTerminal({...old,engine:{forecastMode:"NAIVE"}});
  assert.deepEqual(changed.forecasts,[]);
});

test("mismatched replay and live metric snapshots are never rendered as current totals", async t => {
  t.mock.method(globalThis,"fetch", async url => {
    if (url === "/api/engine/state") return Response.json({currentSlot:12});
    if (url === "/api/jobs") return Response.json([{id:"new",status:"PENDING"}]);
    if (url === "/api/replay/state") return Response.json({currentSlot:2,scenarioId:"new"});
    if (url === "/api/metrics?scope=REPLAY") return Response.json({scope:"REPLAY",scenarioId:"old",asOfSlot:3});
    if (url === "/api/metrics?scope=LIVE") return Response.json({scope:"LIVE",asOfSlot:12,jobCounts:{pendingJobs:0}});
    return Response.json([]);
  });
  const result=await loadBackendTerminal();
  assert.equal(result.replayMetrics,undefined);
  assert.equal(result.liveMetrics,undefined);
  assert.ok(result.errors.some(error => error.includes("mismatched")));
});
