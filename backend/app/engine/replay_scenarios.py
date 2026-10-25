"""Server-side scenario registry; no frontend-supplied file paths."""
from datetime import datetime, timezone
import json
from pathlib import Path

from app.api.replay_schemas import ReplayScenario
from app.api.schemas import JobCreate, MarketSnapshot


def demo_scenario() -> ReplayScenario:
    path = Path(__file__).resolve().parents[3] / "data" / "scenarios" / "demo.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    jobs = [JobCreate.model_validate({key: value for key, value in row.items() if key != "status"})
            for row in fixture["jobs"]]
    end = max([8] + [job.deadline_slot + 2 for job in jobs])
    base = [MarketSnapshot.model_validate(row) for row in fixture["market"]]
    rows = [row.model_copy(update={"slot": slot, "data_kind": "SIMULATED",
                                  "source": "SIMULATED flat carry-forward of illustrative demo fixture"})
            for slot in range(end) for row in base]
    return ReplayScenario(id="demo", description="Illustrative flat-price SIMULATED scenario; not historical benchmark data",
                          origin_utc=datetime(2000, 1, 1, tzinfo=timezone.utc), end_slot=end, jobs=jobs, market=rows)


def capacity_pressure_scenario() -> ReplayScenario:
    """Fixed synthetic pools; future capacity is never supplied to forecasting."""
    north, central = 'eu-north-1', 'eu-central-1'

    def workload(id, name, *, units=1, duration=1, deadline=6, arrival=0,
                 regions=None, models=None, priority=0):
        return JobCreate(id=id, name=name, arrival_slot=arrival, duration_slots=duration,
            deadline_slot=deadline, resource_type='GPU', resource_units=units,
            allowed_regions=regions or [north], allowed_gpu_types=models or ['A10G'], priority=priority)

    jobs = [
        workload('urgent-a', 'Urgent training A', duration=3, deadline=3, priority=9),
        workload('urgent-b', 'Competing training B', duration=3, deadline=4, priority=8),
        workload('route-job', 'Region-flexible inference', duration=2, deadline=3, regions=[north, central]),
        workload('gpu-choice', 'GPU-flexible batch', duration=2, deadline=4, models=['A10G', 'T4']),
        workload('needs-two', 'Two-GPU batch', units=2, arrival=1, deadline=6),
        workload('oversized', 'Oversized three-GPU job', units=3, deadline=3),
        workload('late-arrival', 'Later inference request', duration=2, arrival=3, deadline=7, regions=[central]),
    ]
    pools = [
        (north, 'A10G', .4, [2, 1, 0, 1, 2, 2, 2, 2]),
        (north, 'T4', .2, [1] * 8),
        (central, 'A10G', .65, [1] * 8),
    ]
    market = [MarketSnapshot(slot=slot, region=region, resource_type='GPU', gpu_type=gpu,
        price_usd_per_unit_hour=price, available_units=capacity, carbon_kg_per_unit_hour=None,
        source='SIMULATED capacity-pressure-v1; hand-authored GPU pool capacity and illustrative prices; not AWS inventory',
        data_kind='SIMULATED')
        for region, gpu, price, capacities in pools for slot, capacity in enumerate(capacities)]
    return ReplayScenario(id='capacity-pressure', origin_utc=datetime(2000, 1, 1, tzinfo=timezone.utc),
        end_slot=8, jobs=jobs, market=market,
        description='SIMULATED GPU capacity pressure: competing workloads, pool shortages and recovery, '
                    'alternative regions/models and an oversized job. All prices and capacity are illustrative; not live AWS.')
