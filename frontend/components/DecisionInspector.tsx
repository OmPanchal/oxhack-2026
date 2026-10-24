import type { Decision, Job } from "@/lib/types";
export function DecisionInspector({ decision, job, preview }: { decision?: Decision; job?: Job; preview: boolean }) {
  return <section aria-labelledby="decision-heading"><div className="panel-heading"><h2 id="decision-heading">Execution plan</h2><span className="attention">{preview ? "EXAMPLE" : "BACKEND"}</span></div>
    <div className="panel-heading"><span>{job?.id ?? "NO SELECTION"}</span><span className={decision?.action === "WAIT" ? "attention" : "positive"}>{decision?.action ?? "NO DECISION"}</span></div>
    {decision ? <><dl className="key-values">
      <div><dt>REGION</dt><dd>{decision.region ?? "—"}</dd></div><div><dt>MODE</dt><dd className="attention">{decision.executionMode}</dd></div>
      <div><dt>START → END</dt><dd>{decision.plannedStartSlot ?? "—"} → {decision.plannedEndSlot ?? "—"}</dd></div>
      <div><dt>PROJECTED COST</dt><dd className="positive">{decision.projectedCostUsd == null ? "—" : `$${decision.projectedCostUsd.toFixed(2)}`}</dd></div>
    </dl><div className="reason"><p className="muted">{decision.reasonCode}</p><p>{decision.explanation}</p></div>
    <div className="panel-footer">{preview ? "ILLUSTRATIVE PLAN / NO EXECUTION" : "PROJECTED COST IS NOT REALIZED SPEND"}</div></> : <p className="empty">No decision for this workload. Select another row or await the optimizer.</p>}
  </section>;
}
