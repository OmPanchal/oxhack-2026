import type { Decision } from "@/lib/types";
export function DecisionInspector({ decisions }: { decisions: Decision[] }) {
  return <section><h2>Decision inspector</h2>{decisions.length ? decisions.map((decision, i) =>
    <p key={`${decision.jobId}-${i}`}><strong>{decision.action}</strong> · {decision.explanation} · {decision.executionMode}</p>
  ) : <p>No scheduling decisions yet. The optimizer will supply actions and explanations.</p>}</section>;
}
