import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../lib/execution.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {workloadExecution} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const job = {id:'routed',status:'PENDING',allowedRegions:['eu-north-1','eu-central-1']};
const decision = {jobId:'routed',action:'ROUTE',region:'eu-central-1'};
const receipt = {jobId:'routed',region:'eu-central-1',status:'ACQUIRED',executionMode:'SIMULATED',
  requestedAtSlot:0,endSlot:1,stages:['PLANNED','ACQUISITION_REQUESTED','CAPACITY_ACQUIRED','EXECUTION_RUNNING']};

test('a route recommendation does not claim that execution has started in the destination', () => {
  const pending = workloadExecution(job,decision);
  assert.equal(pending.phase,'Awaiting acquisition');
  assert.equal(pending.region,null);
  assert.equal(pending.plannedRegion,'eu-central-1');
  assert.equal(pending.running,false);
});

test('pending local tasks stay pending independently of cloud compatibility decisions', () => {
  const local=workloadExecution({...job,dockerTaskId:'cpu-hash-v1'},
    {jobId:job.id,action:'WAIT',reasonCode:'NO_COMPATIBLE_MARKET_DATA',region:null});
  assert.equal(local.phase,'Pending local execution');
  assert.equal(local.region,null);
  assert.equal(local.started,false);
});

test('a routed job runs in its confirmed destination and completes without changing its original decision', () => {
  const running = workloadExecution({...job,status:'RUNNING'},decision,receipt);
  assert.equal(running.phase,'Running');
  assert.equal(running.region,'eu-central-1');
  assert.equal(running.routed,true);
  assert.equal(running.startedAtSlot,0);
  const completed = workloadExecution({...job,status:'COMPLETED'},decision,{...receipt,status:'COMPLETED'});
  assert.equal(completed.phase,'Completed');
  assert.equal(completed.region,'eu-central-1');
  assert.equal(completed.completedAtSlot,1);
  assert.equal(completed.running,false);
  assert.equal(decision.action,'ROUTE');
});

test('rejected or unrelated acquisitions never become confirmed execution locations', () => {
  const rejected=workloadExecution(job,decision,{...receipt,status:'REJECTED'});
  assert.equal(rejected.phase,'Capacity request rejected');
  assert.equal(rejected.region,null);
  assert.equal(workloadExecution(job,decision,{...receipt,jobId:'other'}).region,null);
});

test('a completed job without location telemetry is not assigned its recommended location', () => {
  const completed=workloadExecution({...job,status:'COMPLETED'},decision);
  assert.equal(completed.phase,'Completed');
  assert.equal(completed.region,null);
});

test('local execution location requires an actual reported start', () => {
  assert.equal(workloadExecution(job,decision,undefined,{jobId:job.id,region:'local',startedAtUtc:null}).region,null);
  const local=workloadExecution({...job,status:'RUNNING'},decision,undefined,
    {jobId:job.id,region:'local',startedAtUtc:'2026-10-25T10:00:00Z',executionMode:'LOCAL'});
  assert.equal(local.region,'local');
  assert.equal(local.mode,'LOCAL');
});
