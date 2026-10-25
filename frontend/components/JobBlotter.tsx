"use client";
import type { Decision, Job } from "@/lib/types";
import { jobHardware, deadlineAttention, filterJobs, formatTimeLeft } from "@/lib/workloads";
import type { JobFilters } from "@/lib/workloads";
import { latestDecision, decisionSummary } from "@/lib/decisions";
import type { Acquisition, LocalExecution } from '@/lib/backend-types';
import { workloadExecution } from '@/lib/execution';
import { regionName } from '@/lib/market';

export function JobBlotter({ jobs, decisions, acquisitions = [], executions = [], selectedId, onSelect, filters, onFilters, currentSlot }: {
  jobs: Job[]; decisions: Decision[]; selectedId: string | null; onSelect: (id: string) => void;
  filters: JobFilters; onFilters: (filters: JobFilters) => void; currentSlot: number;
  acquisitions?: Acquisition[]; executions?: LocalExecution[];
}) {
  const visible = filterJobs(jobs, filters);
  const reset = () => onFilters({ query: "", resource: "ALL", status: "ALL", sort: "deadline" });
  return <section aria-labelledby="blotter-heading"><div className="panel-heading"><h2 id="blotter-heading">Workload queue</h2><span className="muted">{jobs.length} jobs</span></div>
    <div className="queue-filters"><label className="search-field">Search<input type="search" placeholder="Name, ID, region or GPU model" value={filters.query} onChange={e => onFilters({ ...filters, query: e.target.value })} /></label>
      <label>Resource<select value={filters.resource} onChange={e => onFilters({ ...filters, resource: e.target.value })}><option value="ALL">All resources</option><option>GPU</option><option>CPU</option></select></label>
      <label>Status<select value={filters.status} onChange={e => onFilters({ ...filters, status: e.target.value })}><option value="ALL">All statuses</option>{["PENDING", "RUNNING", "COMPLETED", "FAILED", "INFEASIBLE"].map(status => <option key={status}>{status}</option>)}</select></label>
      <label>Sort by<select value={filters.sort} onChange={e => onFilters({ ...filters, sort: e.target.value })}><option value="deadline">Earliest deadline</option><option value="priority">Highest priority</option><option value="name">Job name</option></select></label>
    </div>
    <div className="table-scroll"><table><thead><tr><th>Workload</th><th>Hardware</th><th className="numeric">Units</th><th>Time left</th><th>Execution status</th><th>Execution location</th><th>Activity</th></tr></thead>
      <tbody>{visible.map(job => { const decision = latestDecision(decisions, job.id, currentSlot); const attention = deadlineAttention(job, currentSlot); const state = workloadExecution(job, decision, acquisitions.find(r => r.jobId === job.id), executions.find(r => r.jobId === job.id)); return <tr key={job.id} className={selectedId === job.id ? "selected" : ""}>
        <td><button className="row-select job-name" aria-haspopup="dialog" aria-pressed={selectedId === job.id} onClick={() => onSelect(job.id)}>{job.name}<span className="muted">{job.id}</span></button></td>
        <td>{jobHardware(job)}</td><td className="numeric">{job.resourceUnits}</td><td><span>{job.status === "COMPLETED" || job.status === "FAILED" ? "—" : formatTimeLeft(job.deadlineSlot, currentSlot)}</span>{attention && <span className="cell-note attention">{attention}</span>}</td>
        <td className={job.status === "FAILED" || job.status === "INFEASIBLE" ? "negative" : "muted"}>{job.status}</td>
        <td>{state.region ? regionName(state.region) : job.dockerTaskId ? 'Local machine' : 'Not confirmed'}<span className="cell-note muted">{state.region ?? (job.dockerTaskId ? 'LOCAL · not started' : state.plannedRegion ? `Planned: ${regionName(state.plannedRegion)}` : 'Not allocated')}{state.mode ? ` · ${state.mode}` : ''}</span></td>
        <td className={job.status === 'PENDING' && !job.dockerTaskId ? 'attention' : job.status === 'FAILED' || job.status === 'INFEASIBLE' ? 'negative' : 'positive'}>{job.status === 'PENDING' && !job.dockerTaskId && decision?.action === 'WAIT' ? decisionSummary(decision).label : state.phase}
          <span className="cell-note muted">{job.status === 'PENDING' && job.dockerTaskId ? 'Start from Replay & execution → Execution' : job.status === 'PENDING' ? decisionSummary(decision).detail : state.routed && state.region ? `Routed to ${regionName(state.region)}` : ''}</span>
        </td></tr>; })}</tbody></table></div>
    {!visible.length && <div className="empty"><p>{jobs.length ? "No jobs match these filters." : "No jobs yet. Add your first CPU or GPU workload."}</p>{jobs.length > 0 && <button className="text-button" onClick={reset}>Clear filters</button>}</div>}
    <div className="panel-footer"><span role="status">Showing {visible.length} of {jobs.length} jobs</span><span>Location is confirmed after acquisition. Original scheduling decisions remain in job details.</span></div>
  </section>;
}
