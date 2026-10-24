import type { Job } from "@/lib/types";
export function Portfolio({ jobs, preview }: { jobs: Job[]; preview: boolean }) {
  const pending = jobs.filter(job => job.status === "PENDING").length;
  const running = jobs.filter(job => job.status === "RUNNING").length;
  return <dl className="metric-strip" aria-label="Portfolio overview">
    <div className="metric"><dt>Portfolio / workloads</dt><dd>{String(jobs.length).padStart(2, "0")}</dd><small>{preview ? "Example portfolio" : "Backend inventory"}</small></div>
    <div className="metric"><dt>Pending / running</dt><dd>{String(pending).padStart(2, "0")} <span className="muted">/</span> <span className="positive">{String(running).padStart(2, "0")}</span></dd><small>Non-preemptive workloads</small></div>
    <div className="metric"><dt>Realized compute spend</dt><dd className="muted">—</dd><small>Awaiting accounting</small></div>
    <div className="metric"><dt>Realized savings</dt><dd className="muted">—</dd><small>No benchmark yet</small></div>
  </dl>;
}
