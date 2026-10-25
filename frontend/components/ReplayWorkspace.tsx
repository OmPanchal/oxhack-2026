"use client";
import { useEffect, useId, useState } from "react";
import { BackendReplayWorkspace } from "./BackendReplayWorkspace";
import type { ReplayState, Strategy, TerminalData } from "@/lib/types";
import { replayScenarios } from "@/lib/preview";
import { nextFrame } from "@/lib/replay-view";
import { ReplayPanel } from "./ReplayPanel";
import { ExecutionMonitor } from "./ExecutionMonitor";
import { DecisionInspector } from "./DecisionInspector";
import { ReplayNarrative } from "./ReplayNarrative";
import { demoPolicies } from "@/lib/replay-narrative";
import { PolicyComparison, policyLabel } from "./PolicyComparison";

const views = ["Demo replay", "Local execution"] as const;

export function ReplayWorkspace({ preview, state, active, backendData, onRefresh = () => {} }: { preview: boolean; state: ReplayState; active: boolean; backendData?: TerminalData; onRefresh?: () => void }) {
  const [policy, setPolicy] = useState<Strategy>("OPTIMIZER_WITH_ML");
  const [jobId, setJobId] = useState("");
  const [scenarioId, setScenarioId] = useState("normal");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [view, setView] = useState(0);
  const viewId = useId();
  const scenario = replayScenarios.find(row => row.id === scenarioId)!;
  const frame = preview ? scenario.frames[index] : undefined;
  const job = frame?.jobs.find(row=>row.id===jobId) ?? frame?.jobs[0];
  const decision = frame?.decisions.filter(row=>row.jobId===job?.id).at(-1);
  const complete = index === scenario.frames.length - 1;
  useEffect(() => {
    if (!active || !preview || complete || view !== 0) setPlaying(false);
    if (!active || !preview || !playing || complete || view !== 0) return;
    const timer = window.setTimeout(() => setIndex(value => nextFrame(value, scenario.frames.length)), 2000 / speed);
    return () => window.clearTimeout(timer);
  }, [active, preview, playing, complete, index, speed, scenario, view]);
  function reset() { setPlaying(false); setIndex(0); }
  function selectScenario(id: string) { reset(); setScenarioId(id); }
  if (!preview) return backendData ? <BackendReplayWorkspace data={backendData} active={active} onRefresh={onRefresh} /> : <p className="empty">Loading replay state…</p>;
  return <div className="stack replay-simple replay-workspace guided-replay">
    <div className="tabs replay-view-tabs" role="tablist" aria-label="Replay and execution views" style={{padding: "10px 12px"}}>
      {views.map((label, i) => <button key={label} id={`${viewId}-tab-${i}`} role="tab" aria-selected={view === i} aria-controls={`${viewId}-panel-${i}`} tabIndex={view === i ? 0 : -1} onClick={() => setView(i)} onKeyDown={event => {
        const next = event.key === "ArrowRight" ? (i + 1) % views.length : event.key === "ArrowLeft" ? (i + views.length - 1) % views.length : event.key === "Home" ? 0 : event.key === "End" ? views.length - 1 : null;
        if (next !== null) { event.preventDefault(); setView(next); document.getElementById(`${viewId}-tab-${next}`)?.focus(); }
      }}>{label}</button>)}
    </div>
    <div id={`${viewId}-panel-0`} role="tabpanel" aria-labelledby={`${viewId}-tab-0`} hidden={view !== 0}>
      <div className="stack">
        <ReplayPanel state={frame ? { ...state, currentSlot: frame.slot } : state} scenarios={preview ? replayScenarios : []} scenarioId={preview ? scenarioId : undefined} index={index} playing={playing} speed={speed} onScenario={selectScenario} onReset={reset} onStep={() => setIndex(value => nextFrame(value, scenario.frames.length))} onPlay={() => setPlaying(value => !value)} onSpeed={setSpeed} />
        {frame && <>
          <p className="notice" role="status">SIMULATED storyboard · {frame.event}</p>
          <div className="replay-demo-story"><ReplayNarrative decisionDetails={<details className="replay-more"><summary>Full execution plan and decision history</summary>{policy === "OPTIMIZER_WITH_ML" ? <><DecisionInspector job={job} decision={decision} currentSlot={frame.slot} preview /><ol className="replay-history">{scenario.frames.slice(0,index+1).flatMap(row=>row.decisions).filter(row=>row.jobId===job?.id).map((row,i)=><li key={i}>Issued slot {row.decidedAtSlot} · {row.action}<p>{row.explanation}</p></li>)}</ol></> : <p className="panel-body">No issued decisions for this preview policy.</p>}</details>} preview job={policy === "OPTIMIZER_WITH_ML" ? job : undefined} decision={policy === "OPTIMIZER_WITH_ML" ? decision : undefined} market={frame.market} run={{strategy:policy,status:policy === "OPTIMIZER_WITH_ML" ? "ACTIVE" : "UNAVAILABLE",error:policy === "OPTIMIZER_WITH_ML" ? null : "No policy result supplied in this prepared preview.",decisions:scenario.frames.slice(0,index+1).flatMap(row=>row.decisions),forecasts:[],modelVersionsUsed:["illustrative-not-trained"],outcomes: frame.execution.completedAt?.match(/^Slot (\d+)$/) && job?.status === "COMPLETED" ? [{jobId:job.id,status:"COMPLETED",slot:Number(frame.execution.completedAt.match(/^Slot (\d+)$/)![1]),reason:"Prepared example"}] : []}}>
            <div className="guided-selectors"><label>Policy<select value={policy} onChange={event=>setPolicy(event.target.value as Strategy)}>{demoPolicies.map(row=><option key={row} value={row}>{policyLabel(row)}</option>)}</select></label><label>Workload<select value={job?.id ?? ""} onChange={event=>setJobId(event.target.value)}>{frame.jobs.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label></div>
          </ReplayNarrative>
          <section className="replay-advanced">
          <details className="replay-more"><summary>Capacity by pool</summary><p className="panel-body">Illustrative SIMULATED inputs, not observed AWS inventory.</p><div className="table-scroll"><table><thead><tr><th>Region</th><th>Hardware</th><th>Units</th></tr></thead><tbody>{frame.market.map((row,i)=><tr key={i}><td>{row.region}</td><td>{row.gpuType ?? row.resourceType}</td><td>{row.availableUnits ?? "Unknown"}</td></tr>)}</tbody></table></div></details>
          <details className="replay-more"><summary>Simulated shocks</summary><p className="panel-body">Preview shocks are prepared examples. Choose a scenario in replay settings to inspect its storyboard. No backend shock is injected.</p></details></section></div>
          <PolicyComparison />
        </>}

      </div>
    </div>
    <div id={`${viewId}-panel-1`} role="tabpanel" aria-labelledby={`${viewId}-tab-1`} hidden={view !== 1}><p className="notice">Choose Backend data to run genuine local Docker tasks and inspect their records. Preview telemetry below is illustrative.</p><ExecutionMonitor execution={frame?.execution} preview /></div>
  </div>;
}
