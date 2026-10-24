"use client";
import { useEffect, useId, useState } from "react";
import type { ReplayState } from "@/lib/types";
import { replayScenarios } from "@/lib/preview";
import { nextFrame } from "@/lib/replay-view";
import { ReplayPanel } from "./ReplayPanel";
import { ExecutionMonitor } from "./ExecutionMonitor";
import { DecisionInspector } from "./DecisionInspector";
import { PolicyComparison } from "./PolicyComparison";

const views = ["Replay", "Policy comparison", "Execution"] as const;

export function ReplayWorkspace({ preview, state, active }: { preview: boolean; state: ReplayState; active: boolean }) {
  const [scenarioId, setScenarioId] = useState("normal");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [view, setView] = useState(0);
  const viewId = useId();
  const scenario = replayScenarios.find(row => row.id === scenarioId)!;
  const frame = preview ? scenario.frames[index] : undefined;
  const decision = frame?.decisions[0];
  const complete = index === scenario.frames.length - 1;
  useEffect(() => {
    if (!active || !preview || complete || view !== 0) setPlaying(false);
    if (!active || !preview || !playing || complete || view !== 0) return;
    const timer = window.setTimeout(() => setIndex(value => nextFrame(value, scenario.frames.length)), 2000 / speed);
    return () => window.clearTimeout(timer);
  }, [active, preview, playing, complete, index, speed, scenario, view]);
  function reset() { setPlaying(false); setIndex(0); }
  function selectScenario(id: string) { reset(); setScenarioId(id); }
  return <div className="stack replay-simple">
    <div className="tabs replay-view-tabs" role="tablist" aria-label="Replay and execution views">
      {views.map((label, i) => <button key={label} id={`${viewId}-tab-${i}`} role="tab" aria-selected={view === i} aria-controls={`${viewId}-panel-${i}`} tabIndex={view === i ? 0 : -1} onClick={() => setView(i)} onKeyDown={event => {
        const next = event.key === "ArrowRight" ? (i + 1) % views.length : event.key === "ArrowLeft" ? (i + views.length - 1) % views.length : event.key === "Home" ? 0 : event.key === "End" ? views.length - 1 : null;
        if (next !== null) { event.preventDefault(); setView(next); document.getElementById(`${viewId}-tab-${next}`)?.focus(); }
      }}>{label}</button>)}
    </div>
    <div id={`${viewId}-panel-0`} role="tabpanel" aria-labelledby={`${viewId}-tab-0`} hidden={view !== 0}>
      <div className="stack">
        <ReplayPanel state={frame ? { ...state, currentSlot: frame.slot } : state} scenarios={preview ? replayScenarios : []} scenarioId={preview ? scenarioId : undefined} index={index} playing={playing} speed={speed} onScenario={selectScenario} onReset={reset} onStep={() => setIndex(value => nextFrame(value, scenario.frames.length))} onPlay={() => setPlaying(value => !value)} onSpeed={setSpeed} />
        {frame ? <section className="replay-story" aria-label="Replay event, response and outcome">
          <div className="replay-story-block"><div className="replay-story-heading"><h2>Current event</h2><span className="tag">Slot {frame.slot} · Simulated</span></div><p role="status">{frame.event}</p></div>
          <div className="replay-story-block"><div className="replay-story-heading"><h2>Scheduler response</h2><span className="muted">{decision?.action ?? "No new decision"}</span></div>
            <p>{decision?.explanation ?? "No further scheduling decision is supplied for this event."}</p>
            {decision && <dl className="replay-plan-summary"><div><dt>Region</dt><dd>{decision.region ?? "Unavailable"}</dd></div><div><dt>Planned window</dt><dd>{decision.plannedStartSlot != null && decision.plannedEndSlot != null ? `Slots ${decision.plannedStartSlot}–${decision.plannedEndSlot}` : "Unavailable"}</dd></div><div><dt>Projected cost</dt><dd>{decision.projectedCostUsd === null ? "Unavailable" : `$${decision.projectedCostUsd.toFixed(2)}`}</dd></div></dl>}
          </div>
          <div className="replay-story-block"><div className="replay-story-heading"><h2>Workload outcome</h2><span className={frame.execution.status === "FAILED" ? "attention" : "muted"}>{frame.execution.status}</span></div>
            <p>{frame.jobs[0].name} <span className="muted">· {frame.jobs[0].id}</span></p>
            <p className={frame.execution.failureReason ? "attention" : "muted"}>{frame.execution.failureReason ?? (frame.execution.status === "COMPLETED" ? `Example completion at ${frame.execution.completedAt}.` : frame.execution.status === "RUNNING" ? "Example task is running; completion is pending." : "Execution has not started in this example.")}</p>
          </div>
          <details className="replay-more"><summary>Full execution plan</summary><DecisionInspector job={frame.jobs[0]} decision={decision} currentSlot={frame.slot} preview /></details>
          <details className="replay-more"><summary>Event history · {index + 1} events</summary><ol className="replay-history">{scenario.frames.slice(0, index + 1).map((row, i) => <li key={row.slot}><button className="text-button" aria-current={i === index ? "step" : undefined} onClick={() => { setPlaying(false); setIndex(i); }}>Slot {row.slot}</button><p>{row.event}</p></li>)}</ol></details>
          <div className="panel-footer">Prepared examples only. No simulator, optimizer or Docker task runs.</div>
        </section> : <section><div className="empty"><h3>No replay results yet</h3><p>Events, scheduling responses and outcomes will appear when replay is connected.</p></div></section>}
      </div>
    </div>
    <div id={`${viewId}-panel-1`} role="tabpanel" aria-labelledby={`${viewId}-tab-1`} hidden={view !== 1}><PolicyComparison /></div>
    <div id={`${viewId}-panel-2`} role="tabpanel" aria-labelledby={`${viewId}-tab-2`} hidden={view !== 2}><ExecutionMonitor execution={frame?.execution} preview={preview} /></div>
  </div>;
}
