"use client";
import { useEffect, useId, useRef, useState } from "react";
import type { ReplayState, Strategy, TerminalData } from "@/lib/types";
import type { ReplayMetrics } from "@/lib/backend-types";
import { api } from "@/lib/api";
import { latestDecision } from "@/lib/decisions";
import { replayCapacityAtSlot, replayProgress } from "@/lib/replay-view";
import { DecisionInspector } from "./DecisionInspector";
import { BackendExecution } from "./BackendExecution";
import { PolicyComparison } from "./PolicyComparison";
import { policyPresentation, visiblePolicies } from "@/lib/policy-labels";

const views = ["Demo replay", "Local execution"];
const scenarioNames: Record<string, string> = {
  "capacity-pressure": "Capacity pressure · simulated",
  demo: "Flat-price demo · simulated",
  "historical-t4-a10g": "Historical T4/A10G · observed prices, simulated capacity",
};
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
  const [strategy, setStrategy] = useState<Strategy>("OPTIMIZER_WITH_ML");
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
  function usageFor(policy: Strategy) {
    const run = state.strategyStates?.find(row => row.strategy === policy);
    return policyPresentation(policy, [...(run?.modelVersionsUsed ?? []), ...(run?.forecasts.map(row => row.modelVersion) ?? [])], run?.status);
  }
  const selectedUsage = usageFor(strategy);
  const job = strategyState?.jobs.find(row => row.id === jobId) ?? strategyState?.jobs[0];
  const decision = latestDecision(strategyState?.decisions ?? [], job?.id ?? null, state.currentSlot);
  const jobDecisions = (strategyState?.decisions ?? []).filter(row => row.jobId === job?.id && row.decidedAtSlot <= state.currentSlot);
  const waitingDecision = latestDecision(jobDecisions.filter(row => row.action === "WAIT"), job?.id ?? null, state.currentSlot);
  const completedOutcome = strategyState?.outcomes.find(row => row.jobId === job?.id && row.status === "COMPLETED");
  const selectedExample = state.description?.startsWith("SELECTED SUCCESS EXAMPLE:");
  const decisionText = !decision ? "No decision has been produced for this workload yet."
    : decision.action === "INFEASIBLE" ? decision.explanation
    : `${decision.action === "WAIT" ? "Wait before running" : decision.action === "ROUTE" ? "Route the workload" : decision.action === "FALLBACK" ? "Use the fallback allocation" : "Run the workload"}${decision.region ? ` in ${decision.region}` : ""}.`;
  const regions = [...new Set(state.observedMarket?.map(row => row.region) ?? [])].sort();
  const capacity = replayCapacityAtSlot(state.observedMarket ?? [], state.currentSlot);
  const catalog = data.replayScenarios ?? [
    { id: "capacity-pressure", available: true, description: "Capacity pressure · simulated", reason: null },
    { id: "demo", available: true, description: "Flat-price demo · simulated", reason: null },
  ];
  const preset = catalog.some(row => row.id === scenario) ? scenario : "custom";
  const historicalUnavailable = catalog.find(row => row.id === "historical-t4-a10g" && !row.available);
  const progress = replayProgress(state.currentSlot, state.startSlot, state.endSlot);
  const scenarioName = (id: string) => scenarioNames[id] ?? id;
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
        <section><div className="panel-heading"><h2>Demo replay</h2><span className="tag">{state.status} · SIMULATED</span></div>
          <p className="panel-body">Follow a workload from its requirements to the scheduler's decision, then inspect the outcome and compare policies. Replay does not launch Docker tasks.</p>
          {selectedExample && <p className="replay-description">Selected historical success example · legacy waiting policy. Chosen after evaluation because ML won; broader results include ties and losses.</p>}
          {state.provenance && <p className="replay-description">{state.provenance.priceDataKind === "OBSERVED_WITH_SIMULATED_SHOCKS" ? "Observed base prices with simulated price shocks" : "Observed historical prices"} · simulated workloads and capacity.</p>}
          <div className="replay-toolbar"><div className="replay-toolbar-actions"><button disabled={busy || !validSeed || !scenario.trim()} onClick={() => { setPlaying(false); void run(() => api.resetReplay({ seed: Number(seed), scenarioId: scenario.trim() })); }}>{state.initialized ? "Start again" : "Start replay"}</button><button className="primary-button" disabled={busy || !state.initialized || done} onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button></div><span className="muted" role="status">{busy ? "Updating…" : done ? "Complete" : playing ? "Playing" : "Paused"} · {progress.elapsed}{progress.total == null ? "" : ` / ${progress.total}`} hours processed</span></div>
          <details className="replay-more"><summary>Replay settings and data sources</summary>
          <div className="replay-toolbar"><label>Scenario<select value={preset} disabled={busy || playing} onChange={event => setScenario(event.target.value === "custom" ? "" : event.target.value)}>{catalog.map(row => <option key={row.id} value={row.id} disabled={!row.available}>{scenarioName(row.id)}{row.available ? "" : " · awaiting price data"}</option>)}<option value="custom">Custom scenario</option></select></label>{preset === "custom" && <label>Scenario ID<input value={scenario} disabled={busy || playing} onChange={event => setScenario(event.target.value)} /></label>}<label>Seed<input type="number" step="1" value={seed} aria-invalid={!validSeed} disabled={busy || playing} onChange={event => setSeed(event.target.value)} /></label>
            <div className="replay-toolbar-actions"><button disabled={busy || !validSeed || !scenario.trim()} onClick={() => { setPlaying(false); void run(() => api.resetReplay({ seed: Number(seed), scenarioId: scenario.trim() })); }}>Reset</button><button disabled={busy || playing || !state.initialized || done} onClick={() => void run(() => api.stepReplay({ slots: 1 }))}>Step +1h</button><button className="primary-button" disabled={busy || !state.initialized || done} onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button></div>
            <span className="muted" role="status">{busy ? "Updating…" : done ? "Complete" : playing ? "Playing" : "Paused"} · {progress.elapsed}{progress.total == null ? "" : ` / ${progress.total}`} hours processed</span>
          </div>
          <details className="replay-playback-options"><summary>Playback speed</summary><label>Advance slots<select value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={1}>1 slot / 2 seconds</option><option value={2}>1 slot / second</option><option value={4}>2 slots / second</option></select></label></details>
          <p className="replay-description">{state.description ?? "Choose a scenario and reset to begin. Replay has its own clock and portfolio."}</p>
          {historicalUnavailable && <p className="muted">Historical replay is awaiting imported price data on this machine.</p>}
          {state.provenance && <details><summary>Historical data and assumptions</summary><div className="panel-body"><p>Prices: {state.provenance.priceDataKind === "OBSERVED_WITH_SIMULATED_SHOCKS" ? "observed base with simulated price shocks" : "observed"} · Capacity and workloads: simulated · {state.startSlot} prior hours loaded before scoring.</p><p>{state.provenance.notes}</p>{state.provenance.sourcePools.map(pool => <p key={pool}>{pool}</p>)}<p>Dataset: {state.provenance.datasetSha256}</p></div></details>}
          </details>
        </section>
        {!state.initialized ? <section><p className="empty">No replay initialized. Reset to start a reproducible simulation.</p></section> : <section className="replay-story">
          <div className="replay-story-block"><div className="replay-story-heading"><h2>Workload</h2><span className="tag">{job?.status ?? "No arrived jobs"}</span></div>
            <div className="control-row"><label>Policy <select value={strategy} onChange={event => { setStrategy(event.target.value as Strategy); setJobId(""); }}>{state.strategies.filter(policy => visiblePolicies.includes(policy)).map(policy => <option value={policy} key={policy}>{usageFor(policy).label}</option>)}</select></label>{strategyState?.jobs.length ? <label>Workload <select value={job?.id ?? ""} onChange={event => setJobId(event.target.value)}>{strategyState.jobs.map(job => <option key={job.id} value={job.id}>{job.name}</option>)}</select></label> : null}</div>
            {selectedUsage.note && <p className="muted">{selectedUsage.note}</p>}
            {job ? <dl className="replay-plan-summary"><div><dt>Compute required</dt><dd>{job.resourceUnits} × {job.gpuType ?? job.resourceType}</dd></div><div><dt>Run time</dt><dd>{job.durationSlots} hours</dd></div><div><dt>Complete within</dt><dd>{job.deadlineSlot - job.arrivalSlot} hours of arrival</dd></div><div><dt>Allowed regions</dt><dd>{job.allowedRegions.join(", ")}</dd></div></dl> : <p className="muted">Step or play the replay to see an arrived workload.</p>}
          </div>
          <div className="replay-story-block"><h2>Decision</h2><p>{strategyState?.status !== "ACTIVE" ? strategyState?.error ?? "Policy state is unavailable." : decisionText}</p>
            {decision && job && strategyState?.status === "ACTIVE" && <dl className="replay-plan-summary"><div><dt>Planned start</dt><dd>{decision.plannedStartSlot == null ? "Unavailable" : `${decision.plannedStartSlot - job.arrivalSlot} hours after arrival`}</dd></div><div><dt>Predicted job cost</dt><dd>{decision.projectedCostUsd == null ? "Unavailable" : `$${decision.projectedCostUsd.toFixed(4)}`}</dd></div></dl>}
            {waitingDecision && waitingDecision !== decision && <p className="muted">Earlier decision at slot {waitingDecision.decidedAtSlot}: WAIT{waitingDecision.plannedStartSlot == null || !job ? "." : ` · planned start ${waitingDecision.plannedStartSlot - job.arrivalSlot} hours after arrival.`} Full reasoning is available below.</p>}
            <details className="replay-more"><summary>Full execution plan and decision history</summary><DecisionInspector decision={decision} job={job} currentSlot={state.currentSlot} /><ul className="replay-history">{jobDecisions.map((row, index) => <li key={`${row.decidedAtSlot}-${index}`}><span>Slot {row.decidedAtSlot}</span><span>{row.action} · {row.explanation}</span></li>)}</ul></details>
          </div>
          <div className="replay-story-block"><h2>Outcome</h2><p>{job ? `${job.name} · ${job.status}` : "No arrived workloads for this policy."}</p><p className="muted">{completedOutcome && job ? `Finished ${completedOutcome.slot - job.arrivalSlot} hours after arrival. Deadline: ${job.deadlineSlot - job.arrivalSlot} hours after arrival.` : job?.status === "PENDING" ? "Waiting for execution; no completed outcome yet." : job?.status === "RUNNING" ? "Execution is simulated and still in progress." : strategyState?.outcomes.filter(row => row.jobId === job?.id).map(row => `Slot ${row.slot}: ${row.reason}`).join(" · ") || "No terminal outcome recorded."}</p></div>
          <details className="replay-more"><summary>Capacity by pool</summary><div className="replay-story-block">
            <p className="muted">Scenario limits before workload reservations, not AWS inventory. Future capacity is not shown.</p>
            {capacity.length ? <div className="table-scroll"><table><thead><tr><th scope="col">Region</th><th scope="col">Resource</th><th scope="col">Total units</th></tr></thead><tbody>{capacity.map(row => <tr key={`${row.region}-${row.resourceType}-${row.gpuType ?? ""}`}><td>{row.region}</td><td>{row.gpuType ?? row.resourceType}</td><td>{row.availableUnits ?? "Unknown"}</td></tr>)}</tbody></table></div> : <p className="empty">Step once to observe the first capacity limits.</p>}
          </div></details>
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
        <PolicyComparison metrics={metrics} />
      </div>
    </div>
    <div id={`${id}-panel-1`} role="tabpanel" aria-labelledby={`${id}-tab-1`} hidden={view !== 1}><BackendExecution data={data} onRefresh={onRefresh} /></div>
  </div>;
}
