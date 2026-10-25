import type { ReplayStrategy } from '@/lib/backend-types';
import type { Decision, Job, MarketSnapshot } from '@/lib/types';
import { conciseAction, forecastProvenance, outcomeNarrative, priorWait, relativeToArrival } from '@/lib/replay-narrative';
import { jobHardware } from '@/lib/workloads';
import { regionName } from '@/lib/market';

export function ReplayNarrative({run, job, decision, market = [], preview = false, children, decisionDetails}: {
  run?: Pick<ReplayStrategy, 'strategy' | 'status' | 'error' | 'decisions' | 'forecasts' | 'outcomes' | 'modelVersionsUsed'>; job?: Job; decision?: Decision; market?: MarketSnapshot[]; preview?: boolean; children?: React.ReactNode; decisionDetails?: React.ReactNode;
}) {
  const versions = [...(run?.modelVersionsUsed ?? []), ...(run?.forecasts.map(f=>f.modelVersion) ?? [])];
  const provenance = forecastProvenance(versions,run?.status,preview);
  const earlierWait = priorWait(run?.decisions ?? [], decision);
  const outcome = run?.outcomes.filter(o=>o.jobId===job?.id).at(-1);
  const kinds = [...new Set(market.map(r=>r.dataKind))];
  const usable = run?.status === 'ACTIVE';
  return <div className="guided-narrative replay-card-list" aria-label="Workload, decision, outcome and policy comparison">
    <section className="replay-narrative-card" aria-labelledby="narrative-workload"><div className="panel-heading"><h2 id="narrative-workload">Workload</h2><span className="tag">{preview ? 'Illustrative preview' : 'Backend replay'}</span></div>
      <div className="panel-body">{children}{job ? <><h3>{job.name}</h3><dl className="key-values">
        <div><dt>Required hardware</dt><dd>{job.resourceUnits} × {jobHardware(job)}</dd></div><div><dt>Execution duration</dt><dd>{job.durationSlots}h</dd></div>
        <div><dt>Completion window</dt><dd>{job.deadlineSlot-job.arrivalSlot}h from arrival</dd></div><div><dt>Allowed regions</dt><dd>{job.allowedRegions.map(regionName).join(', ')}</dd></div>
      </dl><p className="form-note">The completion window includes both waiting and execution, measured from arrival—not from when execution starts.</p></> : <p className="empty">No workload has arrived for this policy yet. Start or advance replay to reveal recorded work.</p>}</div>
    </section>
    <section className="replay-narrative-card" aria-labelledby="narrative-decision"><div className="panel-heading"><h2 id="narrative-decision">Decision</h2><span className="tag">{usable ? decision?.action ?? 'No decision yet' : run?.status ?? 'Unavailable'}</span></div>
      <div className="panel-body"><h3>{usable ? conciseAction(decision) : 'Policy result unavailable'}</h3>
        {!usable && <p className="attention">{run?.error ?? 'No policy result has been supplied. No substitute result is shown.'}</p>}
        {usable && decision && <dl className="key-values"><div><dt>Selected region</dt><dd>{decision.region ? regionName(decision.region) : 'Not selected'}</dd></div>
          <div><dt>Planned start</dt><dd>{relativeToArrival(decision.plannedStartSlot,job)}</dd></div><div><dt>Predicted job cost</dt><dd>{decision.projectedCostUsd == null ? 'Not reported' : `$${decision.projectedCostUsd.toFixed(4)}`}</dd></div></dl>}
        {earlierWait && <p>Earlier, the backend chose WAIT {relativeToArrival(earlierWait.decidedAtSlot,job).toLowerCase()} before this decision.</p>}
        <p className="form-note">Predicted job cost is a forecast, not realized spend.</p>
        {run?.strategy === 'OPTIMIZER_WITH_ML' || preview ? <div className="replay-provenance"><strong>{provenance.label}</strong><p>{provenance.detail}</p></div> : null}
        {decisionDetails}
      </div>
    </section>
    <section className="replay-narrative-card" aria-labelledby="narrative-outcome"><div className="panel-heading"><h2 id="narrative-outcome">Outcome</h2><span className="tag">{job?.status ?? 'Not available'}</span></div>
      <div className="panel-body"><h3>{outcomeNarrative(job,outcome)}</h3>{job && <dl className="key-values"><div><dt>Recorded completion</dt><dd>{outcome?.status === 'COMPLETED' && job.status === 'COMPLETED' ? relativeToArrival(outcome.slot,job) : 'Not recorded'}</dd></div>
        <div><dt>Deadline</dt><dd>{job.deadlineSlot-job.arrivalSlot}h after arrival · slot {job.deadlineSlot}</dd></div></dl>}
        {!usable && job && <p className="attention">This is retained backend job state. The policy is {run?.status ?? 'unavailable'}; do not interpret partial outcomes as a successful comparison.</p>}
        <p className="form-note">{preview ? 'Hand-authored storyboard; no real execution occurred.' : `Replay execution is SIMULATED. Market inputs: ${kinds.length ? kinds.join(' / ') : 'not yet supplied'}. No cloud or Docker workload is launched by replay.`}</p>
      </div>
    </section>
  </div>;
}
