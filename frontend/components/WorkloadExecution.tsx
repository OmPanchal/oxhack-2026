import type { Acquisition, LocalExecution } from '@/lib/backend-types';
import type { Decision, Job } from '@/lib/types';
import { workloadExecution } from '@/lib/execution';
import { regionName } from '@/lib/market';

export function WorkloadExecution({job, decision, acquisition, local}: {
  job: Job; decision?: Decision; acquisition?: Acquisition; local?: LocalExecution;
}) {
  const state = workloadExecution(job, decision, acquisition, local);
  const stages = [
    ['Destination selected', !!state.plannedRegion || !!state.region],
    ['Capacity acquired', state.acquired || state.mode === 'LOCAL'],
    ['Running', state.running || state.completed || state.started],
    ['Completed', state.completed],
  ] as const;
  return <section><div className="panel-heading"><h2>Execution status</h2><span className="tag">{job.status}{state.mode ? ` · ${state.mode}` : ''}</span></div>
    <div className="panel-body"><h3>{state.phase}{state.region ? ` in ${regionName(state.region)}` : ''}</h3>
      <p>{state.region ? `${state.routed ? 'Routed to' : 'Allocated in'} ${regionName(state.region)} (${state.region}).`
        : state.plannedRegion ? `Recommended destination: ${regionName(state.plannedRegion)}. Execution location is not confirmed yet.`
        : 'No execution location has been reported.'}</p>
      {state.mode === 'SIMULATED' && <p className="muted">Simulated acquisition and execution; no real cloud instance was launched.</p>}
      {job.status === 'PENDING' && decision?.executionMode === 'PAPER' && <p className="muted">PAPER mode recommends a location but does not execute this job.</p>}
      <ol>{stages.map(([label, reached]) => <li key={label}>{label} · {reached ? 'Reached' : 'Pending'}</li>)}</ol>
      {state.startedAtSlot !== null && <p>Started at slot {state.startedAtSlot}{state.completedAtSlot !== null ? ` · completed at slot ${state.completedAtSlot}` : ''}.</p>}
    </div>
  </section>;
}
