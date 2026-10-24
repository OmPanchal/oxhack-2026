"""Append audit records in the same transaction as the state they describe."""
from datetime import datetime, timezone
import json
import sqlite3

from app.api.schemas import Contract, ExecutionMode
from app.database import Database


class AuditEvent(Contract):
    id: int
    occurred_at_utc: datetime
    event_type: str
    job_id: str
    execution_mode: ExecutionMode | None
    payload: dict


def append_event(connection: sqlite3.Connection, event_type: str, job_id: str,
                 payload: dict, execution_mode: ExecutionMode | None = None):
    connection.execute(
        "INSERT INTO audit_events "
        "(occurred_at_utc, event_type, job_id, execution_mode, payload) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), event_type, job_id, execution_mode,
         json.dumps(payload, allow_nan=False)),
    )


class EventStore:
    def __init__(self, database: Database):
        self.database = database

    def list(self, job_id: str | None = None) -> list[AuditEvent]:
        with self.database.transaction() as connection:
            query = "SELECT * FROM audit_events"
            params = ()
            if job_id is not None:
                query += " WHERE job_id = ?"
                params = (job_id,)
            rows = connection.execute(query + " ORDER BY id", params).fetchall()
            return [AuditEvent(**{**dict(row), "payload": json.loads(row["payload"])})
                    for row in rows]
