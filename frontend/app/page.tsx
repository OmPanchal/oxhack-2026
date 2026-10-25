"use client";
import { useEffect, useState } from "react";
import { api, loadBackendTerminal } from "@/lib/api";
import { latestDecision, linkedDecisionDetail } from "@/lib/decisions";
import type { JobCreate, TerminalData } from "@/lib/types";
import { AddJobModal } from "@/components/AddJobModal";
import { WorkloadModal } from "@/components/WorkloadModal";
import { deadlineAttention, formatTimeLeft, jobHardware, rebaseJob } from "@/lib/workloads";
import type { JobFilters } from "@/lib/workloads";
import { Portfolio } from "@/components/Portfolio";
import { MarketChart } from "@/components/MarketChart";
import { JobBlotter } from "@/components/JobBlotter";
import { BackendReplayWorkspace } from "@/components/BackendReplayWorkspace";
import { WorkloadTimeline } from "@/components/WorkloadTimeline";
import { EngineControls } from "@/components/EngineControls";

const tabs = [
  { id: "overview", label: "Overview", description: "A quick read on your portfolio and upcoming work." },
  { id: "workloads", label: "Workloads", description: "Review the queue. Select a workload to understand its execution plan." },
  { id: "market", label: "Market", description: "Compare regional prices and explore the next scheduling windows." },
  { id: "replay", label: "Replay & execution", description: "Replay scenarios, compare policies, and monitor local execution." },
] as const;
type TabId = typeof tabs[number]["id"];
const workloadViews = [{ id: "queue", label: "Queue" }, { id: "timeline", label: "Timeline" }] as const;

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [workloadView, setWorkloadView] = useState<typeof workloadViews[number]["id"]>("queue");
  const [data, setData] = useState<TerminalData | null>(null);
  const [showAddJob, setShowAddJob] = useState(false);
  const [showJobDetails, setShowJobDetails] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [filters, setFilters] = useState<JobFilters>({ query: "", resource: "ALL", status: "ALL", sort: "deadline" });
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const next = await loadBackendTerminal();
        if (active) {
          setData(next); setError(null);
          setSelectedId(current => next.jobs.some(job => job.id === current) ? current : next.jobs[0]?.id ?? null);
        }
      } catch (error) { if (active) setError(error instanceof Error ? error.message : String(error)); }
      finally { if (active) timer = setTimeout(read, 5000); }
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [refresh]);
  const visible = data;
  const currentSlot = data?.engine?.currentSlot ?? 0;
  const regions = [...new Set([...(visible?.capabilities?.allowedRegions ?? []),...(visible?.market.map(row => row.region) ?? []), ...(visible?.jobs.flatMap(row => row.allowedRegions) ?? [])])].sort();
  const gpuTypes = [...new Set([
    ...(visible?.capabilities?.allowedGpuTypes ?? []),
    ...(visible?.market.flatMap(row => row.gpuType ? [row.gpuType] : []) ?? []),
    ...(visible?.jobs.flatMap(row => row.allowedGpuTypes?.length ? row.allowedGpuTypes : row.gpuType ? [row.gpuType] : []) ?? []),
  ])].sort();
  const attentionJobs = visible?.jobs.filter(row => deadlineAttention(row, currentSlot)) ?? [];
  function inspect(id: string) { setSelectedId(id); setShowJobDetails(true); }
  async function createJob(payload: JobCreate) {
    const clock = await api.engineState();
    const job = await api.createJob(rebaseJob(payload, clock.currentSlot));
    setData(current => current ? { ...current, engine: clock, jobs: [...current.jobs.filter(row => row.id !== job.id), job] } : current);
    setNotice(`Added “${job.name}” to your portfolio.`);
    setSelectedId(payload.id); setActiveTab("workloads"); setWorkloadView("queue");
    setFilters({ query: "", resource: "ALL", status: "ALL", sort: "deadline" });
  }
  const job = visible?.jobs.find(row => row.id === selectedId);
  const decision = latestDecision(visible?.decisions ?? [], selectedId, currentSlot);
  const currentTab = tabs.find(tab => tab.id === activeTab)!;
  return <main className="rounded-none">
    <header className="topbar">
      <div className="brand"><h1>arbitr</h1></div>
    <div className="tabs" role="tablist" aria-label="Terminal views">
      {tabs.map((tab, index) => <button key={tab.id} id={`tab-${tab.id}`} role="tab"
        aria-selected={activeTab === tab.id} aria-controls={`panel-${tab.id}`} tabIndex={activeTab === tab.id ? 0 : -1}
        onClick={() => setActiveTab(tab.id)} onKeyDown={event => {
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
          if (next !== null) { event.preventDefault(); setActiveTab(tabs[next].id); document.getElementById(`tab-${tabs[next].id}`)?.focus(); }
        }}>{tab.label}</button>)}
    </div>
      <div className="header-controls"><button onClick={() => setRefresh(n => n + 1)}>Refresh</button></div>
    </header>
    {activeTab !== "replay" && <div className="data-note"><span className="tag">{error ? "Connection error" : visible ? visible.engine?.dataKind === "SIMULATED" ? "Simulated market data" : "Connected" : "Connecting"}</span>
      {visible && <span>{visible.engine?.dataKind === "SIMULATED" ? "Market inputs are simulated. No cloud workload has been launched." : "Prices, forecasts and workload state from the connected service."}</span>}</div>}
    <div className="view-context"><p>{activeTab === "overview" && visible ? `${attentionJobs.length} ${attentionJobs.length === 1 ? "workload needs" : "workloads need"} attention · ${visible.jobs.filter(row => row.status === "PENDING").length} pending` : currentTab.description}</p><div className="view-actions"><span className="muted">{visible ? activeTab === "replay" ? "Hourly replay" : `Slot ${currentSlot} · 1h intervals` : "Connecting…"}</span>{visible && (activeTab === "overview" || activeTab === "workloads") && <button className="primary-button" onClick={() => setShowAddJob(true)}>Add job</button>}</div></div>
    {notice && <div className="success-note" role="status"><span>{notice}</span><button className="text-button" onClick={() => setNotice(null)}>Dismiss</button></div>}
    {error && <div role="alert" className="notice error">{error}</div>}
    {data?.errors?.map(message => <div key={message} role="alert" className="notice error">{message}</div>)}
    {data?.engine && (activeTab === "replay" ? <details className="replay-more live-engine-settings"><summary>Live engine controls · separate from replay</summary><EngineControls state={data.engine} onRefresh={() => setRefresh(n => n + 1)} /></details> : <EngineControls state={data.engine} onRefresh={() => setRefresh(n => n + 1)} />)}
    {!visible && !error && <p className="empty" role="status">Connecting to backend…</p>}
    {visible && <div id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
      {activeTab === "overview" && <div className="view-enter">
        <Portfolio jobs={visible.jobs} currentSlot={currentSlot} metrics={visible.liveMetrics} />
        <div className="overview-workloads">
        {attentionJobs.length > 0 && <section className="attention-list"><div className="panel-heading"><h2>Needs attention</h2><span className="muted">{attentionJobs.length} jobs</span></div>{attentionJobs.map(row => <div className="attention-item" key={row.id}><button className="text-button" onClick={() => inspect(row.id)}>{row.name}</button><span className="attention">{deadlineAttention(row, currentSlot)}</span></div>)}</section>}
        <section><div className="panel-heading"><h2>Upcoming workloads</h2><button className="text-button" onClick={() => setActiveTab("workloads")}>View all workloads →</button></div>
          <div className="table-scroll"><table><thead><tr><th>Workload</th><th>Resource</th><th>Time left</th><th>Plan</th></tr></thead><tbody>
            {[...visible.jobs].filter(row => row.status === "PENDING").sort((a, b) => a.deadlineSlot - b.deadlineSlot || a.id.localeCompare(b.id)).slice(0, 4).map(row => {
              const plan = latestDecision(visible.decisions, row.id, currentSlot);
              return <tr key={row.id}><td><button className="row-select" onClick={() => inspect(row.id)}>{row.name}</button></td><td className="muted">{row.resourceUnits} × {jobHardware(row)}</td><td>{formatTimeLeft(row.deadlineSlot, currentSlot)}</td><td className={plan?.action === "WAIT" ? "attention" : "muted"}>{plan?.action ?? "Awaiting plan"}</td></tr>;
            })}
          </tbody></table></div>
          {!visible.jobs.some(row => row.status === "PENDING") && <p className="empty">No pending workloads.</p>}
        </section>
        </div>
      </div>}
      {activeTab === "workloads" && <div className="stack view-enter">
        <div className="tabs workload-view-tabs" role="tablist" aria-label="Workload views">
          {workloadViews.map((view, index) => <button key={view.id} id={`workload-view-${view.id}`} role="tab" aria-selected={workloadView === view.id} aria-controls={`workload-content-${view.id}`} tabIndex={workloadView === view.id ? 0 : -1} onClick={() => setWorkloadView(view.id)} onKeyDown={event => {
            const next = event.key === "ArrowRight" ? (index + 1) % workloadViews.length : event.key === "ArrowLeft" ? (index + workloadViews.length - 1) % workloadViews.length : event.key === "Home" ? 0 : event.key === "End" ? workloadViews.length - 1 : null;
            if (next !== null) { event.preventDefault(); setWorkloadView(workloadViews[next].id); document.getElementById(`workload-view-${workloadViews[next].id}`)?.focus(); }
          }}>{view.label}</button>)}
        </div>
        <div id="workload-content-queue" role="tabpanel" aria-labelledby="workload-view-queue" hidden={workloadView !== "queue"}>
          {workloadView === "queue" && <JobBlotter jobs={visible.jobs} decisions={visible.decisions} selectedId={selectedId} onSelect={inspect} filters={filters} onFilters={setFilters} currentSlot={currentSlot} />}
        </div>
        <div id="workload-content-timeline" role="tabpanel" aria-labelledby="workload-view-timeline" hidden={workloadView !== "timeline"}>
          {workloadView === "timeline" && <WorkloadTimeline jobs={visible.jobs} decisions={visible.decisions} currentSlot={currentSlot} selectedId={selectedId} onSelect={inspect} />}
        </div>
      </div>}
      {activeTab === "market" && <div className="view-enter"><MarketChart market={visible.market} forecasts={visible.forecasts} currentSlot={currentSlot} modelMetrics={visible.modelMetrics} modelStatus={visible.modelStatus} /></div>}
      <div className={activeTab === "replay" ? "view-enter" : undefined} hidden={activeTab !== "replay"}><BackendReplayWorkspace data={visible} active={activeTab === "replay"} onRefresh={() => setRefresh(n => n + 1)} /></div>
    </div>}
    {showAddJob && visible && <AddJobModal currentSlot={currentSlot} regions={regions} gpuTypes={gpuTypes} tasks={visible.taskCatalog?.tasks} onClose={() => setShowAddJob(false)} onSubmit={createJob} />}
    {showJobDetails && job && <WorkloadModal job={job} decision={decision} evidence={linkedDecisionDetail(visible?.decisions ?? [], visible?.decisionDetails ?? [], decision)} currentSlot={currentSlot} onClose={() => setShowJobDetails(false)} />}
    <footer className="statusbar"><span>Connected service</span><span>Hourly scheduling · No paid cloud provisioning</span></footer>
  </main>;
}
