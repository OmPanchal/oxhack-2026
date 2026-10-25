"use client";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { TerminalData } from "@/lib/types";
import { ExecutionMonitor } from "./ExecutionMonitor";

export function BackendExecution({ data, onRefresh }: { data: TerminalData; onRefresh: () => void }) {
  const [selected, setSelected] = useState("");
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const records = data.executions ?? [];
  const record = records.find(row => row.id === selected) ?? [...records].sort((a,b) => a.requestedAtUtc.localeCompare(b.requestedAtUtc)).at(-1);
  const eligible = data.jobs.filter(job => job.dockerTaskId && job.status === "PENDING");
  const pending = eligible.find(job => job.id === jobId) ?? eligible[0];
  async function execute() {
    if (!pending || lock.current) return;
    lock.current = true; setBusy(true); setError(null);
    try { const result = await api.execute(pending.id); setSelected(result.id); }
    catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    finally { lock.current = false; setBusy(false); onRefresh(); }
  }
  return <div className="stack">
    <section><div className="panel-heading"><h2>Local execution</h2><span className="tag">LOCAL · CPU</span></div>
      <div className="control-row"><label>Pending task <select disabled={!eligible.length || busy} value={pending?.id ?? ""} onChange={event => setJobId(event.target.value)}>{!eligible.length && <option value="">No pending local tasks</option>}{eligible.map(job => <option value={job.id} key={job.id}>{job.name}</option>)}</select></label>
        <button disabled={busy || !pending || data.engine?.dispatch.paused} onClick={() => void execute()}>{busy ? "Starting…" : "Run local task"}</button>
        <button onClick={onRefresh} disabled={busy}>Refresh</button>
      </div><p className="panel-body muted">Local tasks wait here until you press Run local task. Cloud regions and market availability are not used. Docker Desktop or a local Linux Docker engine must be running. In the accelerated demo, the default six-hour window is about 60 real seconds; choose a longer window if needed.</p>
      {eligible.length > 0 && <div className="table-scroll"><table><thead><tr><th>Pending local task</th><th>Status</th><th>Executor</th></tr></thead><tbody>{eligible.map(job => <tr key={job.id}><td><button className="text-button" disabled={busy} onClick={() => setJobId(job.id)}>{job.name}</button></td><td>PENDING</td><td>Local Docker · CPU</td></tr>)}</tbody></table></div>}
      {data.engine?.dispatch.paused && <p className="notice attention">New starts are paused. Monitoring continues.</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
    </section>
    {records.length > 0 && <label className="execution-record-picker">Execution record<select value={record?.id ?? ""} onChange={event => setSelected(event.target.value)}>{records.map(row => <option key={row.id} value={row.id}>{row.jobId} · {row.status} · {row.id}</option>)}</select></label>}
    {record && <p className="panel-body">Docker container: <code>{record.containerName}</code><br />Container ID: <code>{record.containerId ?? 'Start not yet confirmed'}</code><br />Docker engine: <code>{record.dockerEndpoint ?? 'Not recorded for this older execution'}</code><br /><span className="muted">In Docker Desktop, open Containers, include stopped containers, and search by the container name. Completed tasks are kept for inspection.</span></p>}
    <ExecutionMonitor execution={record ? { jobId: record.jobId, taskName: data.taskCatalog?.tasks.find(task => task.id === record.taskId)?.name ?? record.taskId,
      status: record.status, mode: record.executionMode, startedAt: record.startedAtUtc, completedAt: record.completedAtUtc,
      exitCode: record.exitCode, failureReason: record.failureReason, stdout: record.stdout ? record.stdout.split("\n") : [], stderr: record.stderr ? record.stderr.split("\n") : [],
      monitorError: record.lastMonitorError, stdoutTruncated: record.stdoutTruncated, stderrTruncated: record.stderrTruncated, timeoutRequested: record.timeoutRequested } : undefined} />
  </div>;
}
