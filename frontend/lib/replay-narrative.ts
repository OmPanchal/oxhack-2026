import type { Decision, Job, Strategy } from './types';

export const demoPolicies: Strategy[] = ['FIFO', 'CHEAPEST_NOW', 'OPTIMIZER_WITH_ML'];
export const narrativeOrder = ['Workload', 'Decision', 'Outcome', 'Policy comparison'] as const;

export function forecastProvenance(versions: string[], status?: string, preview = false) {
  if (preview) return {label: 'Illustrative preview · no trained inference', detail: 'Hand-authored example; no model was run.'};
  if (status === 'UNAVAILABLE' || status === 'ERROR') return {label: 'Forecasts unavailable', detail: 'This policy has no usable current forecast result. Any retained partial outcomes remain visible.'};
  const names = [...new Set(versions)];
  if (!names.length) return {label: 'No forecast provenance yet', detail: 'No issued forecast versions were supplied.'};
  const ml = names.some(name => /^(lightgbm|xgboost)(-|:)/i.test(name));
  const persistence = names.some(name => /persistence/i.test(name));
  const other = names.some(name => !/^(lightgbm|xgboost)(-|:)/i.test(name) && !/persistence/i.test(name));
  if (ml && (persistence || other)) return {label: 'Mixed forecast use', detail: 'Saved ML predictions were used alongside persistence fallback or other reported providers. Not every prediction is ML.'};
  if (ml) return {label: 'Genuine saved-model ML', detail: 'The backend reports saved LightGBM/XGBoost inference. This does not establish out-of-sample quality.'};
  if (persistence && !other) return {label: 'Persistence fallback · no ML predictions', detail: 'The ML policy used persistence rather than trained-model predictions for the reported forecasts.'};
  return {label: 'Other / unverified forecast provider', detail: 'Reported provider names do not establish genuine saved-model ML inference.'};
}

export function relativeToArrival(slot: number | null | undefined, job?: Job) {
  if (slot == null || !job) return 'Not reported';
  const delta = slot - job.arrivalSlot;
  return delta === 0 ? 'At arrival' : delta > 0 ? `${delta}h after arrival` : `${Math.abs(delta)}h before arrival`;
}

export function conciseAction(decision?: Decision) {
  if (!decision) return 'No decision recorded';
  if (decision.action === 'WAIT') return decision.plannedStartSlot == null ? 'Waiting for a feasible allocation' : 'Wait for the planned window';
  return ({RUN:'Run in the selected region', ROUTE:'Route to another allowed region', FALLBACK:'Use the recorded fallback plan', INFEASIBLE:'No feasible execution window'})[decision.action];
}

export function priorWait(decisions: Decision[], decision?: Decision) {
  if (!decision) return undefined;
  const index = decisions.indexOf(decision);
  const earlier = index >= 0 ? decisions.slice(0,index) : decisions.filter(d => d.decidedAtSlot < decision.decidedAtSlot);
  return earlier.filter(d => d.jobId === decision.jobId && d.action === 'WAIT').at(-1);
}

export function outcomeNarrative(job?: Job, outcome?: {status: string; slot: number; reason: string}) {
  if (!job) return 'No arrived workload or recorded outcome is available for this policy.';
  if (job.status === 'COMPLETED') return outcome?.status === 'COMPLETED'
    ? `Completed ${relativeToArrival(outcome.slot,job).toLowerCase()}.`
    : 'The backend reports COMPLETED, but no completion time was supplied.';
  if (job.status === 'RUNNING') return 'Running; completion has not been recorded.';
  if (job.status === 'PENDING') return 'Pending; execution has not started.';
  if (job.status === 'FAILED') return `Failed; the workload did not complete.${outcome ? ` ${outcome.reason}` : ' No failure time was supplied.'}`;
  return `Infeasible; the workload was not executed.${outcome ? ` ${outcome.reason}` : ''}`;
}
