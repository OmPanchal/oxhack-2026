import type { Decision, Job } from "@/lib/types";
import { latestDecision } from "@/lib/decisions";
import { timelineWindow } from "@/lib/timeline";

export function WorkloadTimeline({ jobs, decisions, currentSlot, selectedId, onSelect, preview }: {
  jobs: Job[]; decisions: Decision[]; currentSlot: number; selectedId: string | null; onSelect: (id: string) => void; preview: boolean;
}) {
  return <section aria-labelledby="timeline-heading">
    <div className="panel-heading"><h2 id="timeline-heading">Workload timeline</h2><span className="tag">{preview ? "Example plans" : "Planned windows"}</span></div>
    <div className="timeline-legend"><span><i className="legend-wait" />Wait from submission</span><span><i className="legend-execution" />Planned execution</span><span><i className="legend-deadline" />Deadline</span><span>Dashed marker: now · slot {currentSlot}</span></div>
    {!jobs.length ? <div className="empty"><h3>No workloads to map</h3><p>Add a workload to see its deadline here. Execution bars appear when a plan is supplied.</p></div> : <ul className="timeline-list">{jobs.map(job => {
      const decision = latestDecision(decisions, job.id, currentSlot);
      const window = timelineWindow(job, decision, currentSlot);
      return <li key={job.id} className={job.id === selectedId ? "timeline-selected" : undefined}>
        <div className="timeline-row-title"><button className="text-button" aria-current={job.id === selectedId ? "true" : undefined} onClick={() => onSelect(job.id)}>{job.name}</button><span className="muted">{job.status}</span></div>
        <div className="timeline-track" role="img" aria-label={`${job.name}: ${window.plan ? `planned execution slots ${window.plan.start} to ${window.plan.end}` : "no supplied execution window"}; deadline slot ${job.deadlineSlot}; current slot ${currentSlot}.`}>
          {window.plan && <>{window.plan.waitWidth > 0 && <span className="timeline-wait" style={{ left: `${window.plan.waitLeft}%`, width: `${window.plan.waitWidth}%` }} />}<span className="timeline-execution" style={{ left: `${window.plan.left}%`, width: `${window.plan.width}%` }} /></>}
          <span className="timeline-now" style={{ left: `${window.now}%` }} /><span className="timeline-deadline" style={{ left: `${window.deadline}%` }} />
        </div>
        <div className="timeline-axis"><span>Slot {window.origin}</span><span>{window.plan ? `Planned ${window.plan.start}–${window.plan.end}` : "No plan supplied"} · Deadline {job.deadlineSlot}</span><span>Slot {window.limit}</span></div>
      </li>;
    })}</ul>}
    <div className="panel-footer">Each row spans its own submission-to-deadline window, extended to include now and the supplied plan. Bars show plans, not execution history.</div>
  </section>;
}
