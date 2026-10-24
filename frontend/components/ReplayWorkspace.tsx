"use client";
import { useEffect, useId, useState } from "react";
import type { ReplayState } from "@/lib/types";
import { replayScenarios } from "@/lib/preview";
import { nextFrame } from "@/lib/replay-view";
import { ReplayPanel } from "./ReplayPanel";
import { ExecutionMonitor } from "./ExecutionMonitor";
import { DecisionInspector } from "./DecisionInspector";
import { PolicyComparison } from "./PolicyComparison";

const detailTabs = ["Execution plan", "Task logs"] as const;

export function ReplayWorkspace({ preview, state, active }: { preview: boolean; state: ReplayState; active: boolean }) {
  const [scenarioId, setScenarioId] = useState("normal");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [detail, setDetail] = useState(0);
  const detailId = useId();
  const scenario = replayScenarios.find(row => row.id === scenarioId)!;
  const frame = preview ? scenario.frames[index] : undefined;
  const complete = index === scenario.frames.length - 1;
  useEffect(() => {
    if (!active || !preview || complete) setPlaying(false);
    if (!active || !preview || !playing || complete) return;
    const timer = window.setTimeout(() => setIndex(value => nextFrame(value, scenario.frames.length)), 2000 / speed);
    return () => window.clearTimeout(timer);
  }, [active, preview, playing, complete, index, speed, scenario]);
  function reset() { setPlaying(false); setIndex(0); }
  function selectScenario(id: string) { reset(); setScenarioId(id); }
  return <div className="stack">
    <div className="replay-workspace">
      <ReplayPanel state={frame ? { ...state, currentSlot: frame.slot } : state} scenarios={preview ? replayScenarios : []} scenarioId={preview ? scenarioId : undefined} index={index} playing={playing} speed={speed} onScenario={selectScenario} onReset={reset} onStep={() => setIndex(value => nextFrame(value, scenario.frames.length))} onPlay={() => setPlaying(value => !value)} onSpeed={setSpeed} />
      <div className="replay-event-strip" aria-label="Scenario timeline">
        {frame ? <>
          <ol className="replay-event-rail">{scenario.frames.map((row, i) => <li key={row.slot}>
            <button disabled={i > index} aria-current={i === index ? "step" : undefined} onClick={() => { setPlaying(false); setIndex(i); }}><span>Slot {row.slot}</span><span>{i === index ? "Current" : i < index ? "Review event" : "Upcoming"}</span></button>
          </li>)}</ol>
          <p className="replay-current-event" role="status">{frame.event}</p>
        </> : <div className="empty"><h3>No replay events supplied</h3><p>Event history will appear here when replay is connected.</p></div>}
      </div>
      <dl className="replay-state-strip" aria-label="Current replay state">
        <div><dt>{preview ? "Scenario slot" : "Current slot"}</dt><dd>{frame?.slot ?? state.currentSlot}<small>1h slots</small></dd></div>
        <div><dt>Workload</dt><dd>{frame?.jobs[0].name ?? "Unavailable"}<small>{frame ? `${frame.jobs[0].id} · ${frame.jobs[0].status}` : "No workload state supplied"}</small></dd></div>
        <div><dt>Regional quote</dt><dd>{frame?.market[0] ? `$${frame.market[0].priceUsdPerUnitHour.toFixed(2)}` : "—"}<small>{frame?.market[0] ? `${frame.market[0].region} · ${frame.market[0].gpuType} · USD / GPU-hour` : "No quote at this event"}</small></dd></div>
        <div><dt>Reported capacity</dt><dd>{frame?.market[0]?.availableUnits ?? "—"}<small>{frame?.market[0] ? "GPUs · simulated snapshot" : "Unavailable"}</small></dd></div>
      </dl>
      <div className="replay-detail-tabs tabs" role="tablist" aria-label="Replay workload details">
        {detailTabs.map((label, i) => <button key={label} id={`${detailId}-tab-${i}`} role="tab" aria-selected={detail === i} aria-controls={`${detailId}-panel-${i}`} tabIndex={detail === i ? 0 : -1} onClick={() => setDetail(i)} onKeyDown={event => {
          const next = event.key === "ArrowRight" ? (i + 1) % detailTabs.length : event.key === "ArrowLeft" ? (i + detailTabs.length - 1) % detailTabs.length : event.key === "Home" ? 0 : event.key === "End" ? detailTabs.length - 1 : null;
          if (next !== null) { event.preventDefault(); setDetail(next); document.getElementById(`${detailId}-tab-${next}`)?.focus(); }
        }}>{label}</button>)}
      </div>
      <div id={`${detailId}-panel-0`} role="tabpanel" aria-labelledby={`${detailId}-tab-0`} hidden={detail !== 0}>
        <DecisionInspector job={frame?.jobs[0]} decision={frame?.decisions[0]} currentSlot={frame?.slot ?? state.currentSlot} preview={preview} />
      </div>
      <div id={`${detailId}-panel-1`} role="tabpanel" aria-labelledby={`${detailId}-tab-1`} hidden={detail !== 1}>
        <ExecutionMonitor execution={frame?.execution} preview={preview} />
      </div>
      <div className="panel-footer">{preview ? "Hand-authored scenario, plans and logs. No simulator, optimizer or Docker task runs." : "Replay state is supplied by FastAPI. Event and execution telemetry are not connected yet."}</div>
    </div>
    <PolicyComparison />
  </div>;
}
