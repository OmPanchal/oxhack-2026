import type { ExecutionView } from "@/lib/replay-view";

export function ExecutionMonitor({ execution, preview = false }: { execution?: ExecutionView; preview?: boolean }) {
  return <section aria-labelledby="execution-heading">
    <div className="panel-heading"><h2 id="execution-heading">Execution monitor</h2><span className="tag">{execution ? `${preview ? "Example · " : ""}${execution.status}` : "No telemetry"}</span></div>
    {!execution ? <p className="empty">No execution telemetry connected. Task status, timestamps, exit codes and logs are unavailable.</p> : <>
      <div className="panel-body"><p>{execution.taskName}</p><p className="muted">{execution.jobId} · {execution.mode}</p></div>
      <dl className="key-values"><div><dt>Started</dt><dd>{execution.startedAt ?? "Not started"}</dd></div><div><dt>Finished</dt><dd>{execution.completedAt ?? "—"}</dd></div><div><dt>Exit code</dt><dd>{execution.exitCode ?? "—"}</dd></div><div><dt>Result</dt><dd>{execution.status === "COMPLETED" ? "Completed" : execution.status === "FAILED" ? "Failed · unfinished" : "Not completed"}</dd></div></dl>
      {execution.failureReason && <p className="execution-failure attention" role="status">{execution.failureReason}</p>}
      <details className="execution-logs" open><summary>{preview ? "Example task logs" : "Task logs"}</summary>
        <h3>Standard output</h3><pre>{execution.stdout.length ? execution.stdout.join("\n") : "No output available."}</pre>
        <h3>Standard error</h3><pre>{execution.stderr.length ? execution.stderr.join("\n") : "No error output available."}</pre>
      </details>
    </>}
    <div className="panel-footer">{preview ? "Illustrative states and logs. No Docker container or cloud task ran." : "LOCAL identifies local Docker execution; a region label does not establish cloud execution."}</div>
  </section>;
}
