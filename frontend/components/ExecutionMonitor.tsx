export function ExecutionMonitor() {
  return <section><div className="panel-heading"><h2>Execution monitor</h2><span className="muted">IDLE</span></div>
    <div className="log"><p><span className="muted">ADAPTER</span> LOCAL DOCKER</p><p><span className="muted">CONTAINERS</span> —</p>
      <p className="attention">No execution telemetry connected.</p><p className="muted">Awaiting task status, exit codes and logs.</p></div>
    <div className="panel-footer">LOCAL EXECUTION ≠ REGIONAL CLOUD EXECUTION</div></section>;
}
