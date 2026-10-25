"""Rolling-horizon observation, forecast, monitoring and scheduling orchestration."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from typing import Callable, Literal, Protocol

from app.api.runtime_schemas import DecisionDetail, EngineState
from app.api.schemas import Forecast, ForecastRequest, Job, MarketSnapshot, OptimizerConfig, Reservation
from app.audit.events import append_event
from app.database import Database
from app.engine.forecast_bridge import EngineUnavailable, ForecastMode, PersistenceForecastProvider, predict_checked
from app.engine.optimizer import OptimizationPlan, resource_key
from app.engine.scheduling import SchedulingService
from app.forecasting.interfaces import ForecastService
from app.jobs.store import write_job
from app.market.adapter import MarketSource, MemoryMarketSource
from app.execution.control import DispatchConflict, DispatchControl


@dataclass(frozen=True)
class ExecutionOutcome:
    job_id: str
    status: Literal["COMPLETED", "FAILED"]
    execution_mode: Literal["SIMULATED", "LOCAL"]
    observed_at_slot: int
    reason: str | None = None


class ExecutionMonitor(Protocol):
    def poll(self, current_slot: int) -> list[ExecutionOutcome]:
        """Return unconsumed/terminal outcomes idempotently; never launch work."""
        ...


class RollingScheduler:
    def __init__(self, database: Database, *, market_source: MarketSource | None = None,
                 forecast_services: dict[ForecastMode, ForecastService] | None = None,
                 monitor: ExecutionMonitor | None = None, config: OptimizerConfig | None = None,
                 clock: Callable[[], datetime] | None = None, auto_tick_enabled: bool = False,
                 origin_utc: datetime | None = None):
        self.database = database
        self.market_source = market_source if market_source is not None else MemoryMarketSource()
        self.providers = {"NAIVE": PersistenceForecastProvider(), **(forecast_services or {})}
        self.monitor = monitor
        self.config = config or OptimizerConfig()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.auto_tick_enabled = auto_tick_enabled
        if origin_utc is not None and (origin_utc.tzinfo is None or origin_utc.utcoffset() is None):
            raise ValueError("Slot origin must be timezone-aware")
        self.origin = origin_utc.astimezone(timezone.utc) if origin_utc is not None else None
        self.scheduling = SchedulingService(database)
        self.lock = RLock()
        self.dispatch = DispatchControl(database, self._now)
        self.local_dispatcher = None
        self.local_monitor = None

    def _now(self):
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Scheduler clock must be timezone-aware")
        return now.astimezone(timezone.utc)

    def _load_state(self, connection):
        row = connection.execute("SELECT payload FROM engine_state WHERE id = 1").fetchone()
        if row:
            return json.loads(row["payload"])
        origin = self.origin or self._now().replace(minute=0, second=0, microsecond=0)
        return {"currentSlot": 0, "originUtc": origin.isoformat(),
                "forecastMode": "NAIVE", "executionMode": "PAPER", "lastTickAtUtc": None,
                "lastError": None, "dataKind": None, "fingerprint": None}

    @staticmethod
    def _save_state(connection, state):
        connection.execute("INSERT INTO engine_state (id, payload) VALUES (1, ?) "
                           "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload", (json.dumps(state),))

    def state(self) -> EngineState:
        with self.database.transaction() as connection:
            state = self._load_state(connection)
            self._save_state(connection, state)
            dispatch = self.dispatch.read(connection)
            dispatch.automatic_local_dispatch_enabled = self.local_dispatcher is not None
        return EngineState.model_validate({
            **{key: value for key, value in state.items() if key != "fingerprint"},
            "autoTickEnabled": self.auto_tick_enabled, "mlConfigured": self.providers.get("ML") is not None,
            "dispatch": dispatch,
        })

    def pause(self):
        self.dispatch.pause()
        return self.state()

    def resume(self):
        revision = self.dispatch.begin_resume()
        if revision is not None:
            try:
                self.tick(force=True, resume_revision=revision)
            except Exception as exc:
                self.dispatch.resume_failed(revision, exc)
                raise
        return self.state()

    @staticmethod
    def _history(connection, slot):
        return [MarketSnapshot.model_validate_json(row["payload"]) for row in connection.execute(
            "SELECT payload FROM market_observations WHERE slot <= ? ORDER BY slot, series_key", (slot,))]

    def market(self) -> list[MarketSnapshot]:
        with self.database.transaction() as connection:
            return self._history(connection, self._load_state(connection)["currentSlot"])

    def forecasts(self, mode: ForecastMode | None = None) -> list[Forecast]:
        with self.database.transaction() as connection:
            state = self._load_state(connection)
            row = connection.execute(
                "SELECT payload FROM forecast_batches WHERE forecast_mode = ? "
                "AND generated_at_slot = ? ORDER BY id DESC LIMIT 1",
                (mode or state["forecastMode"], state["currentSlot"]),
            ).fetchone()
            return [Forecast.model_validate(item) for item in json.loads(row["payload"])] if row else []

    def details(self) -> list[DecisionDetail]:
        with self.database.transaction() as connection:
            return [DecisionDetail.model_validate_json(row["payload"]) for row in
                    connection.execute("SELECT payload FROM decision_details ORDER BY decision_id")]

    @staticmethod
    def _current_risk_forecasts(connection, slot, mode):
        # A prediction made last hour can describe interruption risk this hour.
        # Its old price never replaces the current observed price in the optimizer.
        latest = {}
        for batch in connection.execute(
            "SELECT payload FROM forecast_batches WHERE forecast_mode = ? "
            "AND generated_at_slot < ? ORDER BY id DESC", (mode, slot),
        ):
            for payload in json.loads(batch["payload"]):
                row = Forecast.model_validate(payload)
                key = resource_key(row)
                if row.target_slot == slot and key not in latest:
                    latest[key] = row
        return list(latest.values())

    def _observe(self, slot, origin):
        try:
            origin_poll = getattr(self.market_source, "poll_with_origin", None)
            return list(origin_poll(slot, origin) if origin_poll else self.market_source.poll(slot))
        except EngineUnavailable:
            raise
        except Exception as exc:
            raise EngineUnavailable("MARKET_SOURCE_FAILED", f"Observation source failed: {exc}") from exc
    def _ingest(self, connection, slot, observations):
        seen = {}
        for raw in observations:
            row = MarketSnapshot.model_validate(raw.model_dump())
            if row.slot > slot or row.data_kind == "FORECAST":
                raise ValueError("Market source returned unseen future data or predictions")
            series = json.dumps(resource_key(row))
            key = (series, row.slot)
            if key in seen and seen[key] != row:
                raise ValueError("Market source returned conflicting observations")
            seen[key] = row
            connection.execute(
                "INSERT INTO market_observations (series_key, slot, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(series_key, slot) DO UPDATE SET payload = excluded.payload",
                (series, row.slot, row.model_dump_json(by_alias=True)),
            )

    def _monitor(self, slot):
        try:
            return list(self.monitor.poll(slot)) if self.monitor else []
        except Exception as exc:
            raise EngineUnavailable("EXECUTION_MONITOR_FAILED", f"Execution monitor failed: {exc}") from exc

    def _settle(self, connection, slot, outcomes):
        outcomes = list(outcomes)
        reservations = [Reservation.model_validate_json(row["payload"]) for row in
                        connection.execute("SELECT payload FROM reservations")]
        explicit = {outcome.job_id for outcome in outcomes}
        for reservation in reservations:
            if reservation.end_slot > slot or reservation.job_id in explicit:
                continue
            started = connection.execute(
                "SELECT execution_mode FROM audit_events WHERE job_id = ? AND event_type = 'JOB_STARTED' "
                "ORDER BY id DESC LIMIT 1", (reservation.job_id,),
            ).fetchone()
            if started and started["execution_mode"] == "SIMULATED":
                outcomes.append(ExecutionOutcome(reservation.job_id, "COMPLETED", "SIMULATED",
                                                 reservation.end_slot, "Simulated duration elapsed"))
        for outcome in outcomes:
            if outcome.status not in {"COMPLETED", "FAILED"} or outcome.execution_mode not in {"SIMULATED", "LOCAL"}:
                raise ValueError("Invalid execution outcome")
            if outcome.observed_at_slot > slot or outcome.observed_at_slot < 0:
                raise ValueError("Execution monitor returned an outcome from an invalid slot")
            row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (outcome.job_id,)).fetchone()
            if row is None:
                raise ValueError("Execution outcome references an unknown job")
            job = Job.model_validate_json(row["payload"])
            started = connection.execute(
                "SELECT execution_mode FROM audit_events WHERE job_id = ? AND event_type = 'JOB_STARTED' "
                "ORDER BY id DESC LIMIT 1", (job.id,),
            ).fetchone()
            if not started or started["execution_mode"] != outcome.execution_mode:
                raise ValueError("Outcome does not match a running execution")
            if job.status in {"COMPLETED", "FAILED"}:
                if job.status != outcome.status:
                    raise ValueError("Conflicting terminal execution outcome")
                continue
            reservation = next((row for row in reservations if row.job_id == job.id), None)
            if (job.status != "RUNNING" or reservation is None
                    or outcome.observed_at_slot < reservation.start_slot):
                raise ValueError("Outcome does not match a running reservation")
            job.status = outcome.status
            write_job(connection, job)
            connection.execute("DELETE FROM reservations WHERE job_id = ?", (job.id,))
            append_event(connection, "JOB_STATUS_CHANGED", job.id,
                         {"fromStatus": "RUNNING", "toStatus": outcome.status, "reason": outcome.reason,
                          "observedAtSlot": outcome.observed_at_slot}, outcome.execution_mode)

    def _fingerprint(self, connection, slot, mode, execution, history):
        dispatch = self.dispatch.read(connection)
        values = [slot, mode, execution, [row.model_dump(mode="json") for row in history],
                  [row["payload"] for row in connection.execute("SELECT payload FROM jobs ORDER BY id")],
                  [row["payload"] for row in connection.execute("SELECT payload FROM reservations ORDER BY job_id")],
                  self.config.model_dump(mode="json"), dispatch.paused, dispatch.revision]
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def tick(self, current_slot: int | None = None, *, forecast_mode: ForecastMode | None = None,
             execution_mode: str | None = None, force: bool = False,
             resume_revision: int | None = None) -> OptimizationPlan | None:
        with self.lock:
            try:
                # Real local outcomes/timeouts must be reconciled even when
                # scheduling mode, logical time or source preflight is invalid.
                if self.local_monitor is not None:
                    self.local_monitor.poll()
                with self.database.transaction() as connection:
                    state = self._load_state(connection)
                    elapsed = int((self._now() - datetime.fromisoformat(state["originUtc"])).total_seconds() // 3600)
                    slot = max(state["currentSlot"], elapsed) if current_slot is None else current_slot
                    if slot < state["currentSlot"]:
                        raise ValueError("Scheduling time cannot move backwards")
                    mode = forecast_mode or state["forecastMode"]
                    execution = execution_mode or state["executionMode"]
                    # A deployment that removes opt-in disarms a saved LOCAL mode
                    # while keeping background monitoring and paper planning alive.
                    if execution == "LOCAL" and self.local_dispatcher is None and execution_mode is None:
                        execution = "PAPER"
                    if mode not in {"NAIVE", "ML"}:
                        raise ValueError("Unknown forecast mode")
                    if execution == "LOCAL" and self.local_dispatcher is None:
                        raise EngineUnavailable("LOCAL_EXECUTION_UNAVAILABLE", "Set COMPUTE_ALLOW_LOCAL_DISPATCH=1 to enable automatic local execution")
                    if execution not in {"PAPER", "SIMULATED", "LOCAL"}:
                        raise ValueError("Unknown execution mode")
                    if execution == "LOCAL" and slot != elapsed:
                        raise ValueError("Automatic LOCAL execution requires the current wall-clock slot")
                    origin = datetime.fromisoformat(state["originUtc"])
                    self._save_state(connection, state)
                # External I/O and inference must not own SQLite's writer lock.
                validate_slot = getattr(self.market_source, "validate_slot", None)
                if validate_slot:
                    validate_slot(slot, origin)
                outcomes = self._monitor(slot)
                with self.database.transaction() as connection:
                    state = self._load_state(connection)
                    if state["currentSlot"] > slot:
                        raise ValueError("Scheduling time advanced during monitoring; retry")
                    self._settle(connection, slot, outcomes)
                    state["currentSlot"] = slot
                    self._save_state(connection, state)
                # Confirmed outcomes remain durable even when the market is down.
                observations = self._observe(slot, origin)
                with self.database.transaction() as connection:
                    state = self._load_state(connection)
                    if state["currentSlot"] != slot:
                        raise ValueError("Scheduling slot changed during observation; retry")
                    self._ingest(connection, slot, observations)
                    history = self._history(connection, slot)
                    kinds = {row.data_kind for row in self._history(connection, slot)}
                    state["dataKind"] = "MIXED" if len(kinds) > 1 else next(iter(kinds), None)
                    self._save_state(connection, state)
                    fingerprint = self._fingerprint(connection, slot, mode, execution, history)
                    if not force and state["fingerprint"] == fingerprint and state["lastError"] is None:
                        return None
                    if not history:
                        raise EngineUnavailable("MARKET_DATA_UNAVAILABLE", "Configure a server-owned observation source")
                    planning_version = state["fingerprint"], state["lastTickAtUtc"]
                    history_json = [row.model_dump_json() for row in history]
                request = ForecastRequest(current_slot=slot, horizon_slots=6, history=history)
                predictions = predict_checked(self.providers.get(mode), mode, request, origin_utc=origin)
                with self.database.transaction() as connection:
                    state = self._load_state(connection)
                    fresh_history = self._history(connection, slot)
                    if state["currentSlot"] != slot or [row.model_dump_json() for row in fresh_history] != history_json:
                        raise ValueError("Market or scheduling slot changed during forecasting; retry")
                    fingerprint = self._fingerprint(connection, slot, mode, execution, fresh_history)
                    if not force and state["fingerprint"] == fingerprint and state["lastError"] is None:
                        return None
                    if planning_version != (state["fingerprint"], state["lastTickAtUtc"]):
                        raise ValueError("Another scheduler committed while forecasting; retry")
                    if resume_revision is not None:
                        elapsed = int((self._now() - origin).total_seconds() // 3600)
                        if elapsed > slot:
                            raise ValueError("Scheduling hour changed during resume; retry with fresh observations")
                        # Activation and use of this fresh plan share one commit.
                        # A newer pause cancels resume even if forecasting was slow.
                        self.dispatch.activate(connection, resume_revision)
                    connection.execute(
                        "INSERT INTO forecast_batches (generated_at_slot, forecast_mode, payload) VALUES (?, ?, ?)",
                        (slot, mode, json.dumps([row.model_dump(mode="json", by_alias=True) for row in predictions])),
                    )
                    plan = self.scheduling.run_in_transaction(
                        connection, current_slot=slot, market=fresh_history,
                        forecasts=self._current_risk_forecasts(connection, slot, mode) + predictions,
                        config=self.config, execution_mode=execution, forecast_mode=mode,
                    )
                    state.update(currentSlot=slot, forecastMode=mode, executionMode=execution,
                                 lastTickAtUtc=self._now().isoformat(), lastError=None,
                                 fingerprint=self._fingerprint(connection, slot, mode, execution, fresh_history))
                    kinds = {row.data_kind for row in history}
                    state["dataKind"] = "MIXED" if len(kinds) > 1 else next(iter(kinds))
                    self._save_state(connection, state)
                    local_starts = []
                    plan_fingerprint = state["fingerprint"]
                    if execution == "LOCAL":
                        if resume_revision is not None:
                            # Resume validates planning only. The next tick gets
                            # another fresh plan before any external Docker I/O.
                            state["fingerprint"] = None
                            self._save_state(connection, state)
                        elif not self.dispatch.read(connection).paused:
                            for decision in plan.decisions:
                                if decision.action in {"RUN", "ROUTE", "FALLBACK"} and decision.region == "local":
                                    row = connection.execute("SELECT id FROM decisions WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                                                             (decision.job_id,)).fetchone()
                                    local_starts.append((decision.job_id, row["id"]))
                # The adapter rechecks the persisted plan after image preparation
                # at its shared final pause/claim/start boundary, outside SQLite.
                for job_id, decision_id in local_starts:
                    try:
                        self.local_dispatcher.execute(job_id, decision_id=decision_id,
                                                      plan_fingerprint=plan_fingerprint)
                    except DispatchConflict:
                        break  # a new pause or changed portfolio requires a fresh tick
                return plan
            except Exception as exc:
                with self.database.transaction() as connection:
                    state = self._load_state(connection)
                    state["lastError"] = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
                    self._save_state(connection, state)
                raise

    def poll(self):
        """Background failures remain visible through engine/state; polling survives."""
        try:
            return self.tick()
        except Exception:
            return None
