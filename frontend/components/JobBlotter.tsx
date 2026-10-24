"use client";
import { useState } from "react";
import type { Decision, Job } from "@/lib/types";
export function JobBlotter({ jobs, decisions, selectedId, onSelect }: {
  jobs: Job[]; decisions: Decision[]; selectedId: string | null; onSelect: (id: string) => void;
}) {
  const [filter, setFilter] = useState("ALL");
  const visible = jobs.filter(job => filter === "ALL" || job.resourceType === filter);
  return <section aria-labelledby="blotter-heading"><div className="panel-heading"><h2 id="blotter-heading">Workload queue</h2>
    <label className="muted">RESOURCE <select aria-label="Filter workload resource" value={filter} onChange={e => setFilter(e.target.value)}><option>ALL</option><option>GPU</option><option>CPU</option></select></label></div>
    <div className="table-scroll"><table><thead><tr><th>ID / WORKLOAD</th><th>HARDWARE</th><th className="numeric">UNITS</th><th className="numeric">HOURS</th><th className="numeric">DEADLINE</th><th>STATUS</th><th>ACTION</th></tr></thead>
      <tbody>{visible.map(job => { const decision = decisions.find(d => d.jobId === job.id); return <tr key={job.id} className={selectedId === job.id ? "selected" : ""}>
        <td><button className="row-select" aria-pressed={selectedId === job.id} onClick={() => onSelect(job.id)}>{job.id} <span className="muted">{job.name}</span></button></td>
        <td>{job.gpuType ?? job.resourceType}</td><td className="numeric">{job.resourceUnits}</td><td className="numeric">{job.durationSlots}</td><td className="numeric">T+{job.deadlineSlot}</td>
        <td className={job.status === "FAILED" || job.status === "INFEASIBLE" ? "negative" : job.status === "PENDING" ? "attention" : "positive"}>{job.status}</td>
        <td className={decision?.action === "WAIT" ? "attention" : "positive"}>{decision?.action ?? "—"}</td></tr>; })}</tbody></table></div>
    {!visible.length && <p className="empty">No workloads match this resource.</p>}
    <div className="panel-footer"><span>{visible.length} ROWS / SELECT A WORKLOAD TO INSPECT</span><span>INTERVALS [START, END)</span></div>
  </section>;
}
