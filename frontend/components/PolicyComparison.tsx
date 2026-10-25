import type { ReplayMetrics } from "@/lib/backend-types";
import { forecastProvenance, demoPolicies } from "@/lib/replay-narrative";
import type { Strategy } from "@/lib/types";
export const policyLabel = (policy: Strategy) => ({ FIFO: "FIFO", CHEAPEST_NOW: "Cheapest now", OPTIMIZER_WITH_NAIVE_FORECAST: "Optimizer / persistence", OPTIMIZER_WITH_ML: "Optimizer / ML" })[policy];
const policies = demoPolicies;
export function PolicyComparison({ metrics }: { metrics?: ReplayMetrics }) {
  return <section className="replay-comparison"><div className="panel-heading"><h2>Policy comparison</h2><span className="tag">{metrics ? `${metrics.status} · SIMULATED` : "No benchmark results"}</span></div>
    <p className="panel-body muted">{metrics ? "Recorded replay results · simulated workloads and capacity. These are replay costs, not actual cloud spend." : "Backend replay results will appear here when available."}</p>
    <div className="table-scroll"><table><thead><tr><th>Policy</th><th>Status</th><th className="numeric">Spend</th><th className="numeric">Completed</th><th className="numeric">Missed deadlines</th><th className="numeric">Failures</th><th className="numeric">Infeasible</th><th className="numeric">Unfinished</th></tr></thead>
      <tbody>{policies.map(policy => { const row = metrics?.strategies.find(row => row.strategy === policy); const usable = !!row && row.status !== "UNAVAILABLE"; return <tr key={policy}><td>{policyLabel(policy)}{policy === "OPTIMIZER_WITH_ML" && <span className="cell-note muted">{forecastProvenance(row?.modelVersions ?? [], row?.status).label}</span>}{row?.modelVersions?.length ? <span className="cell-note muted"><details className="model-version-details"><summary>Model versions</summary>{row.modelVersions.join(" · ")}</details></span> : null}{row?.error && <span className="cell-note attention">{row.error}</span>}</td><td>{row?.status ?? "Unavailable"}</td>
        <td className="numeric">{usable ? `$${row.totals.totalSpendUsd.toFixed(4)}` : "—"}</td>{["completedJobs", "missedDeadlines", "failedJobs", "infeasibleJobs", "unfinishedJobs"].map(key => <td key={key} className="numeric">{usable ? row.totals[key as keyof typeof row.totals] : "—"}</td>)}
      </tr>; })}</tbody></table></div>
    {!metrics?.strategies.length && <div className="empty compact-empty"><h3>No comparison results yet</h3><p>Start and advance a backend replay to obtain spend and outcomes. Preview examples do not generate benchmarks.</p></div>}
  </section>;
}
