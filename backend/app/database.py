"""SQLite connections and transaction boundaries shared by backend stores."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at_utc TEXT NOT NULL,
    event_type TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id),
    execution_mode TEXT, payload TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    @contextmanager
    def transaction(self):
        # Separate connections work across FastAPI threads. Serialize reads and
        # writes in each operation so concurrent starts cannot both succeed.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
