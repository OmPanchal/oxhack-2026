"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { previewData } from "@/lib/preview";
import { latestDecision } from "@/lib/decisions";
import type { Job, JobCreate, TerminalData } from "@/lib/types";
import { AddJobModal } from "@/components/AddJobModal";
import { WorkloadModal } from "@/components/WorkloadModal";
import { deadlineAttention, formatTimeLeft, jobHardware, rebaseJob } from "@/lib/workloads";
import type { JobFilters } from "@/lib/workloads";
import { Portfolio } from "@/components/Portfolio";
import { MarketChart } from "@/components/MarketChart";
import { JobBlotter } from "@/components/JobBlotter";
import { ReplayWorkspace } from "@/components/ReplayWorkspace";
import { WorkloadTimeline } from "@/components/WorkloadTimeline";

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
  const [preview, setPreview] = useState(true);
  const [data, setData] = useState<TerminalData | null>(null);
  const [previewJobs, setPreviewJobs] = useState<Job[]>(previewData.jobs);
  const [showAddJob, setShowAddJob] = useState(false);
  const [showJobDetails, setShowJobDetails] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [filters, setFilters] = useState<JobFilters>({ query: "", resource: "ALL", status: "ALL", sort: "deadline" });
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(previewData.jobs[0]?.id ?? null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setError(null);
    if (preview) { setSelectedId(previewJobs[0]?.id ?? null); return; }
    setData(null);
    // Explicit backend mode bypasses environment mock settings and never falls back.
    Promise.all([api.jobs(), api.market(), api.forecasts(), api.decisions(), api.replayState()])
      .then(([jobs, market, forecasts, decisions, replay]) => {
        if (active) { setData({ jobs, market, forecasts, decisions, replay }); setSelectedId(jobs[0]?.id ?? null); }
      }).catch((error: unknown) => { if (active) setError(String(error)); });
    return () => { active = false; };
  }, [preview, refresh]);
  // Hide previous-mode data immediately while the effect starts the new request.
  const visible = preview ? { ...previewData, jobs: previewJobs } : data;
  const currentSlot = visible?.replay.currentSlot ?? 0;
  const regions = [...new Set([...(visible?.market.map(row => row.region) ?? []), ...(visible?.jobs.flatMap(row => row.allowedRegions) ?? [])])].sort();
  const gpuTypes = [...new Set([
    ...(visible?.market.flatMap(row => row.gpuType ? [row.gpuType] : []) ?? []),
    ...(visible?.jobs.flatMap(row => row.allowedGpuTypes?.length ? row.allowedGpuTypes : row.gpuType ? [row.gpuType] : []) ?? []),
    ...(preview ? ["A100", "H100", "L4"] : []), // Illustrative preview catalog, not observed capacity.
  ])].sort();
  const attentionJobs = visible?.jobs.filter(row => deadlineAttention(row, currentSlot)) ?? [];
  function inspect(id: string) { setSelectedId(id); setShowJobDetails(true); }
  async function createJob(payload: JobCreate) {
    if (preview) {
      const job: Job = { ...payload, status: "PENDING" };
      setPreviewJobs(jobs => [...jobs, job]);
      setNotice(`Added “${job.name}” to the preview. This is an example job; reload resets preview changes.`);
    } else {
      const clock = await api.replayState();
      const job = await api.createJob(rebaseJob(payload, clock.currentSlot));
      setData(current => current ? { ...current, replay: clock, jobs: [...current.jobs.filter(row => row.id !== job.id), job] } : current);
      setNotice(`Added “${job.name}” to the backend portfolio.`);
    }
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
      <div className="header-controls"><label className="source-picker">Data source
        <select value={preview ? "preview" : "backend"} onChange={event => { setShowJobDetails(false); setData(null); setNotice(null); setError(null); setPreview(event.target.value === "preview"); }}>
          <option value="preview">Design preview</option><option value="backend">Backend data</option>
        </select></label>{!preview && <button onClick={() => setRefresh(n => n + 1)}>Refresh</button>}</div>
    </header>
    <div className="preview-note"><span className="tag">{preview ? "Simulated preview" : error ? "Backend error" : visible ? "Backend data" : "Connecting"}</span>
      <span>{preview ? "Illustrative data. No model, benchmark or execution has run." : "State provided by FastAPI."}</span></div>
    <div className="view-context"><p>{activeTab === "overview" && visible ? `${attentionJobs.length} ${attentionJobs.length === 1 ? "workload needs" : "workloads need"} attention · ${visible.jobs.filter(row => row.status === "PENDING").length} pending` : currentTab.description}</p><div className="view-actions"><span className="muted">{visible ? activeTab === "replay" && preview ? "Separate preview scenario · 1h slots" : `Slot ${currentSlot} · 1h intervals` : "Connecting…"}</span>{visible && (activeTab === "overview" || activeTab === "workloads") && <button className="primary-button" onClick={() => setShowAddJob(true)}>Add job</button>}</div></div>
    {notice && <div className="success-note" role="status"><span>{notice}</span><button className="text-button" onClick={() => setNotice(null)}>Dismiss</button></div>}
    {!preview && error && <div role="alert" className="notice error">{error}</div>}
    {!visible && !error && <p className="empty" role="status">Connecting to backend…</p>}
    {visible && <div id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
      {activeTab === "overview" && <div className="view-enter">
        <Portfolio jobs={visible.jobs} preview={preview} currentSlot={currentSlot} />
        <div className="overview-workloads">
        {attentionJobs.length > 0 && <section className="attention-list"><div className="panel-heading"><h2>Needs attention</h2><span className="muted">{attentionJobs.length} jobs</span></div>{attentionJobs.map(row => <div className="attention-item" key={row.id}><button className="text-button" onClick={() => inspect(row.id)}>{row.name}</button><span className="attention">{deadlineAttention(row, currentSlot)}</span></div>)}</section>}
        <section><div className="panel-heading"><h2>Upcoming workloads</h2><button className="text-button" onClick={() => setActiveTab("workloads")}>View all workloads →</button></div>
          <div className="table-scroll"><table><thead><tr><th>Workload</th><th>Resource</th><th>Time left</th><th>Plan</th></tr></thead><tbody>
            {[...visible.jobs].filter(row => row.status === "PENDING").sort((a, b) => a.deadlineSlot - b.deadlineSlot || a.id.localeCompare(b.id)).slice(0, 4).map(row => {
              const plan = visible.decisions.find(d => d.jobId === row.id);
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
          {workloadView === "timeline" && <WorkloadTimeline jobs={visible.jobs} decisions={visible.decisions} currentSlot={currentSlot} selectedId={selectedId} onSelect={inspect} preview={preview} />}
        </div>
      </div>}
      {activeTab === "market" && <div className="view-enter"><MarketChart market={visible.market} forecasts={visible.forecasts} preview={preview} currentSlot={currentSlot} /></div>}
      <div className={activeTab === "replay" ? "view-enter" : undefined} hidden={activeTab !== "replay"}><ReplayWorkspace key={preview ? "preview" : "backend"} preview={preview} state={visible.replay} active={activeTab === "replay"} /></div>
    </div>}
    {showAddJob && visible && <AddJobModal preview={preview} currentSlot={currentSlot} regions={regions} gpuTypes={gpuTypes} onClose={() => setShowAddJob(false)} onSubmit={createJob} />}
    {showJobDetails && job && <WorkloadModal job={job} decision={decision} currentSlot={currentSlot} preview={preview} onClose={() => setShowJobDetails(false)} />}
    <footer className="statusbar"><span>{preview ? "Hand-authored preview fixtures" : "FastAPI"}</span><span>Hourly scheduling · No paid cloud provisioning</span></footer>
  </main>;
}
