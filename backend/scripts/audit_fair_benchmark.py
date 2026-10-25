"""Independent source/ledger audit for a saved fair benchmark; no model inference."""
import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def audit(suite, dataset):
    report, inputs = read(suite / 'report.json'), read(suite / 'inputs.json')
    assert report['status'] == 'COMPLETED' and report['inputSha256'] == fingerprint(inputs)
    design = report['design']
    expected = set(itertools.product(design['scoredStartsUtc'], [p['id'] for p in design['profiles']], design['workloadSeeds']))
    actual = {(c['scoredStartUtc'], c['profileId'], c['workloadSeed']) for c in report['cases']}
    assert expected == actual and len(actual) == len(report['cases'])
    manifest = read(dataset / 'manifest.json')
    native_origin = datetime.fromisoformat(manifest['originUtc'].replace('Z', '+00:00'))
    selected = {(s['region'], s['availability_zone'], s['instance_type'], s['product_description']):
                s['gpu_type'].removeprefix('NVIDIA ') for s in inputs['servingConfig']['poolSelections']
                if s['gpu_type'] in ['NVIDIA T4', 'NVIDIA A10G']}
    observed, source_hash = {}, hashlib.sha256()
    with (dataset / 'hourly-prices.jsonl').open('rb') as stream:
        for line in stream:
            source_hash.update(line)
            row = json.loads(line)
            key = row['region'], row['availabilityZone'], row['instanceType'], row['productDescription']
            if key in selected and row['priceStatus'] == 'KNOWN':
                assert row['dataKind'] == 'OBSERVED'
                assert row['resourceUnitsPerInstance'] == row['allocationGranularityUnits'] == 1
                observed[row['slot'], row['region'], selected[key]] = Decimal(row['priceUsdPerUnitHour'])
    assert source_hash.hexdigest() == manifest['sha256'] == design['datasetSha256']
    executions = charged_hours = price_rows = jobs_checked = hindsight_jobs = 0
    engine_hashes = None
    aggregate = {}
    for case in report['cases']:
        directory = suite / 'cases' / case['caseId']
        frozen = read(directory / 'inputs.json')
        local_report = read(directory / 'report.json')
        assert fingerprint(frozen) == local_report['inputSha256'] == case['inputSha256']
        assert frozen['seed'] == case['workloadSeed']
        if engine_hashes is None:
            engine_hashes = frozen['productionEngineSha256']
        assert engine_hashes == frozen['productionEngineSha256']
        scenario = frozen['bundle']['scenario']
        offset = int((datetime.fromisoformat(scenario['originUtc'].replace('Z', '+00:00')) - native_origin).total_seconds() / 3600)
        realized = {}
        for row in scenario['market']:
            value = observed[offset + row['slot'], row['region'], row['gpuType']]
            assert value == Decimal(str(row['priceUsdPerUnitHour']))
            assert row['availableUnits'] == 1 and row['dataKind'] == 'SIMULATED'
            realized[row['slot'], row['region'], row['gpuType']] = value
            price_rows += 1
        state = read(directory / 'state-0.json')
        assert state == read(directory / 'state-1.json')
        assert state['currentSlot'] == scenario['endSlot']
        definitions = {j['id']: j for j in scenario['jobs']}
        if 'hindsightOpportunity' in case:
            diagnostic = case['hindsightOpportunity']
            assert diagnostic['usesRealizedFuturePrices'] and diagnostic['suppliedToPolicies'] is False
            assert diagnostic['ignoresSharedCapacity'] and diagnostic['feasibilityNotEstablished']
            assert diagnostic['costBasis'] == 'COMPUTE_ONLY_NOT_ACHIEVABLE_SAVINGS'
            assert {r['jobId'] for r in diagnostic['jobs']} == set(definitions)
            opportunities = []
            for row in diagnostic['jobs']:
                job = definitions[row['jobId']]
                values = []
                for start in range(job['arrivalSlot'], job['deadlineSlot'] - job['durationSlots'] + 1):
                    value = sum(((realized[t, job['allowedRegions'][0], job['gpuType']] * job['resourceUnits']).quantize(Decimal('.000000001'))
                                 for t in range(start, start + job['durationSlots'])), Decimal(0))
                    values.append((value, start))
                best, best_start = min(values)
                assert best == Decimal(str(row['bestIndividualComputeUsd'])) and best_start == row['bestIndividualStartSlot']
                assert values[0][0] == Decimal(str(row['immediateComputeUsd']))
                opportunity = values[0][0] - best
                assert opportunity == Decimal(str(row['fullWindowIndividualOpportunityUsd']))
                short = min(value for value, start in values if start <= job['arrivalSlot'] + 1)
                assert values[0][0] - short == Decimal(str(row['oneHourIndividualOpportunityUsd']))
                covered = [value for value, start in values if start + job['durationSlots'] - 1 <= job['arrivalSlot'] + 6]
                if covered:
                    assert values[0][0] - min(covered) == Decimal(str(row['sixHourIndividualOpportunityUsd']))
                else:
                    assert row['sixHourIndividualOpportunityUsd'] is None
                opportunities.append(opportunity)
                hindsight_jobs += 1
            assert sum(opportunities) == Decimal(str(diagnostic['fullWindowIndividualOpportunityUsd']))
        completed, outcomes, totals = {}, {}, {}
        for run in state['strategyStates']:
            assert run['status'] == 'ACTIVE'
            starts = {}
            for decision in run['decisions']:
                assert decision['decidedAtSlot'] >= scenario['startSlot']
                if decision['action'] in ['RUN', 'ROUTE', 'FALLBACK']:
                    assert decision['jobId'] not in starts
                    starts[decision['jobId']] = decision
            terminal = {o['jobId']: o for o in run['outcomes']}
            occupancy = {}
            spend = Decimal(0)
            for job in run['jobs']:
                jobs_checked += 1
                assert {k: v for k, v in job.items() if k != 'status'} == definitions[job['id']]
                charges = [c for c in run['charges'] if c['jobId'] == job['id']]
                start = starts.get(job['id'])
                if start is None:
                    assert not charges and job['status'] == 'INFEASIBLE'
                    continue
                executions += 1
                assert job['arrivalSlot'] <= start['plannedStartSlot'] < start['plannedEndSlot'] <= job['deadlineSlot']
                assert start['plannedEndSlot'] - start['plannedStartSlot'] == job['durationSlots']
                assert start['region'] in job['allowedRegions']
                end = terminal[job['id']]['slot']
                assert sorted(c['slot'] for c in charges) == list(range(start['plannedStartSlot'], end))
                if job['status'] == 'COMPLETED':
                    assert end == start['plannedEndSlot'] and end <= job['deadlineSlot']
                for charge in charges:
                    assert charge['gpuType'] == job['gpuType']
                    key = charge['slot'], start['region'], charge['gpuType']
                    occupancy[key] = occupancy.get(key, 0) + job['resourceUnits']
                    assert occupancy[key] <= 1
                    cost = (realized[key] * job['resourceUnits']).quantize(Decimal('.000000001'))
                    assert cost == Decimal(str(charge['computeUsd']))
                    assert charge['startupUsd'] == charge['transferUsd'] == charge['carbonUsd'] == 0
                    spend += cost
                    charged_hours += 1
            assert spend == Decimal(str(run['metrics']['totalSpendUsd']))
            assert set(run['missedDeadlineIds']) == {j['id'] for j in run['jobs']
                if j['status'] != 'COMPLETED' and j['deadlineSlot'] <= scenario['endSlot']}
            completed[run['strategy']] = {j['id'] for j in run['jobs'] if j['status'] == 'COMPLETED'}
            outcomes[run['strategy']] = ({j['id']: j['status'] for j in run['jobs']}, set(run['missedDeadlineIds']))
            totals[run['strategy']] = spend
            aggregate[run['strategy']] = aggregate.get(run['strategy'], Decimal(0)) + spend
            official = next(r for r in case['metrics']['strategies'] if r['strategy'] == run['strategy'])
            assert official['totals'] == run['metrics']
            assert set(official['completedJobIds']) == completed[run['strategy']]
            assert official['modelVersions'] == run['modelVersionsUsed']
        ml = state['strategyStates'][-1]
        assert ml['modelVersionsUsed'] and all(v.startswith('lightgbm-price-') for v in ml['modelVersionsUsed'])
        for pair in case['metrics']['comparisons']:
            candidate, baseline = pair['strategy'], pair['baseline']
            comparable = (completed[candidate] == completed[baseline] and outcomes[candidate] == outcomes[baseline]
                          and bool(completed[candidate]))
            assert pair['comparable'] == comparable
            difference = totals[baseline] - totals[candidate]
            assert difference == Decimal(str(pair['costDifferenceUsd']))
            if comparable:
                assert difference == Decimal(str(pair['savingsUsd']))
            else:
                assert pair['savingsUsd'] is pair['savingsPercent'] is None
    for row in report['summary']['strategies']:
        assert aggregate[row['strategy']] == Decimal(str(row['totals']['totalSpendUsd']))
    return dict(status='VERIFIED', caseCount=len(expected), datasetSha256=source_hash.hexdigest(),
        scenarioPriceRowsChecked=price_rows, policyJobOutcomesChecked=jobs_checked,
        policyExecutionsChecked=executions, chargedHoursChecked=charged_hours,
        hindsightJobBoundsChecked=hindsight_jobs,
        fullRepeatedStatesIdentical=True, engineCodeUnchangedAcrossCases=True,
        allScoredMlVersionsGenuine=True, scope='Observed prices; simulated workloads/capacity; reused evaluation periods')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.suite, args.dataset)
    (args.suite / 'audit.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
