import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import ts from 'typescript';
import {renderToStaticMarkup} from 'react-dom/server';
import React from 'react';
const root=path.resolve(import.meta.dirname,'..');
const require=createRequire(import.meta.url), cache=new Map();
function load(file) {
  if(cache.has(file)) return cache.get(file).exports;
  const module={exports:{}}; cache.set(file,module);
  const js=ts.transpileModule(readFileSync(file,'utf8'),{fileName:file,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  new Function('require','module','exports',js)(name=>{
    if(name==='@/lib/api') return {api:new Proxy({}, {get(){return ()=>{throw Error('UI rendering must not mutate replay');};}})};
    if(!name.startsWith('.')&&!name.startsWith('@/')) return require(name);
    const base=name.startsWith('@/')?path.join(root,name.slice(2)):path.resolve(path.dirname(file),name);
    const resolved=['','.ts','.tsx','.json'].map(ext=>base+ext).find(existsSync);
    return resolved.endsWith('.json')?JSON.parse(readFileSync(resolved,'utf8')):load(resolved);
  },module,module.exports);
  return module.exports;
}
const helpers=load(path.join(root,'lib/replay-narrative.ts'));
const {ReplayNarrative}=load(path.join(root,'components/ReplayNarrative.tsx'));
const {PolicyComparison}=load(path.join(root,'components/PolicyComparison.tsx'));
const {BackendReplayWorkspace}=load(path.join(root,'components/BackendReplayWorkspace.tsx'));
const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
const job={id:'j',name:'Training',arrivalSlot:5,deadlineSlot:11,durationSlots:2,resourceType:'GPU',resourceUnits:1,gpuType:'T4',allowedRegions:['eu-north-1'],status:'COMPLETED'};
const wait={jobId:'j',decidedAtSlot:5,action:'WAIT',plannedStartSlot:7};
const decision={jobId:'j',decidedAtSlot:7,action:'RUN',region:'eu-north-1',plannedStartSlot:7,plannedEndSlot:9,projectedCostUsd:0,explanation:'Backend explanation'};
const run={strategy:'OPTIMIZER_WITH_ML',status:'ACTIVE',jobs:[job],decisions:[wait,decision],forecasts:[],modelVersionsUsed:['persistence-v1:fallback-model-not-available'],outcomes:[{jobId:'j',status:'COMPLETED',slot:9,reason:'Recorded'}]};
test('actual rendered narrative orders workload, decision, outcome then inline comparison',()=>{
 const html=render(ReplayNarrative,{run,job,decision})+render(PolicyComparison,{});
 let previous=-1;
 for(const heading of helpers.narrativeOrder){const index=html.indexOf(heading);assert.ok(index>previous);previous=index;}
 assert.match(html,/6h from arrival/);assert.match(html,/2h after arrival/);assert.match(html,/4h after arrival/);assert.match(html,/Earlier, the backend chose WAIT/);assert.match(html,/\$0.0000/);
 assert.match(html,/Persistence fallback/);assert.doesNotMatch(html,/Genuine saved-model ML/);
});
test('all incomplete and unavailable states remain explicit; missing completion is never inferred from a plan',()=>{
 for(const status of ['PENDING','RUNNING','FAILED','INFEASIBLE']){const html=render(ReplayNarrative,{run:{...run,outcomes:[]},job:{...job,status},decision});assert.match(html,new RegExp(status));assert.match(html,/Not recorded/);}
 assert.match(render(ReplayNarrative,{run:{...run,outcomes:[]},job,decision}),/no completion time was supplied/);
 assert.match(render(ReplayNarrative,{run:{...run,status:'UNAVAILABLE',error:'No model'},job}),/Policy result unavailable/);
 assert.match(render(ReplayNarrative,{}),/No arrived workload/);
});
test('genuine, fallback, mixed, unknown and unavailable provenance cannot be conflated',()=>{
 assert.match(helpers.forecastProvenance(['lightgbm-price-l1-v1-gpu-123']).label,/Genuine/);
 assert.match(helpers.forecastProvenance(['persistence-v1:fallback-model-not-available']).label,/Persistence fallback/);
 assert.match(helpers.forecastProvenance(['lightgbm-delta-v1-abc','persistence-v1']).label,/Mixed/);
 assert.match(helpers.forecastProvenance(['illustrative-not-trained']).label,/unverified/);
 assert.match(helpers.forecastProvenance([]).label,/No forecast/);
 assert.match(helpers.forecastProvenance(['lightgbm-delta-v1-a'],'UNAVAILABLE').label,/unavailable/);
 assert.match(helpers.forecastProvenance(['lightgbm-delta-v1-a'],'ACTIVE',true).label,/no trained inference/);
});
test('comparison hides only standalone persistence, retains fallback and all backend counts',()=>{
 const totals={totalSpendUsd:1.2345,completedJobs:2,missedDeadlines:3,failedJobs:4,infeasibleJobs:5,unfinishedJobs:6};
 const metrics={strategies:[{strategy:'OPTIMIZER_WITH_ML',status:'ACTIVE',modelVersions:run.modelVersionsUsed,totals},{strategy:'OPTIMIZER_WITH_NAIVE_FORECAST',status:'ACTIVE',modelVersions:['standalone-hidden'],totals}],comparisons:[{explanation:'PAIRWISE-SAVINGS-SHOULD-NOT-RENDER'}]};
 const html=render(PolicyComparison,{metrics});
 assert.doesNotMatch(html,/standalone-hidden|PAIRWISE|Optimizer \/ persistence/);assert.match(html,/Persistence fallback/);assert.match(html,/1.2345/);
 for(const count of [2,3,4,5,6])assert.match(html,new RegExp('>'+count+'<'));
 assert.match(render(PolicyComparison,{metrics:{strategies:[{...metrics.strategies[0],status:'UNAVAILABLE'}]}}),/—/);
});
test('backend page defaults to ML, preserves retrospective disclosure and collapses advanced controls',()=>{
 const description='Retrospectively selected success example: not a representative benchmark.';
 const replay={initialized:true,status:'RUNNING',currentSlot:9,endSlot:12,scenarioId:'custom',seed:1,description,observedMarket:[],strategyStates:[run],strategies:helpers.demoPolicies,events:[]};
 const html=render(BackendReplayWorkspace,{data:{replay,jobs:[],executions:[]},active:false,onRefresh(){}});
 assert.match(html,/Demo replay/);assert.match(html,/Local execution/);assert.match(html,/<option value="OPTIMIZER_WITH_ML" selected="">Optimizer \/ ML/);
 assert.match(html,/Retrospectively selected success example/);
 assert.doesNotMatch(html,/<details[^>]* open/);
 for(const label of ['Replay settings and data sources','Full execution plan and decision history','Capacity by pool','Simulated shocks'])assert.ok(html.includes(label));
 assert.doesNotMatch(html,/Optimizer \/ persistence/);
});
test('relative times preserve zero, arrival offsets and missing values',()=>{
 assert.equal(helpers.relativeToArrival(5,job),'At arrival');assert.equal(helpers.relativeToArrival(null,job),'Not reported');
 assert.equal(helpers.relativeToArrival(0,{...job,arrivalSlot:0}),'At arrival');
 assert.equal(helpers.priorWait([wait,decision],decision),wait);
});
test('local execution still renders its genuine controls, Docker identity, logs and exit code',()=>{
 const {BackendExecution}=load(path.join(root,'components/BackendExecution.tsx'));
 const html=render(BackendExecution,{data:{jobs:[{...job,status:'PENDING',dockerTaskId:'cpu-demo'}],executions:[{id:'e',jobId:'j',taskId:'cpu-demo',status:'COMPLETED',executionMode:'LOCAL',requestedAtUtc:'2026-01-01T00:00:00Z',startedAtUtc:'2026-01-01T00:00:00Z',completedAtUtc:'2026-01-01T00:01:00Z',exitCode:0,stdout:'recorded output',stderr:'recorded stderr',containerName:'real-local-name',containerId:'container-id',dockerEndpoint:'unix:///docker.sock'}]},onRefresh(){}});
 for(const label of ['Run local task','Execution record','real-local-name','container-id','unix:///docker.sock','recorded output','recorded stderr','Exit code'])assert.ok(html.includes(label));
 assert.match(html,/>0</);assert.match(html,/LOCAL/);
});
test('uninitialized replay shows a start action; stale metrics never appear as current',()=>{
 const replay={initialized:false,status:'NOT_INITIALIZED',currentSlot:0,seed:1,scenarioId:'demo',observedMarket:[],strategyStates:[],strategies:helpers.demoPolicies,events:[]};
 const html=render(BackendReplayWorkspace,{data:{replay,jobs:[],replayMetrics:{scenarioId:'other',asOfSlot:20,strategies:[{strategy:'FIFO',status:'ACTIVE',totals:{totalSpendUsd:987.6543}}]}},active:false,onRefresh(){}});
 assert.match(html,/Start replay/);assert.match(html,/No comparison results yet/);assert.doesNotMatch(html,/987.6543/);
});
test('reference layout nests decision details and keeps capacity before comparison',()=>{
 const replay={initialized:true,status:'RUNNING',currentSlot:9,endSlot:12,scenarioId:'demo',seed:1,description:'Recorded scenario description',observedMarket:[],strategyStates:[run],strategies:helpers.demoPolicies,events:[]};
 const html=render(BackendReplayWorkspace,{data:{replay,jobs:[],executions:[]},active:false,onRefresh(){}});
 const decisionIndex=html.indexOf('id="narrative-decision"');
 const historyIndex=html.indexOf('Full execution plan and decision history');
 const outcomeIndex=html.indexOf('id="narrative-outcome"');
 const capacityIndex=html.indexOf('Capacity by pool');
 const comparisonIndex=html.indexOf('class="replay-comparison"');
 assert.ok(decisionIndex<historyIndex && historyIndex<outcomeIndex);
 assert.ok(outcomeIndex<capacityIndex && capacityIndex<comparisonIndex);
 assert.doesNotMatch(html,/>[1234]\. (Workload|Decision|Outcome|Policy comparison)</);
 assert.match(html,/Model versions|No forecast provenance|Persistence fallback/);
});
test('each narrative section renders a separate card and retains passed decision details',()=>{
 const html=render(ReplayNarrative,{run,job,decision,decisionDetails:React.createElement('details',null,React.createElement('summary',null,'Issued decision details'))});
 assert.equal((html.match(/class="replay-narrative-card"/g) ?? []).length,3);
 for(const name of ['workload','decision','outcome'])assert.ok(html.includes(`class="replay-narrative-card" aria-labelledby="narrative-${name}"`));
 assert.ok(html.indexOf('Issued decision details')>html.indexOf('id="narrative-decision"'));
 assert.ok(html.indexOf('Issued decision details')<html.indexOf('id="narrative-outcome"'));
});
