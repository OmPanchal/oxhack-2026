import { useId } from "react";
import type { Decision, Job } from "@/lib/types";
import { deadlineBuffer, slotLabel } from "@/lib/decisions";

const actions: Record<Decision["action"], { title: string; detail: string }> = {
  WAIT: { title: "Wait for a later window", detail: "Execution is planned for a later slot." },
  RUN: { title: "Run now", detail: "The recommendation is to begin execution." },
  ROUTE: { title: "Use another region", detail: "Select this region before execution begins." },
  FALLBACK: { title: "Use the fallback plan", detail: "Review the reason and selected window below." },
  INFEASIBLE: { title: "No feasible execution plan", detail: "The supplied decision cannot meet the workload requirements." },
};

export function DecisionInspector({ decision, job, preview, currentSlot }: {
  decision?: Decision; job?: Job; preview: boolean; currentSlot: number;
}) {
  const headingId = useId();
  const plan = job && decision?.jobId === job.id && decision.decidedAtSlot <= currentSlot ? decision : undefined;
  const age = plan ? currentSlot - plan.decidedAtSlot : 0;
  return <section className="execution-plan" aria-labelledby={headingId}>
    <div className="panel-heading"><h2 id={headingId}>Execution plan</h2><span className="tag">{preview ? "Example plan" : "Scheduling decision"}</span></div>
    {!job ? <p className="empty">Select a workload to see its execution plan.</p> : !plan ? <div className="plan-lead">
      <p className="muted">{job.name} · {job.id}</p><h3>No plan available</h3>
      <p>{preview ? "No example scheduling decision is supplied for this workload at this slot." : "No scheduling decision is available for this workload yet."}</p>
    </div> : <>
      <div className="plan-lead">
        <p className="muted">{job.name} · {job.id}</p>
        <div className="plan-action"><h3>{actions[plan.action].title}</h3><span className={plan.action === "WAIT" || plan.action === "INFEASIBLE" || plan.action === "FALLBACK" ? "attention" : "muted"}>{plan.action}</span></div>
        <p>{actions[plan.action].detail}</p>
        {age > 0 && <p className="attention">Decided {age}h ago. This plan may need to be refreshed.</p>}
      </div>
      <div className="plan-reason"><h3>Why this action</h3><p>{plan.explanation || "No explanation supplied."}</p></div>
      <dl className="key-values">
        <div><dt>Selected region</dt><dd>{plan.region ?? "Unavailable"}</dd></div>
        <div><dt>Projected cost</dt><dd>{plan.projectedCostUsd === null ? "Unavailable" : `$${plan.projectedCostUsd.toFixed(2)}`}</dd></div>
        <div className="wide-detail"><dt>Planned start</dt><dd>{plan.plannedStartSlot === null ? "Unavailable" : slotLabel(plan.plannedStartSlot, currentSlot)}</dd></div>
        <div className="wide-detail"><dt>Planned completion</dt><dd>{plan.plannedEndSlot === null ? "Unavailable" : slotLabel(plan.plannedEndSlot, currentSlot)}</dd></div>
        <div className="wide-detail"><dt>Deadline buffer · from planned completion</dt><dd className={plan.plannedEndSlot !== null && plan.plannedEndSlot > job.deadlineSlot ? "attention" : undefined}>{deadlineBuffer(job.deadlineSlot, plan.plannedEndSlot)}</dd></div>
        <div className="wide-detail"><dt>Deadline</dt><dd>{slotLabel(job.deadlineSlot, currentSlot)}</dd></div>
      </dl>
      <details className="plan-evidence"><summary>Decision details & evidence</summary>
        <dl className="key-values">
          <div className="wide-detail"><dt>Decision issued</dt><dd>{slotLabel(plan.decidedAtSlot, currentSlot)}</dd></div>
          <div><dt>Execution mode</dt><dd>{plan.executionMode}</dd></div>
          <div><dt>Forecast / model used</dt><dd>Not supplied</dd></div>
          <div><dt>Availability</dt><dd>Unknown</dd></div><div><dt>Interruption risk</dt><dd>Unknown</dd></div>
          <div className="wide-detail"><dt>Reason code</dt><dd>{plan.reasonCode}</dd></div>
        </dl>
        <p className="plan-evidence-note">No linked forecast, uncertainty bounds, or risk estimates were supplied with this decision.</p>
      </details>
      <div className="panel-footer">{preview ? "Illustrative plan. No workload has executed." : "Projected cost is an estimate. Execution is reported separately."}</div>
    </>}
  </section>;
}
