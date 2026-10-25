"""SQLite connections and transaction boundaries shared by backend stores."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS simulation_config (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capacity_acquisitions (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id), payload TEXT NOT NULL
);
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
CREATE TABLE IF NOT EXISTS market_observations (
    series_key TEXT NOT NULL, slot INTEGER NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (series_key, slot)
);
CREATE TABLE IF NOT EXISTS aws_quote_batches (
    fingerprint TEXT PRIMARY KEY, recorded_at_utc TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS aws_quote_batches_time ON aws_quote_batches(recorded_at_utc);
CREATE TABLE IF NOT EXISTS engine_state (
    id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_price_history (
    series_key TEXT NOT NULL, hour_utc TEXT NOT NULL, available_at_utc TEXT NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY (series_key, hour_utc)
);
CREATE TABLE IF NOT EXISTS model_history_fetches (
    fingerprint TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatch_state (
    id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, generated_at_slot INTEGER NOT NULL,
    forecast_mode TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_details (
    decision_id INTEGER PRIMARY KEY REFERENCES decisions(id), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_session (
    id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_executions (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id), payload TEXT NOT NULL
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
