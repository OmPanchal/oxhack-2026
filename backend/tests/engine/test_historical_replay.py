"""Synthetic test prices only, including OBSERVED schema validation branches.

These fixtures are not empirical prices or benchmark performance evidence.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.database import Database
from app.api.replay_schemas import ReplayScenario, ReplayShockRequest
from app.engine.historical_replay import DESIGN, digest, load_bundle, prepare_bundle
from app.engine.simulator import ReplayService
from app.main import create_app


def dataset(tmp_path, *, kind='OBSERVED', gap=False, units=1):
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    rows = []
    for slot in range(176):
        for gpu, instance, az, base in [('NVIDIA T4', 'g4dn.xlarge', 'eu-north-1a', .05),
                                        ('NVIDIA A10G', 'g5.xlarge', 'eu-north-1b', .2)]:
            missing = gap and slot == 5 and gpu == 'NVIDIA T4'
            price = None if missing else str(round(base + (slot % 11) * .001, 6))
            rows.append(dict(slot=slot, slotStartUtc=(start + timedelta(hours=slot)).isoformat(),
                region='eu-north-1', availabilityZone=az, instanceType=instance, productDescription='Linux/UNIX',
                resourceType='GPU', gpuType=gpu, resourceUnitsPerInstance=units, allocationGranularityUnits=units,
                unit='GPU-hour', dataKind=kind, source='SIMULATED test values; OBSERVED branch validation only',
                priceStatus='INGESTION_GAP' if missing else 'KNOWN', priceUsdPerUnitHour=price,
                priceUsdPerInstanceHour=price))
    directory = tmp_path / 'dataset'
    directory.mkdir()
    raw = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    (directory / 'hourly-prices.jsonl').write_bytes(raw)
    (directory / 'manifest.json').write_text(json.dumps(dict(schemaVersion='hourly-price-data-v1',
        slotDurationSeconds=3600, originUtc=start.isoformat(), endUtc=(start + timedelta(hours=176)).isoformat(),
        rowCount=len(rows), sha256=hashlib.sha256(raw).hexdigest())), encoding='utf-8')
    design = json.loads(DESIGN.read_text())
    design['scoredHours'] = 8
    design_path = tmp_path / 'design.json'
    design_path.write_text(json.dumps(design), encoding='utf-8')
    return directory, design_path


def prepared(tmp_path):
    directory, design = dataset(tmp_path)
    return prepare_bundle(directory, tmp_path / 'prepared', design)


def test_warmup_is_revealed_before_scoring_without_jobs_or_costs(tmp_path):
    path = prepared(tmp_path)
    scenario = load_bundle(path)
    replay = ReplayService(Database(tmp_path / 'replay.sqlite3'), scenarios={scenario.id: scenario})
    reset = replay.reset(scenario.id)
    assert reset.status == 'READY' and reset.start_slot == reset.current_slot == 168
    assert len(reset.observed_market) == 336
    assert max(row.slot for row in reset.observed_market) == 167
    assert all(not run.jobs and not run.charges and not run.model_versions_used for run in reset.strategy_states)
    assert replay.metrics().start_slot == 168
    assert replay.metrics().provenance.dataset_sha256 == scenario.provenance.dataset_sha256
    replay.shock(ReplayShockRequest(kind='PRICE_SPIKE', slot=170, magnitude=2))
    assert replay.state().provenance.price_data_kind == 'OBSERVED_WITH_SIMULATED_SHOCKS'
    assert replay.metrics().provenance.price_data_kind == 'OBSERVED_WITH_SIMULATED_SHOCKS'
    replay.step()
    assert all(row.slot <= 168 for row in replay.state().observed_market)
    assert all(c.slot >= 168 for run in replay.state().strategy_states for c in run.charges)
    with pytest.raises(ValueError, match='scored replay window'):
        ReplayScenario.model_validate({**scenario.model_dump(),
            'jobs': [{**scenario.jobs[0].model_dump(), 'arrival_slot': 0}]})


@pytest.mark.parametrize('options', [dict(kind='SIMULATED'), dict(gap=True), dict(units=2)])
def test_import_rejects_synthetic_missing_or_wrong_granularity_prices(tmp_path, options):
    directory, design = dataset(tmp_path, **options)
    with pytest.raises(ValueError):
        prepare_bundle(directory, tmp_path / 'rejected', design)
    assert not (tmp_path / 'rejected').exists()


def test_bundle_integrity_source_identity_and_model_dates_are_checked(tmp_path):
    path = prepared(tmp_path)
    bundle = json.loads(path.read_text())
    bundle['scenario']['market'][0]['priceUsdPerUnitHour'] = 100
    path.write_text(json.dumps(bundle), encoding='utf-8')
    with pytest.raises(ValueError, match='checksum'):
        load_bundle(path)
    bundle['scenario']['market'][0]['source'] = 'a different AZ'
    bundle['sha256'] = digest({k: v for k, v in bundle.items() if k != 'sha256'})
    path.write_text(json.dumps(bundle), encoding='utf-8')
    with pytest.raises(ValueError, match='fixed pool'):
        load_bundle(path)


def test_missing_historical_data_is_explicit_in_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('COMPUTE_HISTORICAL_REPLAY_FILE', str(tmp_path / 'missing.json'))
    client = TestClient(create_app(tmp_path / 'api.sqlite3', tick_interval_seconds=0))
    rows = client.get('/api/replay/scenarios').json()
    historical = next(row for row in rows if row['id'] == 'historical-t4-a10g')
    assert historical['available'] is False
    assert client.post('/api/replay/reset', json={'scenarioId': historical['id']}).status_code == 404


def test_loaded_historical_replay_uses_real_weights_without_future_price_access(tmp_path, monkeypatch):
    pytest.importorskip('lightgbm')
    from app.engine.ml_integration import ModelLoader, SelectedModelProvider
    scenario = load_bundle(prepared(tmp_path))
    model = ModelLoader().load()
    forecasts = []
    for index in range(2):
        world = scenario.model_copy(deep=True)
        if index:
            for row in world.market:
                if row.slot > 168:
                    row.price_usd_per_unit_hour = 100
        service = ReplayService(Database(tmp_path / f'causal-{index}.sqlite3'),
            scenarios={world.id: world}, forecast_services={'ML': SelectedModelProvider(model)})
        service.reset(world.id)
        first = service.step().strategy_states[-1]
        assert first.status == 'ACTIVE', first.error
        assert first.forecasts and all(f.model_version.startswith('lightgbm-price-') for f in first.forecasts)
        forecasts.append(first.forecasts)
        if index == 0:
            service.step(7)
            metrics = service.metrics()
            assert all(run.status == 'ACTIVE' for run in metrics.strategies)
            assert all(not run.totals.unfinished_jobs for run in metrics.strategies)
            restarted = ReplayService(Database(service.database.path), scenarios={world.id: world},
                forecast_services={'ML': SelectedModelProvider(model)})
            assert restarted.metrics() == metrics
    assert forecasts[0] == forecasts[1]


def test_frozen_benchmark_runs_production_engine_twice(tmp_path):
    pytest.importorskip('lightgbm')
    from app.engine.historical_replay import benchmark_bundle
    result = benchmark_bundle(prepared(tmp_path), tmp_path / 'benchmark')
    assert result['reproducible'] is True
    assert result['fullReplayStatesIdentical'] is True
    assert result['repeatBatchSizes'] == [24, 1]
    assert result['metrics']['status'] == 'COMPLETED'
    assert len(result['metrics']['strategies']) == 4
    assert (tmp_path / 'benchmark/inputs.json').exists()
    assert (tmp_path / 'benchmark/report.json').exists()


def test_fair_suite_saves_all_seeds_and_preserves_mismatched_outcomes(tmp_path):
    pytest.importorskip('lightgbm')
    from copy import deepcopy
    from app.engine.fair_benchmark import SUITE_DESIGN, run_suite, summarize_cases
    directory, _ = dataset(tmp_path)
    design = json.loads(SUITE_DESIGN.read_text())
    design.update(datasetSha256=json.loads((directory / 'manifest.json').read_text())['sha256'],
        scoredStartsUtc=['2026-10-24T00:00:00+00:00'], scoredHours=8, workloadSeeds=[42, 43],
        profiles=[design['profiles'][0]])
    design_path = tmp_path / 'suite-design.json'
    design_path.write_text(json.dumps(design), encoding='utf-8')
    output = tmp_path / 'suite'
    result = run_suite(directory, output, design_path, progress=lambda *a, **k: None)
    assert result['status'] == 'COMPLETED' and result['allCasesReproduced']
    assert result['summary']['caseCount'] == 2
    assert {case['workloadSeed'] for case in result['cases']} == {42, 43}
    assert (output / 'inputs.json').exists()
    assert all((output / 'cases' / case['caseId'] / 'state-1.json').exists() for case in result['cases'])
    assert all(row['totals']['completedJobs'] == 4 for row in result['summary']['strategies'])
    # Cost differences must not become aggregate savings if even one case has
    # different lifecycle outcomes, regardless of the apparent dollar advantage.
    changed = deepcopy(result['cases'])
    pair = changed[0]['metrics']['comparisons'][-1]
    pair.update(comparable=False, reasonCode='DIFFERENT_OUTCOMES', savingsUsd=None, savingsPercent=None)
    aggregate = summarize_cases(changed)['comparisons'][-1]
    assert aggregate['allCasesComparable'] is False
    assert aggregate['savingsUsd'] is aggregate['savingsPercent'] is None
    assert len(aggregate['nonComparableCases']) == 1
    assert aggregate['wins'] + aggregate['ties'] + aggregate['losses'] == 1
    from scripts.audit_fair_benchmark import audit
    receipt = audit(output, directory)
    assert receipt['caseCount'] == 2
    assert receipt['policyJobOutcomesChecked'] == 16
    assert receipt['hindsightJobBoundsChecked'] == 4
    report_path = output / 'report.json'
    original_report = report_path.read_text()
    corrupted = json.loads(original_report)
    corrupted['cases'][0]['hindsightOpportunity']['fullWindowIndividualOpportunityUsd'] += 1
    report_path.write_text(json.dumps(corrupted), encoding='utf-8')
    with pytest.raises(AssertionError):
        audit(output, directory)
    report_path.write_text(original_report, encoding='utf-8')
    # A matching repeat alone is insufficient: corrupt both copies identically
    # and require the independent observed-price reconciliation to reject them.
    first = output / 'cases' / result['cases'][0]['caseId']
    for repeat in range(2):
        path = first / f'state-{repeat}.json'
        state = json.loads(path.read_text())
        state['strategyStates'][0]['charges'][0]['computeUsd'] += 1
        path.write_text(json.dumps(state), encoding='utf-8')
    with pytest.raises(AssertionError):
        audit(output, directory)
    with pytest.raises(ValueError, match='fresh suite output'):
        run_suite(directory, output, design_path)


def test_fair_suite_rejects_duplicate_dates_and_path_like_profile_ids():
    from app.engine.fair_benchmark import SUITE_DESIGN, validate_design
    design = json.loads(SUITE_DESIGN.read_text())
    design['scoredStartsUtc'].append(design['scoredStartsUtc'][0])
    with pytest.raises(ValueError, match='Dates'):
        validate_design(design)
    design = json.loads(SUITE_DESIGN.read_text())
    design['profiles'][0]['id'] = '../other-folder'
    with pytest.raises(ValueError, match='profile'):
        validate_design(design)


def test_mixed_deadlines_have_a_common_arrival_cutoff_and_reproduce():
    from app.engine.historical_replay import generate_jobs, serving_inputs
    from app.market.features import SeriesIdentity
    config, _ = serving_inputs()
    selections = [SeriesIdentity(**s) for s in config['poolSelections'] if s['gpu_type'] == 'NVIDIA T4']
    design = json.loads(DESIGN.read_text())
    design.update(scoredHours=48, completeWithinHours=24, completionWindowsHours=[3, 12, 24], arrivalEveryHours=4)
    first = generate_jobs(design, selections)
    assert first == generate_jobs(design, selections)
    assert {job.deadline_slot - job.arrival_slot for job in first} == {3, 12, 24}
    assert all(job.arrival_slot <= 168 + 24 and job.deadline_slot <= 168 + 48 for job in first)
    assert all(job.duration_slots <= job.deadline_slot - job.arrival_slot for job in first)


def test_hindsight_is_an_independent_lower_bound_not_an_executable_plan():
    from app.engine.fair_benchmark import hindsight_opportunity
    scenario = dict(jobs=[dict(id=name, arrivalSlot=0, durationSlots=1, deadlineSlot=2,
        resourceUnits=1, allowedRegions=['west'], gpuType='T4') for name in ['a', 'b']],
        market=[dict(slot=t, region='west', gpuType='T4', priceUsdPerUnitHour=p) for t, p in [(0, 5), (1, 1)]])
    result = hindsight_opportunity(scenario)
    assert result['independentImmediateComputeUsd'] == 10
    assert result['minimumComputeForAllJobsIgnoringCapacityUsd'] == 2
    assert result['fullWindowIndividualOpportunityUsd'] == 8
    assert [row['bestIndividualStartSlot'] for row in result['jobs']] == [1, 1]
    assert result['ignoresSharedCapacity'] and result['feasibilityNotEstablished']
    assert result['suppliedToPolicies'] is False
    assert 'NOT_ACHIEVABLE_SAVINGS' in result['costBasis']
