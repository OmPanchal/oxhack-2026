"""Durable manual/scheduler dispatch and restart-safe local observation."""
from datetime import datetime, timedelta, timezone
from math import ceil
from threading import RLock
from uuid import uuid4

from app.api.execution_schemas import LocalExecution
from app.api.schemas import Decision, Reservation
from app.audit.events import append_event
from app.execution.docker import DockerAdapter, TASK
from app.execution.control import DispatchConflict
from app.jobs.store import load_job, write_job

TERMINAL = {"COMPLETED", "FAILED"}


class LocalExecutionService:
    @staticmethod
    def _real_now():
        return datetime.now(timezone.utc)

    def _timeout_now(self):
        return self._real_now() if self.engine.acquisition_provider is not None else self.engine._now()

    def _observed_slot(self, timestamp, state):
        if self.engine.acquisition_provider is not None:
            origin = datetime.fromisoformat(state['originUtc'])
            return max(state['currentSlot'], int((self.engine._now() - origin).total_seconds() // 3600))
        origin = datetime.fromisoformat(state['originUtc'])
        return max(0, ceil((timestamp - origin).total_seconds() / 3600))
    def __init__(self, database, engine, *, adapter=None):
        self.database, self.engine = database, engine
        self.adapter = adapter if adapter is not None else DockerAdapter()
        self.lock = RLock()

    @staticmethod
    def _save(connection, record):
        connection.execute("UPDATE local_executions SET payload = ? WHERE id = ?",
                           (record.model_dump_json(by_alias=True), record.id))

    def list(self):
        with self.database.transaction() as connection:
            return [LocalExecution.model_validate_json(row["payload"]) for row in
                    connection.execute("SELECT payload FROM local_executions ORDER BY id")]

    def get(self, execution_id):
        with self.database.transaction() as connection:
            row = connection.execute("SELECT payload FROM local_executions WHERE id = ?", (execution_id,)).fetchone()
            if row is None:
                raise KeyError(execution_id)
            return LocalExecution.model_validate_json(row["payload"])

    @staticmethod
    def _by_job(connection, job_id):
        row = connection.execute("SELECT payload FROM local_executions WHERE job_id = ?", (job_id,)).fetchone()
        return LocalExecution.model_validate_json(row["payload"]) if row else None

    def _validate(self, connection, job):
        self.engine.dispatch.require_open(connection)
        if job.status != "PENDING":
            raise ValueError("Only pending jobs can start")
        if job.docker_task_id != TASK.id:
            raise ValueError("Select an allowlisted dockerTaskId from /api/execution/tasks")
        if job.resource_type != "CPU" or job.resource_units != 1 or job.gpu_type or "local" not in job.allowed_regions:
            raise ValueError("This task requires one CPU and the explicit local region")
        state = self.engine._load_state(connection)
        self.engine._save_state(connection, state)
        now = self.engine._now()
        origin = datetime.fromisoformat(state['originUtc'])
        slot = int((now - origin).total_seconds() // 3600)
        if self.engine.acquisition_provider is not None:
            # The accelerated clock can lag a slot already persisted by a
            # replan/restarted process. Use the same logical-clock floor as
            # engine state/job creation; never weaken real live-clock checks.
            slot = max(slot, state['currentSlot'])
            now = max(now, origin + timedelta(hours=slot))
        elif slot < state['currentSlot']:
            raise ValueError("Local execution requires current wall-clock scheduling time and an arrived job")
        if slot < job.arrival_slot:
            raise ValueError(f'Local task has not arrived: arrival slot {job.arrival_slot}, current slot {slot}')
        if slot + job.duration_slots + self.engine.config.safety_buffer_slots > job.deadline_slot:
            raise ValueError("Job cannot finish within its deadline and safety buffer")
        deadline = datetime.fromisoformat(state["originUtc"]) + timedelta(
            hours=job.deadline_slot - self.engine.config.safety_buffer_slots)
        slot_seconds = getattr(self.engine.clock, 'slot_seconds', 3600)
        if (deadline - now).total_seconds() * slot_seconds / 3600 < TASK.timeout_seconds:
            raise ValueError("Insufficient wall-clock time remains for the bounded local task")
        # Model the demonstration as zero billed compute, never as cloud savings.
        if self.engine.config.startup_cost_usd or self.engine.config.transfer_cost_usd:
            raise ValueError("Local demonstration has no configured billing adapter; nonzero overhead is unsupported")
        active = connection.execute("SELECT payload FROM local_executions").fetchall()
        if any(LocalExecution.model_validate_json(row["payload"]).status not in TERMINAL for row in active):
            raise ValueError("The single local CPU execution slot is occupied")
        reservations = [Reservation.model_validate_json(row["payload"]) for row in
                        connection.execute("SELECT payload FROM reservations")]
        end = slot + job.duration_slots
        if any(r.region == "local" and r.resource_type == "CPU" and r.start_slot < end and r.end_slot > slot
               for r in reservations):
            raise ValueError("Local CPU capacity is already reserved")
        limit = self.engine.config.portfolio_resource_limit
        if limit is not None and any(
            1 + sum(r.resource_units for r in reservations if r.start_slot <= t < r.end_slot) > limit
            for t in range(slot, end)
        ):
            raise ValueError("Portfolio resource limit would be exceeded")
        return slot, now

    def _validate_ticket(self, connection, job_id, decision_id, plan_fingerprint):
        state = self.engine._load_state(connection)
        row = connection.execute("SELECT id, payload FROM decisions WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                                 (job_id,)).fetchone()
        origin = datetime.fromisoformat(state["originUtc"])
        slot = int((self.engine._now() - origin).total_seconds() // 3600)
        actual = self.engine._fingerprint(connection, slot, state["forecastMode"], "LOCAL",
                                          self.engine._history(connection, slot))
        if (self.engine.local_dispatcher is not self or state["executionMode"] != "LOCAL"
                or state["currentSlot"] != slot or state["fingerprint"] != plan_fingerprint
                or actual != plan_fingerprint or row is None or row["id"] != decision_id):
            raise DispatchConflict("STALE_LOCAL_PLAN", "Local plan changed during preparation; replan before dispatch")
        decision = Decision.model_validate_json(row["payload"])
        if (decision.execution_mode != "LOCAL" or decision.action not in {"RUN", "ROUTE", "FALLBACK"}
                or decision.region != "local" or decision.decided_at_slot != slot or decision.planned_start_slot != slot):
            raise DispatchConflict("STALE_LOCAL_PLAN", "Only a current local RUN/ROUTE/FALLBACK may dispatch")

    def execute(self, job_id, *, decision_id=None, plan_fingerprint=None):
        with self.lock:
            with self.database.transaction() as connection:
                existing = self._by_job(connection, job_id)
                if existing:
                    return existing
                self._validate(connection, load_job(connection, job_id))
                if decision_id is not None:
                    self._validate_ticket(connection, job_id, decision_id, plan_fingerprint)
            # Image download and daemon I/O never hold a SQLite write lock.
            image_id = self.adapter.prepare()
            # Pause can win while the image is downloading. Once admitted here,
            # pause waits for this single start submission before acknowledging.
            with self.engine.dispatch.boundary():
                with self.database.transaction() as connection:
                    existing = self._by_job(connection, job_id)
                    if existing:
                        return existing
                    job = load_job(connection, job_id)
                    slot, now = self._validate(connection, job)
                    if decision_id is not None:
                        self._validate_ticket(connection, job_id, decision_id, plan_fingerprint)
                    if self.engine.acquisition_provider is not None:
                        now = self._real_now()
                    execution_id = uuid4().hex
                    record = LocalExecution(id=execution_id, job_id=job.id, task_id=TASK.id,
                        docker_endpoint=getattr(self.adapter, 'prepared_endpoint', None),
                        image_id=image_id, container_name="compute-" + execution_id, requested_at_utc=now)
                    connection.execute("INSERT INTO local_executions (id, job_id, payload) VALUES (?, ?, ?)",
                                       (record.id, job.id, record.model_dump_json(by_alias=True)))
                    reservation = Reservation(job_id=job.id, region="local", resource_type="CPU", resource_units=1,
                                              start_slot=slot, end_slot=slot + job.duration_slots)
                    connection.execute("INSERT INTO reservations (job_id, payload) VALUES (?, ?)",
                                       (job.id, reservation.model_dump_json(by_alias=True)))
                    job.status = "RUNNING"
                    write_job(connection, job)
                    append_event(connection, "EXECUTION_RESERVED", job.id, {"executionId": record.id}, "LOCAL")
                try:
                    self.adapter.launch(record)
                except Exception as exc:
                    # Lost responses keep their durable claim; never retry.
                    self._error(record.id, f"Start outcome uncertain: {exc}")
            self.refresh(record.id)
            return self.get(record.id)

    def _error(self, execution_id, message):
        with self.database.transaction() as connection:
            row = connection.execute("SELECT payload FROM local_executions WHERE id = ?", (execution_id,)).fetchone()
            record = LocalExecution.model_validate_json(row["payload"])
            if record.status not in TERMINAL:
                record.last_monitor_error = message
                self._save(connection, record)

    def refresh(self, execution_id):
        with self.lock:
            record = self.get(execution_id)
            if record.status in TERMINAL:
                return record
            try:
                observed = self.adapter.inspect(record)
                if observed and observed["state"] == "running" and observed["started_at_utc"]:
                    if (self._timeout_now() - observed["started_at_utc"]).total_seconds() >= TASK.timeout_seconds:
                        # Persist before kill, so a fast exit cannot be mistaken for success.
                        with self.database.transaction() as connection:
                            fresh = self._by_job(connection, record.job_id)
                            if fresh.status not in TERMINAL:
                                fresh.timeout_requested = True
                                self._save(connection, fresh)
                        self.adapter.kill(record)
                        observed = self.adapter.inspect(record)
            except Exception as exc:
                self._error(record.id, str(exc))
                return self.get(record.id)
            with self.database.transaction() as connection:
                record = self._by_job(connection, record.job_id)
                if record.status in TERMINAL:
                    return record
                if observed is None:
                    if record.container_id is None:
                        record.last_monitor_error = "Start unconfirmed; container absent. Manual reconciliation required; no automatic retry."
                        self._save(connection, record)
                        return record
                    record.status = "FAILED"
                    record.failure_reason = "Previously observed container is missing"
                    record.completed_at_utc = None
                else:
                    record.last_monitor_error = observed.get("log_error")
                    record.container_id = observed["container_id"]
                    for name in ("stdout", "stderr", "stdout_truncated", "stderr_truncated"):
                        if name in observed:
                            setattr(record, name, observed[name])
                    if observed["started_at_utc"] and record.started_at_utc is None:
                        record.started_at_utc = observed["started_at_utc"]
                        append_event(connection, "JOB_STARTED", record.job_id,
                            {"executionId": record.id, "startedAtUtc": record.started_at_utc.isoformat()}, "LOCAL")
                    if observed["state"] in {"exited", "dead"}:
                        record.exit_code = observed["exit_code"]
                        record.completed_at_utc = observed["completed_at_utc"]
                        failed = (record.exit_code != 0 or record.timeout_requested or observed["oom"]
                                  or observed["state"] == "dead" or bool(observed["error"]))
                        record.status = "FAILED" if failed else "COMPLETED"
                        record.failure_reason = ("Execution exceeded time limit" if record.timeout_requested else
                            "Container exceeded memory limit" if observed["oom"] else
                            observed["error"] or f"Container exited with code {record.exit_code}") if failed else None
                    elif observed["state"] == "running":
                        record.status = "RUNNING"
                    else:
                        record.last_monitor_error = f"Container is {observed['state']}; no automatic start/retry"
                if record.status in TERMINAL:
                    job = load_job(connection, record.job_id)
                    job.status = record.status
                    write_job(connection, job)
                    connection.execute("DELETE FROM reservations WHERE job_id = ?", (job.id,))
                    payload = {"fromStatus": "RUNNING", "toStatus": record.status,
                               "executionId": record.id, "reason": record.failure_reason}
                    if record.completed_at_utc:
                        origin = datetime.fromisoformat(self.engine._load_state(connection)["originUtc"])
                        # A finish just after an hourly deadline must count as late.
                        payload["observedAtSlot"] = self._observed_slot(record.completed_at_utc, self.engine._load_state(connection)) if self.engine.acquisition_provider is not None else max(0, ceil((record.completed_at_utc - origin).total_seconds() / 3600))
                    append_event(connection, "JOB_STATUS_CHANGED", job.id, payload, "LOCAL")
                self._save(connection, record)
                return record

    def poll(self):
        for record in self.list():
            if record.status not in TERMINAL:
                self.refresh(record.id)
