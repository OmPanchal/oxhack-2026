export function PolicyComparison() {
  return <section><div className="panel-heading"><h2>Policy comparison</h2><span className="muted">NO BENCHMARK RUN</span></div>
    <div className="table-scroll"><table><thead><tr><th>POLICY</th><th className="numeric">SPEND</th><th className="numeric">DONE</th><th className="numeric">MISSED</th><th className="numeric">FAILED</th><th className="numeric">UNFINISHED</th></tr></thead>
      <tbody>{["FIFO", "CHEAPEST_NOW", "OPTIMIZER / NAIVE", "OPTIMIZER / ML"].map(policy => <tr key={policy}><td>{policy}</td>{Array.from({length: 5}, (_, i) => <td key={i} className="numeric muted">—</td>)}</tr>)}</tbody></table></div>
    <div className="empty compact-empty"><h3>No comparison results yet</h3><p>Spend and outcomes will appear together after a benchmark run. The prepared preview does not generate policy results.</p></div>
    <div className="panel-footer">Compare completed workloads, failures and unfinished jobs alongside spend before interpreting savings.</div></section>;
}
