import type { Job } from "@/lib/types";
import { jobHardware, deadlineAttention, formatTimeLeft } from "@/lib/workloads";
export function JobDetails({ job, currentSlot }: { job?: Job; currentSlot: number }) {
  if (!job) return <section><div className="panel-heading"><h2>Job details</h2></div><p className="empty">Select a workload to inspect its requirements.</p></section>;
  const attention = deadlineAttention(job, currentSlot);
  return <section aria-labelledby="job-details-heading"><div className="panel-heading"><h2 id="job-details-heading">Job details</h2><span className="muted">{job.status}</span></div>
    <div className="job-details-title"><h3>{job.name}</h3><p className="muted">{job.id}</p>{attention && <p className="attention">{attention}</p>}</div>
    <dl className="key-values"><div><dt>Resource</dt><dd>{job.resourceUnits} × {jobHardware(job)}</dd></div><div><dt>Duration</dt><dd>{job.durationSlots} hours</dd></div>
      <div><dt>Complete within</dt><dd>{job.deadlineSlot - job.arrivalSlot} hours from submission</dd></div><div><dt>Time left</dt><dd>{job.status === "COMPLETED" || job.status === "FAILED" ? "—" : formatTimeLeft(job.deadlineSlot, currentSlot)}</dd></div>
      <div><dt>Maximum budget</dt><dd>{job.maxBudgetUsd === null ? "No limit" : `$${job.maxBudgetUsd.toFixed(2)}`}</dd></div><div><dt>Priority</dt><dd>{({0: "Normal", 1: "High", 2: "Urgent"} as Record<number, string>)[job.priority] ?? job.priority}</dd></div>
    </dl><div className="reason"><p className="muted">Allowed regions</p><p>{job.allowedRegions.join(", ")}</p></div>
  </section>;
}
