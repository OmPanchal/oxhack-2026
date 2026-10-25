import type { ReplayMetrics } from "@/lib/backend-types";
import type { Strategy } from "@/lib/types";
export const policyLabel = (policy: Strategy) => ({ FIFO: "FIFO", CHEAPEST_NOW: "Cheapest now", OPTIMIZER_WITH_NAIVE_FORECAST: "Optimizer / persistence", OPTIMIZER_WITH_ML: "Optimizer / ML" })[policy];
const policies: Strategy[] = ["FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML"];
export function PolicyComparison({ metrics }: { metrics?: ReplayMetrics }) {
  return <section><div className="panel-heading"><h2>Policy comparison</h2><span className="tag">{metrics ? `${metrics.status} · SIMULATED` : "No benchmark results"}</span></div>
    <div className="table-scroll"><table><thead><tr><th>Policy</th><th>Status</th><th className="numeric">Spend</th><th className="numeric">Done</th><th className="numeric">Missed</th><th className="numeric">Failed</th><th className="numeric">Infeasible</th><th className="numeric">Unfinished</th></tr></thead>
      <tbody>{policies.map(policy => { const row = metrics?.strategies.find(row => row.strategy === policy); const usable = !!row && row.status !== "UNAVAILABLE"; return <tr key={policy}><td>{policyLabel(policy)}{row?.error && <span className="cell-note attention">{row.error}</span>}</td><td>{row?.status ?? "Unavailable"}</td>
        <td className="numeric">{usable ? `$${row.totals.totalSpendUsd.toFixed(4)}` : "—"}</td>{["completedJobs", "missedDeadlines", "failedJobs", "infeasibleJobs", "unfinishedJobs"].map(key => <td key={key} className="numeric">{usable ? row.totals[key as keyof typeof row.totals] : "—"}</td>)}
      </tr>; })}</tbody></table></div>
    {!metrics?.strategies.length && <div className="empty compact-empty"><h3>No comparison results yet</h3><p>Reset and step a backend replay to obtain spend and outcomes. Preview examples do not generate benchmarks.</p></div>}
    {metrics?.comparisons.map(row => <p className="panel-body" key={`${row.strategy}-${row.baseline}`}>{policyLabel(row.strategy)} vs {policyLabel(row.baseline)}: {row.comparable && row.savingsUsd !== null ? `${row.savingsUsd >= 0 ? "Savings" : "Additional cost"} $${Math.abs(row.savingsUsd).toFixed(4)}${row.savingsPercent === null ? "" : ` (${row.savingsPercent.toFixed(2)}%)`}. ` : ""}{row.explanation}</p>)}
    <div className="panel-footer">{metrics ? "Backend accounting · simulated realized spend. Savings are shown only when the backend marks outcomes comparable." : "Compare completed workloads, failures and unfinished jobs alongside spend before interpreting savings."}</div></section>;
}
