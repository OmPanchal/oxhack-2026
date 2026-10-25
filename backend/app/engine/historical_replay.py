"""Prepare and benchmark observed fixed-pool prices using the production replay.

No prices are downloaded or invented. Workloads and capacity are synthetic.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import random

from app.api.replay_schemas import ReplayProvenance, ReplayScenario
from app.api.schemas import JobCreate, MarketSnapshot

ROOT = Path(__file__).resolve().parents[3]
DESIGN = ROOT / 'data/historical-replay-design.json'
CONFIG = ROOT / 'data/forecast-serving.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def configured_bundle_path():
    return Path(os.getenv('COMPUTE_HISTORICAL_REPLAY_FILE',
                          str(ROOT / 'data/processed/historical-replay/scenario.json')))


def serving_inputs():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    receipt = json.loads((ROOT / config['artifactReceipt']).read_text(encoding='utf-8'))
    return config, receipt


def generate_jobs(design, selections):
    """Prices never enter workload generation; each case has its own fixed RNG."""
    windows = design.get('completionWindowsHours', [design['completeWithinHours']])
    if (not windows or any(type(w) is not int or not design['durationRangeHours'][1] <= w <= 24 for w in windows)
            or max(windows) != design['completeWithinHours'] or max(windows) > design['scoredHours']):
        raise ValueError('Invalid workload completion windows')
    rng = random.Random(design['workloadSeed'])
    jobs = []
    for identity in selections:
        model = identity.gpu_type.removeprefix('NVIDIA ')
        phase = rng.randrange(len(windows)) if len(windows) > 1 else 0
        for index, elapsed in enumerate(range(0, design['scoredHours'] - max(windows) + 1, design['arrivalEveryHours'])):
            arrival = 168 + elapsed
            window = windows[(index + phase) % len(windows)]
            jobs.append(JobCreate(id=f'historical-{model.lower()}-{elapsed:03}', name=f'{model} batch +{elapsed}h',
                arrival_slot=arrival, duration_slots=rng.randint(*design['durationRangeHours']),
                deadline_slot=arrival + window, resource_type='GPU', resource_units=1,
                gpu_type=model, allowed_regions=[identity.region], priority=0))
    return jobs


def prepare_bundle(dataset_directory: Path, output: Path, design_path: Path = DESIGN):
    # Existing loader verifies the complete input hash, UTC boundaries, unique
    # identities, explicit gaps and OBSERVED prices before any scenario is written.
    from app.forecasting.training_data import load_prepared_dataset
    from app.market.features import SeriesIdentity

    design = json.loads(design_path.read_text(encoding='utf-8'))
    if (design['schemaVersion'] != 'historical-replay-design-v1'
            or design['warmupHours'] != 168 or design['capacityUnitsPerPool'] != 1
            or design['capacityDataKind'] != 'SIMULATED' or design['workloadDataKind'] != 'SIMULATED'
            or design['evaluationStatus'] != 'REUSED_EVALUATION_PERIOD'
            or set(design['gpuTypes']) != {'NVIDIA T4', 'NVIDIA A10G'}
            or type(design['arrivalEveryHours']) is not int or design['arrivalEveryHours'] <= 0
            or type(design['completeWithinHours']) is not int or not 1 <= design['completeWithinHours'] <= 24
            or len(design['durationRangeHours']) != 2
            or not all(type(value) is int for value in design['durationRangeHours'])
            or not 1 <= design['durationRangeHours'][0] <= design['durationRangeHours'][1] <= design['completeWithinHours']):
        raise ValueError('Unsupported historical replay design')
    if output.exists():
        raise ValueError('Use a fresh output directory; historical inputs are never overwritten')
    config, receipt = serving_inputs()
    scored_start = datetime.fromisoformat(design['scoredStartUtc'])
    model_origin = datetime.fromisoformat(config['originUtc'])
    if (scored_start.utcoffset() != timedelta(0) or scored_start.minute or scored_start.second
            or scored_start.microsecond):
        raise ValueError('Scored start must be aligned to a UTC hour')
    native_start = (scored_start - model_origin) // timedelta(hours=1)
    if native_start < config['availableFromSlot']:
        raise ValueError('Scoring cannot precede model availability')
    hours = design['scoredHours']
    if type(hours) is not int or not 6 <= hours <= 168:
        raise ValueError('Scored horizon must contain 6–168 hours')
    dataset = load_prepared_dataset(Path(dataset_directory))
    origin = scored_start - timedelta(hours=168)
    lower = (origin - dataset.origin) // timedelta(hours=1)
    end_slot = 168 + hours
    if lower < 0 or lower + end_slot > dataset.end_slot:
        raise ValueError('Dataset must cover the full 168-hour warm-up and scored window')
    selections = [SeriesIdentity(**row) for row in config['poolSelections']
                  if row['resource_type'] == 'GPU' and row['gpu_type'] in design['gpuTypes']]
    if len(selections) != len(design['gpuTypes']) or len(set(design['gpuTypes'])) != len(selections):
        raise ValueError('Every requested GPU needs one fixed serving-config source')
    by_identity = {series.identity: series for series in dataset.series}
    selected_rows = {}
    # Verify whole-instance granularity, which the generic price-series loader
    # intentionally does not expose. Current sources are single-GPU instances.
    row_digest = hashlib.sha256()
    with (Path(dataset_directory) / 'hourly-prices.jsonl').open('rb') as stream:
        for line in stream:
            row_digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            identity = SeriesIdentity.from_row(row)
            if identity in selections and lower <= row['slot'] < lower + end_slot:
                if (row['resourceUnitsPerInstance'] != 1 or row['allocationGranularityUnits'] != 1
                        or row['unit'] != 'GPU-hour' or row['dataKind'] != 'OBSERVED'
                        or row['priceStatus'] != 'KNOWN' or not row['source'].strip()
                        or row['priceUsdPerUnitHour'] is None or row['priceUsdPerInstanceHour'] is None
                        or Decimal(str(row['priceUsdPerUnitHour'])) != Decimal(str(row['priceUsdPerInstanceHour']))):
                    raise ValueError('Historical replay requires known OBSERVED single-GPU instance prices')
                selected_rows[identity, row['slot']] = row
    if row_digest.hexdigest() != dataset.sha256:
        raise ValueError('Hourly dataset changed during replay preparation')
    market, pools = [], []
    for identity in selections:
        if identity not in by_identity:
            raise ValueError(f'Missing selected price pool: {identity}')
        model = identity.gpu_type.removeprefix('NVIDIA ')
        pool = f'{identity.region}; {identity.instance_type}; {identity.availability_zone}; {identity.product_description}'
        pools.append(pool)
        for slot in range(end_slot):
            original = lower + slot
            price = by_identity[identity].prices.get(original)
            if price is None or price <= 0 or (identity, original) not in selected_rows:
                raise ValueError(f'Missing/unsupported price in {pool} at dataset slot {original}')
            market.append(MarketSnapshot(slot=slot, region=identity.region, resource_type='GPU', gpu_type=model,
                price_usd_per_unit_hour=price, available_units=1, data_kind='SIMULATED',
                source=f'OBSERVED historical AWS price; {pool}; dataset {dataset.sha256}; SIMULATED capacity=1'))
    jobs = generate_jobs(design, selections)
    provenance = ReplayProvenance(dataset_sha256=dataset.sha256, source_pools=pools,
        notes='Historical price availability is assumed at each hourly boundary. '
              'Previously evaluated dates; not fresh held-out accuracy evidence. '
              'Constant one-GPU capacity per fixed pool and all jobs are SIMULATED. No interruptions or recovery.')
    scenario = ReplayScenario(id=design['scenarioId'], origin_utc=origin, start_slot=168, end_slot=end_slot,
        market=market, jobs=jobs, provenance=provenance,
        description=f'Historical T4/A10G prices from {scored_start.isoformat()} for {hours} hours. '
                    '168 prior hours loaded for warm-up; workloads and capacity SIMULATED. '
                    'Reused evaluation period, not a fresh accuracy test or cloud execution.')
    payload = dict(schemaVersion='historical-replay-bundle-v1', design=design,
        selectionConfigSha256=digest(config), modelArtifacts=receipt,
        scenario=scenario.model_dump(mode='json', by_alias=True))
    bundle = {**payload, 'sha256': digest(payload)}
    output.mkdir(parents=True)
    path = output / 'scenario.json'
    path.write_text(json.dumps(bundle, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    # Run the same validation used during application registration.
    load_bundle(path)
    return path


def load_bundle(path: Path):
    bundle = json.loads(Path(path).read_text(encoding='utf-8'))
    expected = bundle.pop('sha256')
    if bundle.get('schemaVersion') != 'historical-replay-bundle-v1' or digest(bundle) != expected:
        raise ValueError('Historical replay bundle checksum/schema mismatch')
    config, receipt = serving_inputs()
    if bundle['selectionConfigSha256'] != digest(config) or bundle['modelArtifacts'] != receipt:
        raise ValueError('Historical replay was prepared for different model sources/artifacts')
    scenario = ReplayScenario.model_validate(bundle['scenario'])
    if scenario.id != 'historical-t4-a10g' or scenario.start_slot != 168 or scenario.provenance is None:
        raise ValueError('Historical replay needs its fixed identity, provenance and 168-hour warm-up')
    scored_start = scenario.origin_utc + timedelta(hours=scenario.start_slot)
    model_origin = datetime.fromisoformat(config['originUtc'])
    if scored_start < model_origin + timedelta(hours=config['availableFromSlot']):
        raise ValueError('Historical replay predates model availability')
    if (scored_start != datetime.fromisoformat(bundle['design']['scoredStartUtc'])
            or scenario.end_slot - scenario.start_slot != bundle['design']['scoredHours']):
        raise ValueError('Historical replay window differs from its frozen design')
    selections = [s for s in config['poolSelections'] if s['resource_type'] == 'GPU'
                  and s['gpu_type'] in bundle['design']['gpuTypes']]
    expected_pools = {(s['region'], s['gpu_type'].removeprefix('NVIDIA ')): s for s in selections}
    if len(expected_pools) != 2:
        raise ValueError('Historical replay requires the two configured GPU pools')
    if {(row.region, row.gpu_type) for row in scenario.market} != set(expected_pools):
        raise ValueError('Historical replay is missing a configured pool')
    for row in scenario.market:
        selection = expected_pools.get((row.region, row.gpu_type))
        if selection is None or row.resource_type != 'GPU' or row.available_units != 1 or row.data_kind != 'SIMULATED':
            raise ValueError('Historical replay changed resource identity or synthetic capacity')
        pool = f"{selection['region']}; {selection['instance_type']}; {selection['availability_zone']}; {selection['product_description']}"
        if row.source != f'OBSERVED historical AWS price; {pool}; dataset {scenario.provenance.dataset_sha256}; SIMULATED capacity=1':
            raise ValueError('Historical replay price source does not match its fixed pool')
    return scenario


def benchmark_bundle(path: Path, output: Path, *, optimizer_config=None):
    from app.database import Database
    from app.engine.ml_integration import ModelLoader, SelectedModelProvider
    from app.engine.simulator import ReplayService
    from app.api.schemas import OptimizerConfig

    scenario = load_bundle(path)
    model = ModelLoader().load()
    if output.exists():
        raise ValueError('Use a fresh benchmark output directory')
    output.mkdir(parents=True)
    # Save the frozen inputs before revealing any benchmark outcomes.
    config = optimizer_config or OptimizerConfig()
    bundle = json.loads(Path(path).read_text(encoding='utf-8'))
    seed = bundle['design']['workloadSeed']
    inputs = dict(bundle=bundle, seed=seed,
        optimizerConfig=config.model_dump(mode='json', by_alias=True),
        productionEngineSha256={p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                                for p in sorted(Path(__file__).parent.glob('*.py'))})
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', encoding='utf-8')
    reports, states = [], []
    for repeat in range(2):
        replay = ReplayService(Database(output / f'repeat-{repeat}.sqlite3'),
            scenarios={scenario.id: scenario}, forecast_services={'ML': SelectedModelProvider(model)}, config=config)
        replay.reset(scenario.id, seed)
        while replay.state().current_slot < scenario.end_slot:
            replay.step(min(24 if repeat == 0 else 1, scenario.end_slot - replay.state().current_slot))
        report = replay.metrics().model_dump(mode='json', by_alias=True)
        ml = report['strategies'][-1]
        if (any(row['status'] != 'ACTIVE' for row in report['strategies']) or not ml['modelVersions']
                or any(not version.startswith('lightgbm-price-') for version in ml['modelVersions'])):
            raise ValueError('Historical benchmark did not use genuine ML throughout; inspect the saved replay database')
        reports.append(report)
        states.append(replay.state().model_dump(mode='json', by_alias=True))
        (output / f'state-{repeat}.json').write_text(json.dumps(states[-1]), encoding='utf-8')
    if reports[0] != reports[1] or states[0] != states[1]:
        raise ValueError('Historical benchmark was not reproducible')
    result = dict(schemaVersion='production-replay-benchmark-v1', seed=seed, reproducible=True,
                  fullReplayStatesIdentical=True, repeatBatchSizes=[24, 1],
                  inputSha256=digest(inputs), optimizerConfig=inputs['optimizerConfig'], metrics=reports[0])
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--dataset', type=Path, required=True)
    prepare.add_argument('--output', type=Path, default=configured_bundle_path().parent)
    prepare.add_argument('--design', type=Path, default=DESIGN)
    benchmark = commands.add_parser('benchmark')
    benchmark.add_argument('--bundle', type=Path, default=configured_bundle_path())
    benchmark.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            print(prepare_bundle(args.dataset, args.output, args.design))
        else:
            result = benchmark_bundle(args.bundle, args.output)
            for row in result['metrics']['strategies']:
                totals = row['totals']
                print(row['strategy'], totals['totalSpendUsd'], totals['completedJobs'], 'completed')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Historical replay rejected: {exc}\n')


if __name__ == '__main__':
    main()
