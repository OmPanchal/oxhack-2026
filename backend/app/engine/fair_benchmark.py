"""Frozen multi-case comparison of the four production scheduling policies."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import importlib.metadata
import json
from pathlib import Path
import re
import sys

from app.engine.historical_replay import (ROOT, DESIGN, benchmark_bundle, digest,
    generate_jobs, prepare_bundle, serving_inputs)

SUITE_DESIGN = ROOT / 'data/fair-benchmark-design.json'


def validate_design(design):
    if (design['schemaVersion'] != 'fair-production-benchmark-v1' or design['repeats'] != 2
            or design['warmupHours'] != 168 or design['capacityUnitsPerPool'] != 1
            or design['priceDataKind'] != 'OBSERVED' or design['capacityDataKind'] != 'SIMULATED'
            or design['evaluationStatus'] != 'EXPLORATORY_REUSED_PERIODS'
            or type(design['scoredHours']) is not int or not 6 <= design['scoredHours'] <= 168):
        raise ValueError('Unsupported fair benchmark design')
    dates = [datetime.fromisoformat(value) for value in design['scoredStartsUtc']]
    if not dates or dates != sorted(set(dates)) or any(
            date.utcoffset() != timedelta(0) or date.minute or date.second or date.microsecond for date in dates):
        raise ValueError('Dates must be unique, sorted, aligned UTC hours')
    seeds = design['workloadSeeds']
    if not seeds or len(set(seeds)) != len(seeds) or any(type(s) is not int or not 0 <= s < 2**31 for s in seeds):
        raise ValueError('Workload seeds must be unique nonnegative integers')
    profiles = design['profiles']
    if not profiles or len({p['id'] for p in profiles}) != len(profiles):
        raise ValueError('Workload profiles must have unique IDs')
    for profile in profiles:
        durations = profile['durationRangeHours']
        if (not re.fullmatch(r'[a-z][a-z0-9-]*', profile['id'])
                or type(profile['arrivalEveryHours']) is not int or profile['arrivalEveryHours'] <= 0
                or type(profile['completeWithinHours']) is not int or not 1 <= profile['completeWithinHours'] <= 24
                or len(durations) != 2 or any(type(d) is not int for d in durations)
                or not 1 <= durations[0] <= durations[1] <= profile['completeWithinHours']):
            raise ValueError('Invalid workload profile')
        windows = profile.get('completionWindowsHours', [profile['completeWithinHours']])
        if (not windows or any(type(w) is not int or not durations[1] <= w <= 24 for w in windows)
                or max(windows) != profile['completeWithinHours'] or max(windows) > design['scoredHours']):
            raise ValueError('Invalid mixed workload completion windows')
    return dates


def amount(values):
    return float(sum((Decimal(str(value)) for value in values), Decimal(0)))


def hindsight_opportunity(scenario):
    """Optimistic per-job price diagnostic; never a forecast or feasible plan.

    Uses realized future prices after replay, independently minimizes every job,
    and deliberately ignores shared capacity. All submitted jobs are included.
    """
    prices = {(r['slot'], r['region'], r['gpuType']): Decimal(str(r['priceUsdPerUnitHour']))
              for r in scenario['market']}
    rows = []
    for job in scenario['jobs']:
        arrival, duration = job['arrivalSlot'], job['durationSlots']
        region, gpu = job['allowedRegions'][0], job['gpuType']
        latest = job['deadlineSlot'] - duration
        def cost(start):
            return sum(((prices[t, region, gpu] * job['resourceUnits']).quantize(Decimal('.000000001'))
                        for t in range(start, start + duration)), Decimal(0))
        immediate = cost(arrival)
        choices = [(cost(start), start) for start in range(arrival, latest + 1)]
        best, best_start = min(choices)
        one_hour = min(value for value, start in choices if start <= arrival + 1)
        six_hour = min((value for value, start in choices if start + duration - 1 <= arrival + 6), default=None)
        rows.append(dict(jobId=job['id'], immediateComputeUsd=float(immediate),
            bestIndividualComputeUsd=float(best), bestIndividualStartSlot=best_start,
            oneHourIndividualOpportunityUsd=float(immediate - one_hour),
            sixHourIndividualOpportunityUsd=float(immediate - six_hour) if six_hour is not None else None,
            fullWindowIndividualOpportunityUsd=float(immediate - best)))
    return dict(kind='HINDSIGHT_INDEPENDENT_JOB_LOWER_BOUND', usesRealizedFuturePrices=True,
        costBasis='COMPUTE_ONLY_NOT_ACHIEVABLE_SAVINGS',
        suppliedToPolicies=False, ignoresSharedCapacity=True, feasibilityNotEstablished=True,
        allSubmittedJobsIncluded=True, jobCount=len(rows),
        independentImmediateComputeUsd=amount(r['immediateComputeUsd'] for r in rows),
        minimumComputeForAllJobsIgnoringCapacityUsd=amount(r['bestIndividualComputeUsd'] for r in rows),
        oneHourIndividualOpportunityUsd=amount(r['oneHourIndividualOpportunityUsd'] for r in rows),
        sixHourIndividualOpportunityUsd=(amount(r['sixHourIndividualOpportunityUsd'] for r in rows)
            if all(r['sixHourIndividualOpportunityUsd'] is not None for r in rows) else None),
        fullWindowIndividualOpportunityUsd=amount(r['fullWindowIndividualOpportunityUsd'] for r in rows),
        jobsWithCheaperFutureWindow=sum(r['fullWindowIndividualOpportunityUsd'] > 0 for r in rows), jobs=rows)


def summarize_cases(cases):
    """Keep every case; aggregate savings only when every outcome is comparable."""
    strategies = {}
    pairs = {}
    for case in cases:
        for row in case['metrics']['strategies']:
            entry = strategies.setdefault(row['strategy'], dict(strategy=row['strategy'], totals={},
                modelVersions=set(), errorCaseIds=[]))
            entry['modelVersions'].update(row['modelVersions'])
            if row['status'] != 'ACTIVE':
                entry['errorCaseIds'].append(case['caseId'])
            for key in row['totals']:
                entry['totals'].setdefault(key, []).append(row['totals'][key])
        for comparison in case['metrics']['comparisons']:
            key = comparison['strategy'], comparison['baseline']
            pairs.setdefault(key, []).append((case['caseId'], comparison))
    for entry in strategies.values():
        entry['modelVersions'] = sorted(entry['modelVersions'])
        entry['totals'] = {key: amount(values) if key.endswith('Usd') else sum(values)
                           for key, values in entry['totals'].items()}
    comparisons = []
    for (strategy, baseline), rows in pairs.items():
        matched = [row for _, row in rows if row['comparable']]
        blocked = [dict(caseId=case_id, reasonCode=row['reasonCode'])
                   for case_id, row in rows if not row['comparable']]
        valid = not blocked and len(rows) == len(cases)
        baseline_spend = strategies[baseline]['totals']['totalSpendUsd']
        difference = amount([baseline_spend, -strategies[strategy]['totals']['totalSpendUsd']])
        percent = float((Decimal(str(difference)) / Decimal(str(baseline_spend)) * 100).quantize(
            Decimal('.000001'), rounding=ROUND_HALF_EVEN)) if valid and baseline_spend else None
        comparisons.append(dict(strategy=strategy, baseline=baseline, allCasesComparable=valid,
            comparableCases=len(matched), nonComparableCases=blocked,
            wins=sum(row['savingsUsd'] > 0 for row in matched),
            ties=sum(row['savingsUsd'] == 0 for row in matched),
            losses=sum(row['savingsUsd'] < 0 for row in matched),
            rawCostDifferenceUsd=difference, savingsUsd=difference if valid else None,
            savingsPercent=percent,
            comparableCasesOnlySavingsUsd=amount(row['savingsUsd'] for row in matched) if matched else None))
    return dict(caseCount=len(cases), strategies=list(strategies.values()), comparisons=comparisons)


def run_suite(dataset_directory: Path, output: Path, design_path: Path = SUITE_DESIGN, *, progress=print):
    from app.market.features import SeriesIdentity
    from app.api.schemas import OptimizerConfig
    design = json.loads(design_path.read_text(encoding='utf-8'))
    dates = validate_design(design)
    optimizer_config = OptimizerConfig.model_validate(design.get('optimizerConfig', {}))
    manifest = json.loads((dataset_directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['sha256'] != design['datasetSha256']:
        raise ValueError('Dataset fingerprint differs from the frozen suite design')
    if output.exists():
        raise ValueError('Use a fresh suite output directory; previous results are never overwritten')
    config, receipt = serving_inputs()
    inputs = dict(design=design, designSha256=digest(design), datasetSha256=manifest['sha256'],
        servingConfig=config, modelArtifacts=receipt, pythonVersion=sys.version,
        packageVersions={name: importlib.metadata.version(name) for name in ['lightgbm', 'numpy', 'scikit-learn']})
    output.mkdir(parents=True)
    # This receipt is committed to disk before any case is scored.
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', encoding='utf-8')
    (output / 'scenarios').mkdir()
    results = []
    total = len(dates) * len(design['profiles']) * len(design['workloadSeeds'])
    selections = [SeriesIdentity(**s) for s in config['poolSelections']
                  if s['resource_type'] == 'GPU' and s['gpu_type'] in ['NVIDIA T4', 'NVIDIA A10G']]
    base_design = json.loads(DESIGN.read_text(encoding='utf-8'))
    for date in dates:
        date_id = date.strftime('%Y%m%dT%H')
        template_design = {**base_design, 'scoredStartUtc': date.isoformat(), 'scoredHours': design['scoredHours']}
        template_path = output / f'prepare-{date_id}.json'
        template_path.write_text(json.dumps(template_design), encoding='utf-8')
        template = json.loads(prepare_bundle(dataset_directory, output / f'prices-{date_id}', template_path).read_text())
        for profile in design['profiles']:
            for seed in design['workloadSeeds']:
                case_id = f'{date_id}-{profile["id"]}-seed-{seed}'
                bundle = deepcopy(template)
                case_design = {**template_design, **{k: v for k, v in profile.items() if k != 'id'}, 'workloadSeed': seed}
                bundle['design'] = case_design
                bundle['scenario']['jobs'] = [job.model_dump(mode='json', by_alias=True)
                                               for job in generate_jobs(case_design, selections)]
                bundle['scenario']['description'] += f' Profile {profile["id"]}; workload seed {seed}.'
                bundle['sha256'] = digest({k: v for k, v in bundle.items() if k != 'sha256'})
                path = output / 'scenarios' / f'{case_id}.json'
                path.write_text(json.dumps(bundle), encoding='utf-8')
                progress(f'{len(results) + 1}/{total}: {case_id}', flush=True)
                try:
                    report = benchmark_bundle(path, output / 'cases' / case_id, optimizer_config=optimizer_config)
                except Exception as exc:
                    failure = dict(status='INCOMPLETE', failedCaseId=case_id, error=str(exc), completedCaseIds=[c['caseId'] for c in results])
                    (output / 'failure.json').write_text(json.dumps(failure, indent=2), encoding='utf-8')
                    raise
                metrics = report['metrics']
                compact = {**metrics, 'strategies': [{k: v for k, v in row.items() if k != 'jobs'}
                                                     for row in metrics['strategies']]}
                results.append(dict(caseId=case_id, scoredStartUtc=date.isoformat(), profileId=profile['id'],
                    workloadSeed=seed, workloadCount=len(bundle['scenario']['jobs']),
                    reproducible=report['reproducible'], fullReplayStatesIdentical=report['fullReplayStatesIdentical'],
                    inputSha256=report['inputSha256'], metrics=compact,
                    hindsightOpportunity=hindsight_opportunity(bundle['scenario'])))
    result = dict(schemaVersion='fair-production-benchmark-results-v1', status='COMPLETED',
        inputSha256=digest(inputs), design=design, provenance=inputs,
        allCasesReproduced=all(case['reproducible'] and case['fullReplayStatesIdentical'] for case in results),
        summary=summarize_cases(results), cases=results)
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--design', type=Path, default=SUITE_DESIGN)
    args = parser.parse_args()
    try:
        result = run_suite(args.dataset, args.output, args.design)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Benchmark rejected: {exc}\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
