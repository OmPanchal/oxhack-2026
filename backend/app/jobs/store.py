"""Persistent jobs, validated lifecycle changes, and scheduling decision history."""
import sqlite3

from app.api.schemas import Decision, ExecutionMode, Job, JobCreate, JobStatus, Reservation
from app.audit.events import append_event
from app.database import Database

TRANSITIONS = {
    "PENDING": {"INFEASIBLE"},
    "RUNNING": {"COMPLETED", "FAILED"},
    "COMPLETED": set(), "FAILED": set(), "INFEASIBLE": set(),
}


def load_job(connection: sqlite3.Connection, job_id: str) -> Job:
    row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return Job.model_validate_json(row["payload"])


def write_job(connection: sqlite3.Connection, job: Job):
    connection.execute("UPDATE jobs SET payload = ? WHERE id = ?",
                       (job.model_dump_json(by_alias=True), job.id))


class JobStore:
    def __init__(self, database: Database):
        self.database = database

    def list(self) -> list[Job]:
        with self.database.transaction() as connection:
            return [Job.model_validate_json(row["payload"]) for row in
                    connection.execute("SELECT payload FROM jobs ORDER BY id")]

    def get(self, job_id: str) -> Job:
        with self.database.transaction() as connection:
            return load_job(connection, job_id)

    def create(self, payload: JobCreate) -> Job:
        job = Job(**payload.model_dump())
        with self.database.transaction() as connection:
            try:
                connection.execute("INSERT INTO jobs (id, payload) VALUES (?, ?)",
                                   (job.id, job.model_dump_json(by_alias=True)))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Job ID already exists") from exc
            append_event(connection, "JOB_CREATED", job.id, job.model_dump(mode="json", by_alias=True))
        return job

    def start(self, job_id: str, reservation: Reservation, execution_mode: ExecutionMode) -> Job:
        """Record a start and reservation atomically; does not launch execution.

        The optimizer must validate portfolio capacity and costs before calling.
        """
        if execution_mode not in {"SIMULATED", "LOCAL"}:
            raise ValueError("Starting a job requires SIMULATED or LOCAL mode")
        with self.database.transaction() as connection:
            job = load_job(connection, job_id)
            if job.status != "PENDING":
                raise ValueError("Only pending jobs can start")
            allowed = job.allowed_gpu_types or ([job.gpu_type] if job.gpu_type else [])
            compatible = (reservation.gpu_type is None if job.resource_type == 'CPU'
                          else not allowed or reservation.gpu_type in allowed)
            if (reservation.job_id != job.id
                    or reservation.region not in job.allowed_regions
                    or reservation.resource_type != job.resource_type
                    or not compatible
                    or reservation.resource_units != job.resource_units
                    or reservation.start_slot < job.arrival_slot
                    or reservation.end_slot > job.deadline_slot
                    or reservation.end_slot - reservation.start_slot != job.duration_slots):
                raise ValueError("Reservation does not match job requirements")
            connection.execute("INSERT INTO reservations (job_id, payload) VALUES (?, ?)",
                               (job.id, reservation.model_dump_json(by_alias=True)))
            job.status = "RUNNING"
            write_job(connection, job)
            append_event(connection, "JOB_STARTED", job.id,
                         reservation.model_dump(mode="json", by_alias=True), execution_mode)
            return job

    def transition(self, job_id: str, status: JobStatus, *, reason: str | None = None) -> Job:
        with self.database.transaction() as connection:
            job = load_job(connection, job_id)
            if status not in TRANSITIONS[job.status]:
                raise ValueError(f"Invalid job transition: {job.status} -> {status}")
            previous = job.status
            job.status = status
            write_job(connection, job)
            mode_row = connection.execute(
                "SELECT execution_mode FROM audit_events WHERE job_id = ? "
                "AND event_type = 'JOB_STARTED' ORDER BY id DESC LIMIT 1", (job_id,),
            ).fetchone()
            connection.execute("DELETE FROM reservations WHERE job_id = ?", (job_id,))
            append_event(connection, "JOB_STATUS_CHANGED", job.id,
                         {"fromStatus": previous, "toStatus": status, "reason": reason},
                         mode_row["execution_mode"] if mode_row else None)
            return job


class DecisionStore:
    def __init__(self, database: Database):
        self.database = database

    def record(self, decision: Decision):
        with self.database.transaction() as connection:
            load_job(connection, decision.job_id)
            connection.execute("INSERT INTO decisions (job_id, payload) VALUES (?, ?)",
                               (decision.job_id, decision.model_dump_json(by_alias=True)))
            append_event(connection, "DECISION_RECORDED", decision.job_id,
                         decision.model_dump(mode="json", by_alias=True), decision.execution_mode)

    def list(self) -> list[Decision]:
        with self.database.transaction() as connection:
            return [Decision.model_validate_json(row["payload"]) for row in
                    connection.execute("SELECT payload FROM decisions ORDER BY id")]
