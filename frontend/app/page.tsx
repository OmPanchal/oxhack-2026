"use client";
import { useEffect, useState, useRef } from "react";
import { api, loadBackendTerminal } from "@/lib/api";
import { previewData } from "@/lib/preview";
import { latestDecision, linkedDecisionDetail, decisionSummary } from "@/lib/decisions";
import type { Job, JobCreate, TerminalData } from "@/lib/types";
import { AddJobModal } from "@/components/AddJobModal";
import { WorkloadModal } from "@/components/WorkloadModal";
import { deadlineAttention, formatTimeLeft, jobHardware, rebaseJob } from "@/lib/workloads";
import type { JobFilters } from "@/lib/workloads";
import { AcquisitionMonitor } from '@/components/AcquisitionMonitor';
import { Portfolio } from "@/components/Portfolio";
import { MarketChart } from "@/components/MarketChart";
import { JobBlotter } from "@/components/JobBlotter";
import { ReplayWorkspace } from "@/components/ReplayWorkspace";
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
  const [preview, setPreview] = useState(true);
  const lastBackend = useRef<TerminalData | undefined>(undefined);
  const [data, setData] = useState<TerminalData | null>(null);
  const [previewJobs, setPreviewJobs] = useState<Job[]>(previewData.jobs);
  const [showAddJob, setShowAddJob] = useState(false);
  const [showJobDetails, setShowJobDetails] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [filters, setFilters] = useState<JobFilters>({ query: "", resource: "ALL", status: "ALL", sort: "deadline" });
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(previewData.jobs[0]?.id ?? null);
  const [refresh, setRefresh] = useState(0);
  const [resettingReplay, setResettingReplay] = useState(false);
  async function recoverReplay() {
    if (resettingReplay || !data?.replay.scenarioId) return;
    setResettingReplay(true);
    try {
      await api.resetReplay({ scenarioId: data.replay.scenarioId, seed: data.replay.seed });
      setNotice('Saved replay reset. Live jobs and market history were preserved. Run Replay again to generate a new ledger.');
      setRefresh(n => n + 1);
    } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    finally { setResettingReplay(false); }
  }
  useEffect(() => {
    if (preview) { setError(null); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const next = await loadBackendTerminal(lastBackend.current);
        if (active) {
          lastBackend.current = next; setData(next); setError(null);
          setSelectedId(current => next.jobs.some(job => job.id === current) ? current : next.jobs[0]?.id ?? null);
        }
      } catch (error) { if (active) setError(error instanceof Error ? error.message : String(error)); }
      finally { if (active) timer = setTimeout(read, 5000); }
    }
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [preview, refresh]);
  // Hide previous-mode data immediately while the effect starts the new request.
  const visible = preview ? { ...previewData, jobs: previewJobs } : data;
  const currentSlot = preview ? previewData.replay.currentSlot : Math.max(data?.engine?.currentSlot ?? 0, data?.engine?.wallClockSlot ?? 0);
  const regions = [...new Set([...(visible?.capabilities?.allowedRegions ?? []),...(visible?.market.map(row => row.region) ?? []), ...(visible?.jobs.flatMap(row => row.allowedRegions) ?? [])])].sort();
  const gpuTypes = [...new Set([
    ...(visible?.capabilities?.allowedGpuTypes ?? []),
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
      const clock = await api.engineState();
      const job = await api.createJob(rebaseJob(payload, Math.max(clock.currentSlot, clock.wallClockSlot ?? clock.currentSlot)));
      setData(current => current ? { ...current, engine: clock, jobs: [...current.jobs.filter(row => row.id !== job.id), job] } : current);
      setNotice(`Added “${job.name}” to the backend portfolio.`);
      setRefresh(n => n + 1);
    }
    setSelectedId(payload.id); setActiveTab("workloads"); setWorkloadView("queue");
    setFilters({ query: "", resource: "ALL", status: "ALL", sort: "deadline" });
  }
  const job = visible?.jobs.find(row => row.id === selectedId);
  const decision = latestDecision(visible?.decisions ?? [], selectedId, currentSlot);
  const currentTab = tabs.find(tab => tab.id === activeTab)!;
  return <main className={activeTab === "replay" ? "rounded-none replay-page" : "rounded-none"}>
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
    <div className={`preview-note${activeTab === "replay" && !preview && !error ? " replay-connection-note" : ""}`}><span className="tag">{preview ? "Simulated preview" : error ? "Backend error" : visible ? "Backend data" : "Connecting"}</span>
      <span>{preview ? "Illustrative data. No model, benchmark or execution has run." : "State provided by FastAPI."}</span></div>
    <div className="view-context"><p>{activeTab === "overview" && visible ? `${attentionJobs.length} ${attentionJobs.length === 1 ? "workload needs" : "workloads need"} attention · ${visible.jobs.filter(row => row.status === "PENDING").length} pending` : currentTab.description}</p><div className="view-actions"><span className="muted">{visible ? activeTab === "replay" ? "Hourly replay" : `Slot ${currentSlot} · 1h intervals` : "Connecting…"}</span>{visible && (activeTab === "overview" || activeTab === "workloads") && <button className="primary-button" onClick={() => setShowAddJob(true)}>Add job</button>}</div></div>
    {notice && <div className="success-note" role="status"><span>{notice}</span><button className="text-button" onClick={() => setNotice(null)}>Dismiss</button></div>}
    {!preview && error && <div role="alert" className="notice error">{error}</div>}
    {!preview && data?.errors?.map(message => <div key={message} role="alert" className="notice error">{message}
      {message.startsWith('Replay metrics:') && message.includes('reset replay') && <p>
        This saved replay predates GPU allocation tracking. Resetting it clears simulated results only.{' '}
        <button disabled={resettingReplay} onClick={() => void recoverReplay()}>{resettingReplay ? 'Resetting…' : 'Reset saved replay'}</button>
      </p>}
    </div>)}
    {!preview && activeTab !== "replay" && data?.engine && <EngineControls connectionLost={Boolean(error)} state={data.engine} onRefresh={() => setRefresh(n => n + 1)} />}
    {!preview && activeTab === "replay" && data?.engine && <details className="replay-more live-engine-disclosure"><summary>Live engine controls · separate from replay</summary><EngineControls connectionLost={Boolean(error)} state={data.engine} onRefresh={() => setRefresh(n => n + 1)} /></details>}
    {!visible && !error && <p className="empty" role="status">Connecting to backend…</p>}
    {visible && <div id={`panel-${activeTab}`} role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
      {activeTab === "overview" && <div className="view-enter">
        <Portfolio jobs={visible.jobs} preview={preview} currentSlot={currentSlot} metrics={preview ? undefined : visible.liveMetrics} />
        {!preview && visible.engine?.acquisitionMode === 'SIMULATED' && <AcquisitionMonitor jobs={visible.jobs} records={visible.acquisitions} />}
        <div className="overview-workloads">
        {attentionJobs.length > 0 && <section className="attention-list"><div className="panel-heading"><h2>Needs attention</h2><span className="muted">{attentionJobs.length} jobs</span></div>{attentionJobs.map(row => <div className="attention-item" key={row.id}><button className="text-button" onClick={() => inspect(row.id)}>{row.name}</button><span className="attention">{deadlineAttention(row, currentSlot)}</span></div>)}</section>}
        <section><div className="panel-heading"><h2>Upcoming workloads</h2><button className="text-button" onClick={() => setActiveTab("workloads")}>View all workloads →</button></div>
          <div className="table-scroll"><table><thead><tr><th>Workload</th><th>Resource</th><th>Time left</th><th>Plan</th></tr></thead><tbody>
            {[...visible.jobs].filter(row => row.status === "PENDING").sort((a, b) => a.deadlineSlot - b.deadlineSlot || a.id.localeCompare(b.id)).slice(0, 4).map(row => {
              const plan = latestDecision(visible.decisions, row.id, currentSlot);
              return <tr key={row.id}><td><button className="row-select" onClick={() => inspect(row.id)}>{row.name}</button></td><td className="muted">{row.resourceUnits} × {jobHardware(row)}</td><td>{formatTimeLeft(row.deadlineSlot, currentSlot)}</td><td className={plan?.action === "WAIT" ? "attention" : "muted"}>{decisionSummary(plan).label}<span className="cell-note muted">{decisionSummary(plan).detail}</span></td></tr>;
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
          {workloadView === "queue" && <JobBlotter acquisitions={visible.acquisitions} executions={visible.executions} jobs={visible.jobs} decisions={visible.decisions} selectedId={selectedId} onSelect={inspect} filters={filters} onFilters={setFilters} currentSlot={currentSlot} />}
        </div>
        <div id="workload-content-timeline" role="tabpanel" aria-labelledby="workload-view-timeline" hidden={workloadView !== "timeline"}>
          {workloadView === "timeline" && <WorkloadTimeline jobs={visible.jobs} decisions={visible.decisions} currentSlot={currentSlot} selectedId={selectedId} onSelect={inspect} preview={preview} />}
        </div>
      </div>}
      {activeTab === "market" && <div className="view-enter"><MarketChart market={visible.market} forecasts={visible.forecasts} preview={preview} currentSlot={currentSlot} modelMetrics={preview ? undefined : visible.modelMetrics} modelStatus={preview ? undefined : visible.modelStatus} /></div>}
      <div className={activeTab === "replay" ? "view-enter" : undefined} hidden={activeTab !== "replay"}><ReplayWorkspace key={preview ? "preview" : "backend"} preview={preview} state={visible.replay} active={activeTab === "replay"} backendData={preview ? undefined : data ?? undefined} onRefresh={() => setRefresh(n => n + 1)} /></div>
    </div>}
    {showAddJob && visible && <AddJobModal simulationSlotSeconds={preview ? undefined : visible.engine?.simulationSlotSeconds} preview={preview} currentSlot={currentSlot} regions={regions} gpuTypes={gpuTypes} tasks={preview ? [] : visible.taskCatalog?.tasks} onClose={() => setShowAddJob(false)} onSubmit={createJob} />}
    {showJobDetails && job && <WorkloadModal acquisition={visible?.acquisitions?.find(row => row.jobId === job.id)} local={visible?.executions?.find(row => row.jobId === job.id)} job={job} decision={decision} evidence={linkedDecisionDetail(visible?.decisions ?? [], visible?.decisionDetails ?? [], decision)} currentSlot={currentSlot} preview={preview} onClose={() => setShowJobDetails(false)} />}
    <footer className="statusbar"><span>{preview ? "Hand-authored preview fixtures" : "FastAPI"}</span><span>{!preview && visible?.engine?.acquisitionMode === 'SIMULATED' ? 'Accelerated SIMULATED demo · No cloud provisioning' : 'Hourly scheduling · No paid cloud provisioning'}</span></footer>
  </main>;
}
