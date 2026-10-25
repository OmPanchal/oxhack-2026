"""Replay one explicitly selected historical ML success; not a fair benchmark."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.schemas import OptimizerConfig
from app.engine.historical_replay import ROOT, benchmark_bundle, digest, load_bundle


CASE = '20261015T00-flexible-seed-44'
SOURCE = ROOT / 'data/processed/flexible-workload-legacy-001/scenarios' / f'{CASE}.json'
DISCLOSURE = (
    'SELECTED SUCCESS EXAMPLE: chosen retrospectively from the 27-case legacy '
    'flexible-workload suite because ML won. Observed prices; simulated jobs and '
    'capacity. Reused evaluation period, not held-out evidence or general savings. '
    'Uses LEGACY waiting, not the active CAUTIOUS policy. Full-suite results '
    'remain in docs/FLEXIBLE_WORKLOAD_EXPERIMENT.md.'
)


def run(output):
    # All observations and jobs remain unchanged. Label selection before replay.
    load_bundle(SOURCE)
    if output.exists():
        raise ValueError('Use a fresh output directory; saved demos are never overwritten')
    bundle = json.loads(SOURCE.read_text(encoding='utf-8'))
    bundle.pop('sha256')
    bundle['scenario']['description'] = DISCLOSURE + ' ' + bundle['scenario']['description']
    bundle['scenario']['provenance']['notes'] = DISCLOSURE + ' ' + bundle['scenario']['provenance']['notes']
    bundle['sha256'] = digest(bundle)
    output.mkdir(parents=True)
    scenario = output / 'scenario.json'
    scenario.write_text(json.dumps(bundle, indent=2) + '\n', encoding='utf-8')
    report = benchmark_bundle(scenario, output / 'replay',
                              optimizer_config=OptimizerConfig(waiting_policy='LEGACY'))
    comparisons = [c for c in report['metrics']['comparisons']
                   if c['strategy'] == 'OPTIMIZER_WITH_ML']
    if len(comparisons) != 3 or any(not c['comparable'] or not c['allJobsCompleted']
                                  or c['savingsUsd'] <= 0 for c in comparisons):
        raise ValueError('Selected example no longer wins fairly; inspect saved results')
    state = json.loads((output / 'replay/state-0.json').read_text(encoding='utf-8'))
    fifo, ml = state['strategyStates'][0], state['strategyStates'][-1]
    job_comparisons = []
    for job in fifo['jobs']:
        before = [c for c in fifo['charges'] if c['jobId'] == job['id']]
        after = [c for c in ml['charges'] if c['jobId'] == job['id']]
        first = sum((Decimal(str(c['computeUsd'])) for c in before), Decimal(0))
        second = sum((Decimal(str(c['computeUsd'])) for c in after), Decimal(0))
        job_comparisons.append(dict(jobId=job['id'], arrivalSlot=job['arrivalSlot'],
            durationSlots=job['durationSlots'], deadlineSlot=job['deadlineSlot'],
            fifoChargedSlots=[c['slot'] for c in before], mlChargedSlots=[c['slot'] for c in after],
            fifoComputeUsd=float(first), mlComputeUsd=float(second), savingsUsd=float(first-second)))
    summary = dict(disclosure=DISCLOSURE, selectedCaseId=CASE,
                   sourceScenario=str(SOURCE.relative_to(ROOT)),
                   optimizerConfig=report['optimizerConfig'],
                   reproducible=report['reproducible'],
                   fullReplayStatesIdentical=report['fullReplayStatesIdentical'],
                   strategies=[dict(strategy=r['strategy'], modelVersions=r['modelVersions'],
                                    totals=r['totals']) for r in report['metrics']['strategies']],
                   comparisons=comparisons, jobComparisons=job_comparisons)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(DISCLOSURE)
    for row in summary['strategies']:
        print(row['strategy'], row['totals']['totalSpendUsd'],
              row['totals']['completedJobs'], 'completed')
    print('Evidence:', output)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve())
