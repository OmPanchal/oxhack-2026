"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { ReplayState, Strategy, TerminalData } from "@/lib/types";
import type { ReplayMetrics } from "@/lib/backend-types";
import { api } from "@/lib/api";
import { latestDecision } from "@/lib/decisions";
import { replayCapacityAtSlot } from "@/lib/replay-view";
import { DecisionInspector } from "./DecisionInspector";
import { BackendExecution } from "./BackendExecution";
import { PolicyComparison, policyLabel } from "./PolicyComparison";

const views = ["Replay", "Policy comparison", "Execution"];
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
  const [error, setError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<Strategy>("OPTIMIZER_WITH_NAIVE_FORECAST");
  const [jobId, setJobId] = useState("");
  const [shockKind, setShockKind] = useState<"PRICE_SPIKE" | "CAPACITY_SHORTAGE" | "INTERRUPTION">("PRICE_SPIKE");
  const [magnitude, setMagnitude] = useState("2");
  const [region, setRegion] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const id = useId();
  useEffect(() => { if (!lock.current) { setState(data.replay); setMetrics(data.replayMetrics); } }, [data.replay, data.replayMetrics]);
  const done = state.status === "COMPLETED";
  async function run(operation: () => Promise<ReplayState>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null); setNotice(null);
    try {
      const result = await operation(); setState(result);
      setMetrics(undefined);
      try { setMetrics(await api.metrics()); } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
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
  const preset = ["capacity-pressure", "demo"].includes(scenario) ? scenario : "custom";
  const validSeed = Number.isSafeInteger(Number(seed)) && seed.trim() !== "";
  const value = Number(magnitude);
  const validMagnitude = magnitude.trim() !== "" && Number.isFinite(value) && value >= 0
    && (shockKind !== "CAPACITY_SHORTAGE" || Number.isSafeInteger(value)) && (shockKind !== "INTERRUPTION" || value <= 1);
  return <div className="stack">
    <div className="tabs replay-view-tabs" role="tablist" aria-label="Replay and execution views">{views.map((label, i) => <button key={label} id={`${id}-tab-${i}`} role="tab" aria-selected={view === i} aria-controls={`${id}-panel-${i}`} tabIndex={view === i ? 0 : -1} onClick={() => setView(i)} onKeyDown={event => {
      const next = event.key === "ArrowRight" ? (i + 1) % views.length : event.key === "ArrowLeft" ? (i + views.length - 1) % views.length : event.key === "Home" ? 0 : event.key === "End" ? views.length - 1 : null;
      if (next !== null) { event.preventDefault(); setView(next); document.getElementById(`${id}-tab-${next}`)?.focus(); }
    }}>{label}</button>)}</div>
    {error && <p className="notice error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div id={`${id}-panel-0`} role="tabpanel" aria-labelledby={`${id}-tab-0`} hidden={view !== 0}>
      <div className="stack">
        <section><div className="panel-heading"><h2>Replay controls</h2><span className="tag">Backend replay · SIMULATED</span></div>
          <div className="replay-toolbar"><label>Scenario<select value={preset} disabled={busy || playing} onChange={event => setScenario(event.target.value === "custom" ? "" : event.target.value)}><option value="capacity-pressure">Capacity pressure · simulated</option><option value="demo">Flat-price demo · simulated</option><option value="custom">Custom scenario</option></select></label>{preset === "custom" && <label>Scenario ID<input value={scenario} disabled={busy || playing} onChange={event => setScenario(event.target.value)} /></label>}<label>Seed<input type="number" step="1" value={seed} aria-invalid={!validSeed} disabled={busy || playing} onChange={event => setSeed(event.target.value)} /></label>
            <div className="replay-toolbar-actions"><button disabled={busy || !validSeed || !scenario.trim()} onClick={() => { setPlaying(false); void run(() => api.resetReplay({ seed: Number(seed), scenarioId: scenario.trim() })); }}>Reset</button><button disabled={busy || playing || !state.initialized || done} onClick={() => void run(() => api.stepReplay({ slots: 1 }))}>Step +1h</button><button className="primary-button" disabled={busy || !state.initialized || done} onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button></div>
            <span className="muted" role="status">{busy ? "Updating…" : done ? "Complete" : playing ? "Playing" : "Paused"} · Next slot {state.currentSlot}{state.endSlot == null ? "" : ` / ${state.endSlot}`}</span>
          </div>
          <details className="replay-playback-options"><summary>Playback speed</summary><label>Advance slots<select value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={1}>1 slot / 2 seconds</option><option value={2}>1 slot / second</option><option value={4}>2 slots / second</option></select></label></details>
          <p className="replay-description">{state.description ?? "Choose a scenario and reset to begin. Replay has its own clock and portfolio."}</p>
        </section>
        {!state.initialized ? <section><p className="empty">No replay initialized. Reset to start a reproducible simulation.</p></section> : <section className="replay-story">
          <div className="replay-story-block"><div className="replay-story-heading"><h2>Replay progress</h2><span className="tag">{state.status}</span></div><p>{state.currentSlot === 0 ? "No slots processed yet." : `Processed through slot ${state.currentSlot - 1}.`}{done ? " Replay ended; unfinished and unavailable strategies remain disclosed." : ` Slot ${state.currentSlot} is next.`}</p>
            <div className="control-row"><label>Policy <select value={strategy} onChange={event => { setStrategy(event.target.value as Strategy); setJobId(""); }}>{state.strategies.map(policy => <option value={policy} key={policy}>{policyLabel(policy)}</option>)}</select></label>{strategyState?.jobs.length ? <label>Workload <select value={job?.id ?? ""} onChange={event => setJobId(event.target.value)}>{strategyState.jobs.map(job => <option key={job.id} value={job.id}>{job.name}</option>)}</select></label> : null}</div>
          </div>
          <div className="replay-story-block"><div className="replay-story-heading"><h2>Capacity by pool</h2><span className="tag">SIMULATED{state.currentSlot > 0 ? ` · slot ${state.currentSlot - 1}` : ""}</span></div>
            <p className="muted">Scenario limits before workload reservations, not AWS inventory. Future capacity is not shown.</p>
            {capacity.length ? <div className="table-scroll"><table><thead><tr><th scope="col">Region</th><th scope="col">Resource</th><th scope="col">Total units</th></tr></thead><tbody>{capacity.map(row => <tr key={`${row.region}-${row.resourceType}-${row.gpuType ?? ""}`}><td>{row.region}</td><td>{row.gpuType ?? row.resourceType}</td><td>{row.availableUnits ?? "Unknown"}</td></tr>)}</tbody></table></div> : <p className="empty">Step once to observe the first capacity limits.</p>}
          </div>
          <div className="replay-story-block"><h2>Scheduler response</h2><p>{strategyState?.status !== "ACTIVE" ? strategyState?.error ?? "Policy state is unavailable." : decision ? `${decision.action}: ${decision.explanation}` : "No decision has been produced for this workload yet."}</p></div>
          <div className="replay-story-block"><h2>Workload outcome</h2><p>{job ? `${job.name} · ${job.status}` : "No arrived workloads for this policy."}</p><p className="muted">{strategyState?.outcomes.filter(row => row.jobId === job?.id).map(row => `Slot ${row.slot}: ${row.reason}`).join(" · ") || "No terminal outcome recorded."}</p></div>
          <details className="replay-more"><summary>Full execution plan</summary><DecisionInspector decision={decision} job={job} currentSlot={state.currentSlot} preview={false} /></details>
          <details className="replay-more"><summary>Simulated shocks · {state.events?.length ?? 0}</summary>
            <form className="shock-form" onSubmit={event => { event.preventDefault(); if (!validMagnitude) return; setPlaying(false); void run(async () => { const accepted = await api.shock({ kind: shockKind, slot: state.currentSlot, magnitude: value, region: region || null, durationSlots: 1, dataKind: "SIMULATED" }); setNotice(`Scheduled ${accepted.kind} for slot ${accepted.slot}. Step to process it.`); return api.replayState(); }); }}>
              <label>Shock<select value={shockKind} disabled={busy || done} onChange={event => { const kind = event.target.value as typeof shockKind; setShockKind(kind); setMagnitude(kind === "PRICE_SPIKE" ? "2" : "1"); }}><option value="PRICE_SPIKE">Price spike</option><option value="CAPACITY_SHORTAGE">Capacity shortage</option><option value="INTERRUPTION">Interruption</option></select></label>
              <label>Region<select value={region} disabled={busy || done} onChange={event => setRegion(event.target.value)}><option value="">All regions</option>{regions.map(region => <option key={region}>{region}</option>)}</select></label>
              <label>{shockKind === "PRICE_SPIKE" ? "Price multiplier" : shockKind === "CAPACITY_SHORTAGE" ? "Units removed" : "Interruption probability"}<input type="number" min="0" max={shockKind === "INTERRUPTION" ? 1 : undefined} step={shockKind === "CAPACITY_SHORTAGE" ? 1 : "any"} value={magnitude} aria-invalid={!validMagnitude} disabled={busy || done} onChange={event => setMagnitude(event.target.value)} /></label>
              <button disabled={busy || done || !validMagnitude}>Inject simulated shock</button>
            </form>
            <ul className="panel-body">{state.events?.map(event => <li key={event.eventId}>Slot {event.slot} · {event.kind} · {event.slot < state.currentSlot ? "Processed" : "Scheduled"} · {event.region ?? "All regions"} · magnitude {event.magnitude}</li>)}</ul>
          </details>
          <div className="panel-footer">Backend simulated replay · seed {state.seed}. Historical replay does not launch cloud or Docker workloads.</div>
        </section>}
      </div>
    </div>
    <div id={`${id}-panel-1`} role="tabpanel" aria-labelledby={`${id}-tab-1`} hidden={view !== 1}><PolicyComparison metrics={metrics} /></div>
    <div id={`${id}-panel-2`} role="tabpanel" aria-labelledby={`${id}-tab-2`} hidden={view !== 2}><BackendExecution data={data} onRefresh={onRefresh} /></div>
  </div>;
}
