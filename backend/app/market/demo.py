"""Opt-in, restart-safe, accelerated demonstration; all inputs are SIMULATED."""
from datetime import datetime, timedelta
import hashlib
import json
import math
import time

from app.api.schemas import JobCreate, MarketSnapshot
from app.jobs.store import JobStore


class DemoClock:
    def __init__(self, origin, start_slot, slot_seconds=10, monotonic=time.monotonic):
        if not math.isfinite(slot_seconds) or slot_seconds < 1:
            raise ValueError('Demo slot seconds must be finite and at least one')
        self.origin, self.start_slot, self.slot_seconds = origin, start_slot, slot_seconds
        self.monotonic, self.started = monotonic, monotonic()

    def __call__(self):
        elapsed_hours = (self.monotonic() - self.started) / self.slot_seconds
        return self.origin + timedelta(hours=self.start_slot + elapsed_hours)


class DemoMarket:
    def __init__(self, selections):
        self.selections = list(selections)
        self.capacity = {(s.region, s.resource_type, s.gpu_type.removeprefix('NVIDIA ') or None):
                         32 if s.resource_type == 'CPU' else 8 for s in selections}

    def poll(self, current_slot):
        rows = []
        for s in self.selections:
            gpu = s.gpu_type.removeprefix('NVIDIA ') or None
            phase = int(hashlib.sha256(repr(s.api_key).encode()).hexdigest()[:6], 16)
            base = .04 if s.resource_type == 'CPU' else {
                'T4': .15, 'A10G': .3, 'L4': .4, 'L40S': .6, 'A100': 1.2,
                'H100': 2.2, 'H200': 3., 'B200': 4.}.get(gpu, 1.)
            for slot in range(max(0, current_slot - 168), current_slot + 1):
                price = base * (1 + .1 * math.sin((slot + phase) * math.pi / 12))
                rows.append(MarketSnapshot(slot=slot, region=s.region, resource_type=s.resource_type,
                    gpu_type=gpu, price_usd_per_unit_hour=price,
                    available_units=self.capacity[(s.region, s.resource_type, gpu)],
                    source=f'SIMULATED demo prices and finite capacity; {s.instance_type}; {s.availability_zone}; not AWS inventory',
                    data_kind='SIMULATED'))
        return rows


def prepare_demo(database, service, *, slot_seconds=10, monotonic=time.monotonic):
    if not math.isfinite(slot_seconds) or slot_seconds < 1:
        raise ValueError('Demo slot seconds must be finite and at least one')
    origin = datetime.fromisoformat(service.origin_utc) + timedelta(hours=service.available_from_slot - 168)
    profile = dict(schemaVersion='simulated-acquisition-demo-v1', originUtc=origin.isoformat(),
                   pools=[s.to_dict() for s in service.selections.values()], cpuUnits=32, gpuUnits=8)
    with database.transaction() as connection:
        saved = connection.execute('SELECT payload FROM simulation_config WHERE id=1').fetchone()
        if saved is None:
            if connection.execute('SELECT 1 FROM jobs LIMIT 1').fetchone() or connection.execute('SELECT 1 FROM market_observations LIMIT 1').fetchone():
                raise ValueError('Demo requires its own database; existing non-demo data was preserved')
            connection.execute('INSERT INTO simulation_config VALUES (1, ?)', (json.dumps(profile, sort_keys=True),))
        elif json.loads(saved['payload']) != profile:
            raise ValueError('Demo pool configuration changed; use a new demo database')
        stored = connection.execute('SELECT payload FROM engine_state WHERE id=1').fetchone()
        state = json.loads(stored['payload']) if stored else dict(currentSlot=168, originUtc=origin.isoformat(),
            forecastMode='ML', lastTickAtUtc=None, lastError=None, dataKind='SIMULATED', fingerprint=None)
        state['executionMode'] = 'SIMULATED'
        connection.execute('INSERT INTO engine_state VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (json.dumps(state),))
    source = DemoMarket(service.selections.values())
    clock = DemoClock(origin, state['currentSlot'], slot_seconds, monotonic)
    return source, clock, origin


def seed_demo_jobs(database, slot):
    store = JobStore(database)
    if store.list():
        return
    for id, resource, gpu, duration in [('cpu', 'CPU', None, 1), ('gpu', 'GPU', 'A10G', 2), ('urgent', 'GPU', 'H100', 1)]:
        store.create(JobCreate(id=f'demo-{id}', name=f'Demo {id} workload · SIMULATED', arrival_slot=slot,
            duration_slots=duration, deadline_slot=slot + duration, resource_type=resource,
            gpu_type=gpu, resource_units=1, allowed_regions=['eu-north-1']))
