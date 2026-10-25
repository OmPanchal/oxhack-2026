import type { ReplayMetrics } from "@/lib/backend-types";

import { policyPresentation, visiblePolicies as policies } from "@/lib/policy-labels";
export function PolicyComparison({ metrics }: { metrics?: ReplayMetrics }) {
  return <section><div className="panel-heading"><h2>Policy comparison</h2><span className="tag">{metrics ? `${metrics.status} · SIMULATED` : "No benchmark results"}</span></div>
    {metrics?.provenance && <p className="panel-body">{metrics.provenance.priceDataKind === "OBSERVED_WITH_SIMULATED_SHOCKS" ? "Observed historical base prices with simulated price shocks" : "Observed historical prices"} · simulated workloads and capacity. Previously evaluated dates; this is not a fresh accuracy test or actual cloud spend.</p>}
    <div className="table-scroll"><table><thead><tr><th>Policy</th><th>Status</th><th className="numeric">Spend</th><th className="numeric">Done</th><th className="numeric">Missed</th><th className="numeric">Failed</th><th className="numeric">Infeasible</th><th className="numeric">Unfinished</th></tr></thead>
      <tbody>{policies.map(policy => { const row = metrics?.strategies.find(row => row.strategy === policy); const usable = !!row && row.status !== "UNAVAILABLE"; const usage = policyPresentation(policy, row?.modelVersions, row?.status); return <tr key={policy}><td>{usage.label}{usage.note && <span className="cell-note muted">{usage.note}</span>}{row?.modelVersions?.length ? <details><summary>Model versions</summary><span className="cell-note muted">{row.modelVersions.join(" · ")}</span></details> : null}{row?.error && <span className="cell-note attention">{row.error}</span>}</td><td>{row?.status ?? "Unavailable"}</td>
        <td className="numeric">{usable ? `$${row.totals.totalSpendUsd.toFixed(4)}` : "—"}</td>{["completedJobs", "missedDeadlines", "failedJobs", "infeasibleJobs", "unfinishedJobs"].map(key => <td key={key} className="numeric">{usable ? row.totals[key as keyof typeof row.totals] : "—"}</td>)}
      </tr>; })}</tbody></table></div>
    {!metrics?.strategies.length && <div className="empty compact-empty"><h3>No comparison results yet</h3><p>Reset and step a replay to obtain spend and workload outcomes.</p></div>}
    </section>;
}
