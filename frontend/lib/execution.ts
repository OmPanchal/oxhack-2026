import type { Acquisition, LocalExecution } from './backend-types';
import type { Decision, Job } from './types';

// Presentation of reported execution facts, never an inferred status transition.
export function workloadExecution(job: Job, decision?: Decision, acquisition?: Acquisition, local?: LocalExecution) {
  const receipt = acquisition?.jobId === job.id ? acquisition : undefined;
  const record = local?.jobId === job.id ? local : undefined;
  const acquired = !!receipt && ['ACQUIRED', 'COMPLETED'].includes(receipt.status);
  const localStarted = !!record?.startedAtUtc;
  const region = acquired ? receipt!.region : localStarted ? record!.region : null;
  const plannedRegion = decision?.jobId === job.id ? decision.region : null;
  const mode = acquired ? receipt!.executionMode : localStarted ? record!.executionMode : undefined;
  const phase = job.status === 'COMPLETED' ? 'Completed' : job.status === 'RUNNING' ? 'Running'
    : job.status === 'FAILED' ? 'Failed' : job.status === 'INFEASIBLE' ? 'Infeasible'
    : job.dockerTaskId ? 'Pending local execution'
    : receipt?.status === 'REJECTED' ? 'Capacity request rejected'
    : decision?.action === 'WAIT' ? 'Waiting' : plannedRegion ? 'Awaiting acquisition' : 'Awaiting plan';
  return { phase, region, plannedRegion, mode,
    startedAtSlot: acquired ? receipt!.requestedAtSlot : null,
    completedAtSlot: job.status === 'COMPLETED' && receipt?.status === 'COMPLETED' ? receipt.endSlot : null,
    routed: !!region && region !== job.allowedRegions[0],
    acquired, started: (acquired && receipt!.stages.includes('EXECUTION_RUNNING')) || localStarted,
    running: job.status === 'RUNNING', completed: job.status === 'COMPLETED' };
}
