"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { previewData, previewSlot } from "@/lib/preview";
import type { TerminalData } from "@/lib/types";
import { Portfolio } from "@/components/Portfolio";
import { MarketChart } from "@/components/MarketChart";
import { JobBlotter } from "@/components/JobBlotter";
import { DecisionInspector } from "@/components/DecisionInspector";
import { ReplayPanel } from "@/components/ReplayPanel";
import { ExecutionMonitor } from "@/components/ExecutionMonitor";
import { PolicyComparison } from "@/components/PolicyComparison";

const tabs = [
  { id: "overview", label: "Overview", description: "A quick read on your portfolio and upcoming work." },
  { id: "workloads", label: "Workloads", description: "Review the queue. Select a workload to understand its execution plan." },
  { id: "market", label: "Market", description: "Compare regional prices and explore the next scheduling windows." },
  { id: "replay", label: "Replay & execution", description: "Replay scenarios, compare policies, and monitor local execution." },
] as const;
type TabId = typeof tabs[number]["id"];

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [preview, setPreview] = useState(true);
  const [data, setData] = useState<TerminalData | null>(previewData);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(previewData.jobs[0]?.id ?? null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setError(null);
    if (preview) { setData(previewData); setSelectedId(previewData.jobs[0]?.id ?? null); return; }
    setData(null);
    // Explicit backend mode bypasses environment mock settings and never falls back.
    Promise.all([api.jobs(), api.market(), api.forecasts(), api.decisions(), api.replayState()])
      .then(([jobs, market, forecasts, decisions, replay]) => {
        if (active) { setData({ jobs, market, forecasts, decisions, replay }); setSelectedId(jobs[0]?.id ?? null); }
      }).catch((error: unknown) => { if (active) setError(String(error)); });
    return () => { active = false; };
  }, [preview, refresh]);
  // Hide previous-mode data immediately while the effect starts the new request.
  const visible = preview ? previewData : data === previewData ? null : data;
  const job = visible?.jobs.find(row => row.id === selectedId);
  const decision = visible?.decisions.find(row => row.jobId === selectedId);
  const currentTab = tabs.find(tab => tab.id === activeTab)!;
  return <main className="rounded-none">
    <header className="topbar">
      <div className="brand"><h1>Arbitr</h1></div>
    <div className="tabs" role="tablist" aria-label="Terminal views">
      {tabs.map((tab, index) => <button key={tab.id} id={`tab-${tab.id}`} role="tab"
        aria-selected={activeTab === tab.id} aria-controls={`panel-${tab.id}`} tabIndex={activeTab === tab.id ? 0 : -1}
        onClick={() => setActiveTab(tab.id)} onKeyDown={event => {
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
          if (next !== null) { event.preventDefault(); setActiveTab(tabs[next].id); document.getElementById(`tab-${tabs[next].id}`)?.focus(); }
        }}>{tab.label}</button>)}
    </div>
      <div className="header-controls"><label className="source-picker">Data source
        <select value={preview ? "preview" : "backend"} onChange={event => setPreview(event.target.value === "preview")}>
          <option value="preview">Design preview</option><option value="backend">Backend data</option>
        </select></label>{!preview && <button onClick={() => setRefresh(n => n + 1)}>Refresh</button>}</div>
    </header>
    <div className="preview-note"><span className="tag">{preview ? "Simulated preview" : error ? "Backend error" : visible ? "Backend data" : "Connecting"}</span>
      <span>{preview ? "Illustrative data. No model, benchmark or execution has run." : "State provided by FastAPI."}</span></div>
    <div className="view-context"><p>{currentTab.description}</p><span className="muted">Slot {preview ? previewSlot : visible?.replay.currentSlot ?? "—"} · USD · 1h intervals</span></div>
    {!preview && error && <div role="alert" className="notice error">{error}</div>}
    {!visible && !error && <p className="empty" role="status">Connecting to backend…</p>}
    {visible && <div id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
      {activeTab === "overview" && <>
        <Portfolio jobs={visible.jobs} preview={preview} />
        <section><div className="panel-heading"><h2>Upcoming workloads</h2><button className="text-button" onClick={() => setActiveTab("workloads")}>View all workloads →</button></div>
          <div className="table-scroll"><table><thead><tr><th>Workload</th><th>Resource</th><th>Deadline</th><th>Plan</th></tr></thead><tbody>
            {[...visible.jobs].filter(row => row.status === "PENDING").sort((a, b) => a.deadlineSlot - b.deadlineSlot || a.id.localeCompare(b.id)).slice(0, 4).map(row => {
              const plan = visible.decisions.find(d => d.jobId === row.id);
              return <tr key={row.id}><td><button className="row-select" onClick={() => { setSelectedId(row.id); setActiveTab("workloads"); }}>{row.name}</button></td><td className="muted">{row.resourceUnits} × {row.gpuType ?? row.resourceType}</td><td>Slot {row.deadlineSlot}</td><td className={plan?.action === "WAIT" ? "attention" : "muted"}>{plan?.action ?? "Awaiting plan"}</td></tr>;
            })}
          </tbody></table></div>
          {!visible.jobs.some(row => row.status === "PENDING") && <p className="empty">No pending workloads.</p>}
        </section>
      </>}
      {activeTab === "workloads" && <div className="workload-layout">
        <JobBlotter jobs={visible.jobs} decisions={visible.decisions} selectedId={selectedId} onSelect={setSelectedId} />
        <DecisionInspector decision={decision} job={job} preview={preview} />
      </div>}
      {activeTab === "market" && <MarketChart market={visible.market} forecasts={visible.forecasts} preview={preview} />}
      {activeTab === "replay" && <div className="stack"><div className="operations-layout"><ReplayPanel state={visible.replay} /><ExecutionMonitor /></div><PolicyComparison /></div>}
    </div>}
    <footer className="statusbar"><span>{preview ? "Hand-authored preview fixtures" : "FastAPI"}</span><span>UTC slots · No paid cloud provisioning</span></footer>
  </main>;
}
