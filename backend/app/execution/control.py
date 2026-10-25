"""Persisted dispatch gate. Pause serializes with the actual Docker start call."""
from contextlib import contextmanager
import os
from threading import Lock

from app.api.runtime_schemas import DispatchState
from app.engine.forecast_bridge import EngineUnavailable

_locks = {}
_locks_guard = Lock()


class DispatchConflict(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class DispatchControl:
    def __init__(self, database, clock):
        self.database, self.clock = database, clock
        self.path = str(database.path) + ".dispatch.lock"
        with _locks_guard:
            self.thread_lock = _locks.setdefault(os.path.normcase(self.path), Lock())

    @staticmethod
    def read(connection):
        row = connection.execute("SELECT payload FROM dispatch_state WHERE id = 1").fetchone()
        return DispatchState.model_validate_json(row["payload"]) if row else DispatchState()

    @staticmethod
    def save(connection, state):
        connection.execute("INSERT INTO dispatch_state (id, payload) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload", (state.model_dump_json(by_alias=True),))

    @classmethod
    def require_open(cls, connection):
        if cls.read(connection).paused:
            raise DispatchConflict("DISPATCH_PAUSED", "New starts are paused; running work continues to be monitored")

    @contextmanager
    def boundary(self):
        # A separate OS lock avoids holding SQLite's writer lock over Docker I/O.
        # It works across threads/apps/processes using the same local database,
        # and the OS releases it on process exit. Do not nest this context.
        with self.thread_lock:
            self.database.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a+b") as handle:
                try:
                    if os.name == "nt":
                        import msvcrt
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except OSError as exc:
                    raise EngineUnavailable("DISPATCH_GATE_BUSY", "Could not acquire the local dispatch gate; retry") from exc
                try:
                    yield
                finally:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def pause(self):
        with self.boundary(), self.database.transaction() as connection:
            state = self.read(connection)
            # Even repeated pause invalidates an outstanding resume request.
            state.paused = True
            state.revision += 1
            state.changed_at_utc = self.clock()
            self.save(connection, state)

    def begin_resume(self):
        with self.boundary(), self.database.transaction() as connection:
            state = self.read(connection)
            if not state.paused:
                return None
            state.revision += 1
            state.changed_at_utc = self.clock()
            state.last_resume_error = None
            self.save(connection, state)
            return state.revision

    def activate(self, connection, revision):
        state = self.read(connection)
        if not state.paused or state.revision != revision:
            raise DispatchConflict("RESUME_SUPERSEDED", "Pause/resume changed during replanning; engine remains under the newer control state")
        state.paused = False
        state.revision += 1
        state.changed_at_utc = state.last_resumed_at_utc = self.clock()
        state.last_resume_error = None
        self.save(connection, state)

    def resume_failed(self, revision, exc):
        with self.database.transaction() as connection:
            state = self.read(connection)
            if state.paused and state.revision == revision:
                state.last_resume_error = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
                self.save(connection, state)
