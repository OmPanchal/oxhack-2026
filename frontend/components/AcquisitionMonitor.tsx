import type { Acquisition } from '@/lib/backend-types';
import type { Job } from '@/lib/types';

export function AcquisitionMonitor({records = [], jobs = []}: {records?: Acquisition[]; jobs?: Job[]}) {
  return <section><div className="panel-heading"><h2>Capacity acquisition & execution</h2><span className="tag">SIMULATED</span></div>
    <p className="panel-body muted">A plan requests capacity. Successful simulated admission starts the job; completion releases its reservation. These are simulated leases, not AWS instances or Docker containers.</p>
    {records.length ? <div className="table-scroll"><table><thead><tr><th>Workload</th><th>Pool</th><th>Units</th><th>Capacity</th><th>Execution status</th><th>Stages</th></tr></thead><tbody>
      {records.slice(-20).map(row => <tr key={row.id}><td>{row.jobId}</td><td>{row.region} · {row.gpuType ?? 'CPU'}</td><td>{row.resourceUnits}</td><td>{row.status === 'COMPLETED' ? 'RELEASED' : row.status}<span className="cell-note muted">Slots {row.requestedAtSlot}–{row.endSlot}</span></td><td>{jobs.find(job => job.id === row.jobId)?.status ?? 'Not reported'}</td><td>{row.stages.map(stage => stage.replaceAll('_', ' ')).join(' → ')}<span className="cell-note muted">{row.reason}</span></td></tr>)}
    </tbody></table></div> : <p className="empty">No acquisition requests yet. Add a job and replan, or wait for the next scheduling tick.</p>}
  </section>;
}
