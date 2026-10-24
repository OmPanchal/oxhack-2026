import type { Job } from "@/lib/types";
import { deadlineAttention } from "@/lib/workloads";
export function Portfolio({ jobs, preview, currentSlot }: { jobs: Job[]; preview: boolean; currentSlot: number }) {
  const count = (status: Job["status"]) => jobs.filter(job => job.status === status).length;
  const attention = jobs.filter(job => deadlineAttention(job, currentSlot)).length;
  return <dl className="metric-strip" aria-label="Portfolio overview">
    <div className="metric"><dt>Total workloads</dt><dd>{jobs.length}</dd><small>{preview ? "Example portfolio" : "Backend inventory"}</small></div>
    <div className="metric"><dt>Pending / running</dt><dd>{count("PENDING")} <span className="muted">/</span> {count("RUNNING")}</dd><small>Non-preemptive workloads</small></div>
    <div className="metric"><dt>Completed / failed</dt><dd>{count("COMPLETED")} <span className="muted">/</span> {count("FAILED")}</dd><small>{count("INFEASIBLE")} infeasible</small></div>
    <div className="metric"><dt>Needs attention</dt><dd>{attention}</dd><small>Deadline pressure, failed or infeasible</small></div>
  </dl>;
}
