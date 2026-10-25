// Opt-in only: point at the disposable SIMULATED fixture, never a live backend.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const target = process.env.INTEGRATION_AUDIT_URL;
test('frontend API client and proxy agree with the running FastAPI contracts', {skip: !target}, async () => {
  process.env.NEXT_PUBLIC_API_BASE_URL = target;
  const source = (await readFile(new URL('../lib/api.ts', import.meta.url), 'utf8'))
    .replace('import { mockData } from "./mock";', 'const mockData = {};');
  const js = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  const {api, loadBackendTerminal, ApiError} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
  const snapshot = await loadBackendTerminal();
  assert.ok(snapshot.market.length && snapshot.market.every(r => r.dataKind === 'SIMULATED'), 'Only use the disposable SIMULATED fixture');
  assert.ok(snapshot.jobs.some(j => j.name === 'SIMULATED CPU audit'), 'Fixture identity check');
  assert.deepEqual(snapshot.errors, []);
  assert.equal((await api.health()).status, 'ok');
  assert.equal(snapshot.modelStatus.status, 'READY');
  assert.equal(snapshot.forecasts.length, 252);
  assert.ok(snapshot.forecasts.every(r => 'predictedPriceUsdPerUnitHour' in r));
  const current = snapshot.engine.wallClockSlot;
  const job = await api.createJob({id:`http-audit-${Date.now()}`,name:'SIMULATED HTTP contract job',
    arrivalSlot:current, durationSlots:1, deadlineSlot:current+2,resourceType:'GPU',resourceUnits:1,
    allowedGpuTypes:['A100','H100'],allowedRegions:['eu-north-1'],maxBudgetUsd:null,priority:1,dockerTaskId:null});
  assert.deepEqual(job.allowedGpuTypes, ['A100','H100']);
  assert.equal(job.gpuType,null);
  assert.equal(job.status,'PENDING');
  assert.equal((await api.pause()).dispatch.paused,true);
  assert.equal((await api.resume()).dispatch.paused,false);
  const decisions = await api.optimize({currentSlot:current,forecastMode:'ML',executionMode:'PAPER'});
  assert.ok(decisions.some(r=>r.jobId===job.id && r.reasonCode==='CAPACITY_UNKNOWN'));
  assert.equal((await api.decisionDetails()).length,(await api.decisions()).length);
  assert.ok((await api.taskCatalog()).tasks.length);
  assert.deepEqual(await api.executions(),[]);
  await assert.rejects(api.execute('missing-audit-job'), e=>e instanceof ApiError && e.status===404);
  await api.resetReplay({scenarioId:'capacity-pressure',seed:42});
  await api.shock({kind:'PRICE_SPIKE',slot:1,region:'eu-north-1',magnitude:2});
  const replay=await api.stepReplay({slots:2});
  const metrics=await api.metrics();
  assert.equal(replay.currentSlot,2);
  assert.equal(metrics.asOfSlot,2);
  assert.equal(metrics.scope,'REPLAY');
  assert.ok(metrics.strategies.every(r=>r.ledgerReconciled));
  assert.equal((await api.liveMetrics()).scope,'LIVE');
  assert.equal((await api.modelMetrics()).status,'UNAVAILABLE');
  await api.resetReplay({scenarioId:'model-coverage',seed:42});
});
