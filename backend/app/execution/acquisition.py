"""Explicit simulated acquisition leases; never contacts a cloud provider."""
import json
from uuid import uuid4

from app.api.schemas import Contract, Reservation
from app.audit.events import append_event
from app.engine.optimizer import hardware_matches
from app.execution.control import DispatchControl
from app.jobs.store import load_job, write_job
from typing import Literal


class Acquisition(Contract):
    id: str
    job_id: str
    region: str
    resource_type: Literal['CPU', 'GPU']
    gpu_type: str | None
    resource_units: int
    requested_at_slot: int
    end_slot: int
    status: Literal['ACQUIRED', 'REJECTED', 'COMPLETED']
    execution_mode: Literal['SIMULATED'] = 'SIMULATED'
    reason: str
    stages: list[str]


class SimulatedAcquisition:
    """Finite pool admission, followed by duration-based simulated execution.

    Planning creates recommendations; only successful admission creates running
    jobs/reservations. All effects are transactional and restart-safe. No AWS or
    Docker operations exist in this adapter.
    """
    def __init__(self, database, capacity):
        self.database, self.capacity = database, dict(capacity)

    def list(self):
        with self.database.transaction() as connection:
            return [Acquisition.model_validate_json(r['payload']) for r in connection.execute(
                'SELECT payload FROM capacity_acquisitions ORDER BY job_id')]

    def dispatch(self, plan, slot):
        with self.database.transaction() as connection:
            if DispatchControl.read(connection).paused:
                return
            for decision in plan.decisions:
                if decision.execution_mode != 'SIMULATED' or decision.action not in {'RUN', 'ROUTE', 'FALLBACK'}:
                    continue
                job = load_job(connection, decision.job_id)
                if job.status != 'PENDING':
                    continue
                allocation = plan.allocations[job.id]
                if allocation.start_slot != slot or not hardware_matches(job, allocation):
                    continue
                latest = connection.execute('SELECT payload FROM decisions WHERE job_id=? ORDER BY id DESC LIMIT 1', (job.id,)).fetchone()
                if latest is None or json.loads(latest['payload']) != decision.model_dump(mode='json', by_alias=True):
                    continue  # A concurrent replan superseded this recommendation.
                reservations = [Reservation.model_validate_json(r['payload']) for r in connection.execute('SELECT payload FROM reservations')]
                key = allocation.region, allocation.resource_type, allocation.gpu_type
                limit = self.capacity.get(key, 0)
                fits = all(allocation.resource_units + sum(r.resource_units for r in reservations
                    if (r.region, r.resource_type, r.gpu_type) == key and r.start_slot <= t < r.end_slot) <= limit
                    for t in range(slot, allocation.end_slot))
                receipt = Acquisition(id=str(uuid4()), job_id=job.id, region=allocation.region,
                    resource_type=allocation.resource_type, gpu_type=allocation.gpu_type,
                    resource_units=allocation.resource_units, requested_at_slot=slot, end_slot=allocation.end_slot,
                    status='ACQUIRED' if fits else 'REJECTED',
                    stages=['PLANNED', 'ACQUISITION_REQUESTED', 'CAPACITY_ACQUIRED' if fits else 'ACQUISITION_REJECTED'],
                    reason='Finite simulated pool admitted the request' if fits else 'Simulated capacity unavailable; job remains pending')
                if fits:
                    connection.execute('INSERT INTO reservations VALUES (?, ?)', (job.id, allocation.model_dump_json(by_alias=True)))
                    job.status = 'RUNNING'
                    write_job(connection, job)
                    receipt.stages.append('EXECUTION_RUNNING')
                    append_event(connection, 'JOB_STARTED', job.id, allocation.model_dump(mode='json', by_alias=True), 'SIMULATED')
                connection.execute('INSERT INTO capacity_acquisitions VALUES (?, ?) ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload',
                                   (job.id, receipt.model_dump_json(by_alias=True)))
                append_event(connection, 'CAPACITY_ACQUISITION', job.id, receipt.model_dump(mode='json', by_alias=True), 'SIMULATED')

    def poll(self, slot):
        from app.engine.runtime import ExecutionOutcome
        results = []
        with self.database.transaction() as connection:
            for row in connection.execute('SELECT job_id, payload FROM capacity_acquisitions').fetchall():
                receipt = Acquisition.model_validate_json(row['payload'])
                if receipt.status == 'REJECTED' or receipt.end_slot > slot:
                    continue
                if receipt.status != 'COMPLETED':
                    receipt.status = 'COMPLETED'
                    receipt.stages.append('EXECUTION_COMPLETED')
                    connection.execute('UPDATE capacity_acquisitions SET payload=? WHERE job_id=?',
                                       (receipt.model_dump_json(by_alias=True), receipt.job_id))
                # Repeat terminal observations until the scheduler has committed
                # them too; a process crash between these commits cannot lose one.
                results.append(ExecutionOutcome(receipt.job_id, 'COMPLETED', 'SIMULATED', receipt.end_slot,
                                                'SIMULATED_DURATION_ELAPSED'))
        return results
