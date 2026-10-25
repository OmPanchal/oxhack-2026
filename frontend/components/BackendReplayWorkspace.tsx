"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { ReplayState, Strategy, TerminalData } from "@/lib/types";
import type { ReplayMetrics } from "@/lib/backend-types";
import { api } from "@/lib/api";
import { latestDecision } from "@/lib/decisions";
import { replayCapacityAtSlot, metricsMatchReplay } from "@/lib/replay-view";
import { DecisionInspector } from "./DecisionInspector";
import { BackendExecution } from "./BackendExecution";
import { ReplayNarrative } from "./ReplayNarrative";
import { demoPolicies } from "@/lib/replay-narrative";
import { PolicyComparison, policyLabel } from "./PolicyComparison";

const views = ["Demo replay", "Local execution"];
export function BackendReplayWorkspace({ data, active, onRefresh }: { data: TerminalData; active: boolean; onRefresh: () => void }) {
  const [state, setState] = useState(data.replay);
  const [metrics, setMetrics] = useState<ReplayMetrics | undefined>(data.replayMetrics);
  const [scenario, setScenario] = useState(data.replay.scenarioId ?? "capacity-pressure");
  const [seed, setSeed] = useState(String(data.replay.seed));
  const [view, setView] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const mutationCompletedAt = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<Strategy>("OPTIMIZER_WITH_ML");
  const [jobId, setJobId] = useState("");
  const [shockKind, setShockKind] = useState<"PRICE_SPIKE" | "CAPACITY_SHORTAGE" | "INTERRUPTION">("PRICE_SPIKE");
  const [magnitude, setMagnitude] = useState("2");
  const [region, setRegion] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const id = useId();
  useEffect(() => {
    if (!lock.current && (data.requestedAt ?? 0) >= mutationCompletedAt.current) {
      setState(data.replay); setMetrics(data.replayMetrics);
    }
  }, [data.replay, data.replayMetrics, data.requestedAt]);
  const done = state.status === "COMPLETED";
  async function run(operation: () => Promise<ReplayState>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null); setNotice(null);
    try {
      const result = await operation(); mutationCompletedAt.current = Date.now(); setState(result);
      setMetrics(undefined);
      try {
        const report = await api.metrics();
        if (metricsMatchReplay(report, result)) setMetrics(report);
        else setError('Replay changed while metrics were loading. Refresh to view a matching snapshot.');
      } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    } catch (error) { setPlaying(false); setError(error instanceof Error ? error.message : String(error)); }
    finally { lock.current = false; setBusy(false); onRefresh(); }
  }
  useEffect(() => {
    if (!active || view !== 0 || done || !state.initialized) setPlaying(false);
    if (!active || view !== 0 || !playing || done || !state.initialized || busy) return;
    const timer = setTimeout(() => { void run(() => api.stepReplay({ slots: 1 })); }, 2000 / speed);
    return () => clearTimeout(timer);
  }, [active, view, playing, done, state.initialized, state.currentSlot, busy, speed]);
  const strategyState = state.strategyStates?.find(row => row.strategy === strategy);
  const job = strategyState?.jobs.find(row => row.id === jobId) ?? strategyState?.jobs[0];
  const decision = latestDecision(strategyState?.decisions ?? [], job?.id ?? null, state.currentSlot);
  const regions = [...new Set(state.observedMarket?.map(row => row.region) ?? [])].sort();
  const capacity = replayCapacityAtSlot(state.observedMarket ?? [], state.currentSlot);
  const preset = ["capacity-pressure", "demo", "model-coverage"].includes(scenario) ? scenario : "custom";
  const validSeed = Number.isSafeInteger(Number(seed)) && seed.trim() !== "";
  const value = Number(magnitude);
  const validMagnitude = magnitude.trim() !== "" && Number.isFinite(value) && value >= 0
    && (shockKind !== "CAPACITY_SHORTAGE" || Number.isSafeInteger(value)) && (shockKind !== "INTERRUPTION" || value <= 1);
  return <div className="stack replay-workspace guided-replay">
    <div className="tabs replay-view-tabs" role="tablist" aria-label="Replay and execution views">{views.map((label, i) => <button key={label} id={`${id}-tab-${i}`} role="tab" aria-selected={view === i} aria-controls={`${id}-panel-${i}`} tabIndex={view === i ? 0 : -1} onClick={() => setView(i)} onKeyDown={event => {
      const next = event.key === "ArrowRight" ? (i + 1) % views.length : event.key === "ArrowLeft" ? (i + views.length - 1) % views.length : event.key === "Home" ? 0 : event.key === "End" ? views.length - 1 : null;
      if (next !== null) { event.preventDefault(); setView(next); document.getElementById(`${id}-tab-${next}`)?.focus(); }
    }}>{label}</button>)}</div>
    {error && <p className="notice error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div id={`${id}-panel-0`} role="tabpanel" aria-labelledby={`${id}-tab-0`} hidden={view !== 0}>
      <div className="stack">
        <section className="replay-control-panel"><div className="panel-heading"><h2>Demo replay</h2><span className="tag">{state.status} · SIMULATED</span></div>
          <div className="replay-introduction"><p>Follow a workload from its requirements to the scheduler’s decision, then inspect the outcome and compare policies. Replay does not launch Docker tasks.</p><p className="muted">{state.description ?? "Replay has its own clock and portfolio. Start replay when you are ready."}</p><p className="muted">{state.observedMarket?.some(row=>row.dataKind === "OBSERVED") ? "Observed historical prices · simulated workloads and capacity." : "SIMULATED replay · market provenance is shown with the recorded outcome."}</p></div>
          <div className="replay-toolbar">
            <div className="replay-toolbar-actions"><button disabled={busy || playing || !validSeed || !scenario.trim()} onClick={() => { setPlaying(false); void run(() => api.resetReplay({ seed: Number(seed), scenarioId: scenario.trim() })); }}>{state.initialized ? "Start again" : "Start replay"}</button><button className="primary-button" disabled={busy || !state.initialized || done} onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button></div>
            <span role="status">{busy ? "Updating…" : !state.initialized ? "Not started" : done ? "Complete" : playing ? "Playing" : "Paused"} · Replay slot {state.currentSlot}{state.endSlot == null ? "" : ` / ${state.endSlot}`}</span>
          </div>
          {state.endSlot != null && <progress aria-label="Replay progress" max={Math.max(1,state.endSlot)} value={state.currentSlot} />}
          <details className="replay-more"><summary>Replay settings and data sources</summary><div className="panel-body stack">
            <div className="guided-selectors"><label>Scenario<select value={preset} disabled={busy || playing} onChange={event => setScenario(event.target.value === "custom" ? "" : event.target.value)}><option value="capacity-pressure">Capacity pressure · simulated</option><option value="demo">Flat-price demo · simulated</option>{(data.modelStatus?.engineEnabled || scenario === "model-coverage") && <option value="model-coverage">All model regions · CPU/GPU · simulated</option>}<option value="custom">Custom scenario</option></select></label>{preset === "custom" && <label>Scenario ID<input value={scenario} disabled={busy || playing} onChange={event => setScenario(event.target.value)} /></label>}<label>Seed<input type="number" step="1" value={seed} aria-invalid={!validSeed} disabled={busy || playing} onChange={event => setSeed(event.target.value)} /></label><label>Playback speed<select value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={1}>1 slot / 2 seconds</option><option value={2}>1 slot / second</option><option value={4}>2 slots / second</option></select></label></div>
            <button disabled={busy || playing || !state.initialized || done} onClick={() => void run(() => api.stepReplay({ slots: 1 }))}>Single-step +1h</button>
            <p>Active scenario: {state.scenarioId ?? "Not initialized"} · seed {state.seed}. Settings apply only when you click Start replay / Start again.</p>
            <p>{state.description ?? "No scenario description supplied."}</p><p>Market sources: {[...new Set(state.observedMarket?.map(row=>`${row.source} (${row.dataKind})`) ?? [])].join(" · ") || "No observations supplied yet."}</p>
            <p>Execution and shocks are SIMULATED. Replay does not launch Docker or cloud workloads.</p>
          </div></details>
        </section>
        <div className="replay-demo-story"><ReplayNarrative decisionDetails={<details className="replay-more"><summary>Full execution plan and decision history</summary><DecisionInspector decision={decision} job={job} currentSlot={state.currentSlot} preview={false} /><ol className="replay-history">{strategyState?.decisions.filter(row=>row.jobId===job?.id).map((row,index)=><li key={index}><strong>Issued slot {row.decidedAtSlot} · {row.action}</strong><p>{row.explanation}</p></li>)}</ol>{!decision && <p className="panel-body">No issued decision history for this workload.</p>}</details>} run={strategyState} job={job} decision={decision} market={state.observedMarket}>
          <div className="guided-selectors"><label>Policy<select value={strategy} onChange={event => { setStrategy(event.target.value as Strategy); setJobId(""); }}>{demoPolicies.map(policy => <option value={policy} key={policy}>{policyLabel(policy)}</option>)}</select></label><label>Workload<select value={job?.id ?? ""} disabled={!strategyState?.jobs.length} onChange={event => setJobId(event.target.value)}>{!strategyState?.jobs.length && <option value="">No arrived workloads</option>}{strategyState?.jobs.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label></div>
        </ReplayNarrative>
        <section className="replay-advanced">

          <details className="replay-more"><summary>Capacity by pool</summary><div className="panel-body"><p className="muted">Scenario limits before reservations, not AWS inventory. Only observed replay slots are shown.</p>
            {capacity.length ? <div className="table-scroll"><table><thead><tr><th>Region</th><th>Resource</th><th>Total units</th><th>Provenance</th></tr></thead><tbody>{capacity.map(row => <tr key={`${row.region}-${row.resourceType}-${row.gpuType ?? ""}`}><td>{row.region}</td><td>{row.gpuType ?? row.resourceType}</td><td>{row.availableUnits ?? "Unknown"}</td><td>{row.dataKind} · {row.source} · slot {row.slot}</td></tr>)}</tbody></table></div> : <p className="empty">No processed capacity observations yet.</p>}
          </div></details>
          <details className="replay-more"><summary>Simulated shocks · {state.events?.length ?? 0}</summary>
            <form className="shock-form" onSubmit={event => { event.preventDefault(); if (!validMagnitude) return; setPlaying(false); void run(async () => { const accepted = await api.shock({ kind: shockKind, slot: state.currentSlot, magnitude: value, region: region || null, durationSlots: 1, dataKind: "SIMULATED" }); setNotice(`Scheduled ${accepted.kind} for slot ${accepted.slot}. Step to process it.`); return api.replayState(); }); }}>
              <label>Shock<select value={shockKind} disabled={busy || done || !state.initialized} onChange={event => { const kind = event.target.value as typeof shockKind; setShockKind(kind); setMagnitude(kind === "PRICE_SPIKE" ? "2" : "1"); }}><option value="PRICE_SPIKE">Price spike</option><option value="CAPACITY_SHORTAGE">Capacity shortage</option><option value="INTERRUPTION">Interruption</option></select></label>
              <label>Region<select value={region} disabled={busy || done || !state.initialized} onChange={event => setRegion(event.target.value)}><option value="">All regions</option>{regions.map(region => <option key={region}>{region}</option>)}</select></label>
              <label>{shockKind === "PRICE_SPIKE" ? "Price multiplier" : shockKind === "CAPACITY_SHORTAGE" ? "Units removed" : "Interruption probability"}<input type="number" min="0" max={shockKind === "INTERRUPTION" ? 1 : undefined} step={shockKind === "CAPACITY_SHORTAGE" ? 1 : "any"} value={magnitude} aria-invalid={!validMagnitude} disabled={busy || done || !state.initialized} onChange={event => setMagnitude(event.target.value)} /></label>
              <button disabled={busy || done || !state.initialized || !validMagnitude}>Inject simulated shock</button>
            </form>
            <ul className="panel-body">{state.events?.map(event => <li key={event.eventId}>Slot {event.slot} · {event.kind} · {event.slot < state.currentSlot ? "Processed" : "Scheduled"} · {event.region ?? "All regions"} · magnitude {event.magnitude}</li>)}</ul>
          </details>
          <div className="panel-footer">Backend simulated replay · seed {state.seed}. Historical replay does not launch cloud or Docker workloads.</div>
        </section></div>
        <PolicyComparison metrics={metrics && metricsMatchReplay(metrics,state) ? metrics : undefined} />
      </div>
    </div>
    <div id={`${id}-panel-1`} role="tabpanel" aria-labelledby={`${id}-tab-1`} hidden={view !== 1}><BackendExecution data={data} onRefresh={onRefresh} /></div>
  </div>;
}
