"""Counterfactual replay with a shared realized world and independent policy state."""
from copy import deepcopy
from decimal import Decimal
import hashlib
from threading import RLock

from app.api.replay_schemas import (STRATEGIES, ReplayCharge, ReplayOutcome,
    ReplayScenario, ReplaySession, ReplayShock, ReplayShockRequest, ReplayStrategyView, ReplayView, StrategyRun)
from app.api.schemas import ForecastRequest, Job, MarketSnapshot, OptimizationInput, OptimizerConfig, Reservation
from app.database import Database
from app.engine.forecast_bridge import EngineUnavailable, ForecastMode, PersistenceForecastProvider, predict_checked
from app.engine.optimizer import ConstrainedPortfolioOptimizer, resource_key
from app.engine.policies import immediate_policy
from app.engine.money import decimal_usd, total_usd, within_budget
from app.engine.accounting import replay_totals as totals
from app.engine.replay_scenarios import capacity_pressure_scenario, demo_scenario
from app.forecasting.interfaces import ForecastService


class ReplayService:
    def __init__(self, database: Database, *, scenarios: dict[str, ReplayScenario] | None = None,
                 forecast_services: dict[ForecastMode, ForecastService] | None = None,
                 config: OptimizerConfig | None = None):
        self.database = database
        self.scenarios = scenarios if scenarios is not None else {
            "demo": demo_scenario(), "capacity-pressure": capacity_pressure_scenario(),
        }
        self.templates = {"NAIVE": PersistenceForecastProvider(), **(forecast_services or {})}
        self.providers = {}
        self.config = config or OptimizerConfig()
        self.lock = RLock()

    @staticmethod
    def _load(connection):
        row = connection.execute("SELECT payload FROM replay_session WHERE id = 1").fetchone()
        return ReplaySession.model_validate_json(row["payload"]) if row else None

    @staticmethod
    def _save(connection, session):
        connection.execute("INSERT INTO replay_session (id, payload) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload", (session.model_dump_json(by_alias=True),))

    @staticmethod
    def _view(session):
        if session is None:
            return ReplayView(status="READY", current_slot=0, seed=42, strategies=STRATEGIES)
        return ReplayView(status="COMPLETED" if session.current_slot == session.scenario.end_slot else
                          "READY" if session.current_slot == 0 else "RUNNING",
            current_slot=session.current_slot, seed=session.seed, strategies=STRATEGIES, initialized=True,
            scenario_id=session.scenario.id, description=session.scenario.description,
            origin_utc=session.scenario.origin_utc, end_slot=session.scenario.end_slot,
            strategy_states=[ReplayStrategyView(**run.model_dump(), metrics=totals(run)) for run in session.runs],
            events=session.events, observed_market=session.history)

    def state(self):
        with self.database.transaction() as connection:
            return self._view(self._load(connection))

    def metrics(self):
        from app.engine.metrics import replay_metrics
        with self.database.transaction() as connection:
            session = self._load(connection)
        return replay_metrics(session)

    def reset(self, scenario_id="demo", seed=42):
        if scenario_id not in self.scenarios:
            raise KeyError(scenario_id)
        scenario = self.scenarios[scenario_id].model_copy(deep=True)
        if self.config.portfolio_resource_limit is not None and len({job.resource_type for job in scenario.jobs}) > 1:
            raise ValueError("Scalar portfolio limit requires homogeneous replay workloads")
        try:
            providers = deepcopy(self.templates)
        except Exception as exc:
            raise EngineUnavailable("REPLAY_PROVIDER_CONFIGURATION", "Replay providers must support isolated copies") from exc
        runs = [StrategyRun(strategy=name) for name in STRATEGIES]
        if providers.get("ML") is None:
            runs[-1].status = "UNAVAILABLE"
            runs[-1].error = "ML provider is not configured; no naive substitution"
        with self.lock, self.database.transaction() as connection:
            session = ReplaySession(scenario=scenario, seed=seed, runs=runs, config=self.config.model_copy(deep=True))
            self._save(connection, session)
            self.providers = providers
            return self._view(session)

    def shock(self, payload: ReplayShockRequest):
        with self.lock, self.database.transaction() as connection:
            session = self._load(connection)
            if session is None:
                raise ValueError("Reset replay before adding shocks")
            if not session.current_slot <= payload.slot < session.scenario.end_slot:
                raise ValueError("Shock must affect an unprocessed slot inside the replay horizon")
            if payload.slot + payload.duration_slots > session.scenario.end_slot:
                raise ValueError("Shock duration extends beyond the replay horizon")
            definitions = self._definitions(session, session.scenario.end_slot)
            if payload.kind == "JOB_ARRIVAL":
                if payload.job.id in definitions:
                    raise ValueError("Shock job ID already exists")
                if self.config.portfolio_resource_limit is not None:
                    types = {job.resource_type for job in definitions.values()} | {payload.job.resource_type}
                    if len(types) > 1:
                        raise ValueError("Scalar portfolio limit requires homogeneous replay workloads")
            elif payload.kind == "DEADLINE_PRESSURE":
                if payload.job_id not in definitions:
                    raise ValueError("Deadline shock references an unknown job")
            else:
                if not any(self._matches(payload, row) for row in session.scenario.market):
                    raise ValueError("Shock filter matches no scenario resource")
            event = ReplayShock(**payload.model_dump(), event_id=f"shock-{len(session.events) + 1:04d}")
            session.events.append(event)
            self._save(connection, session)
            return event

    def step(self, slots=1):
        if not 1 <= slots <= 24:
            raise ValueError("Replay step must contain 1–24 hourly intervals")
        with self.lock:
            with self.database.transaction() as connection:
                row = connection.execute("SELECT payload FROM replay_session WHERE id = 1").fetchone()
                if row is None:
                    raise ValueError("Reset replay before stepping")
                before = row["payload"]
                session = ReplaySession.model_validate_json(before)
            if session.config != self.config:
                raise ValueError("Replay policy configuration changed; reset before continuing")
            if not self.providers:
                self.providers = deepcopy(self.templates)
            for _ in range(min(slots, session.scenario.end_slot - session.current_slot)):
                self._interval(session)
            # Forecasting can be slow. Commit only if no other process reset,
            # stepped or shocked this session while inference was in progress.
            with self.database.transaction() as connection:
                current = connection.execute("SELECT payload FROM replay_session WHERE id = 1").fetchone()
                if current is None or current["payload"] != before:
                    raise ValueError("Replay changed while stepping; retry against current state")
                self._save(connection, session)
            return self._view(session)

    @staticmethod
    def _matches(event, row):
        return ((event.region is None or event.region == row.region)
                and (event.resource_type is None or event.resource_type == row.resource_type)
                and (event.gpu_type is None or event.gpu_type == row.gpu_type))

    @staticmethod
    def _draw(seed, event, slot, key):
        value = repr((seed, event, slot, key)).encode()
        return int.from_bytes(hashlib.sha256(value).digest()[:8], "big") / 2**64

    def _world(self, session, slot):
        rows, interrupted = [], set()
        for base in sorted((row for row in session.scenario.market if row.slot == slot), key=lambda row: repr(resource_key(row))):
            row = base.model_copy(deep=True)
            key = resource_key(row)
            outage = self._draw(session.seed, "scenario-interruption", slot, key) < session.scenario.interruption_probability
            for event in session.events:
                if not event.slot <= slot < event.slot + event.duration_slots or not self._matches(event, row):
                    continue
                if event.kind == "PRICE_SPIKE":
                    row.price_usd_per_unit_hour *= event.magnitude
                elif event.kind == "CAPACITY_SHORTAGE":
                    row.available_units = max(0, row.available_units - int(event.magnitude))
                elif event.kind == "INTERRUPTION":
                    outage |= self._draw(session.seed, event.event_id, slot, key) < event.magnitude
                else:
                    continue
                row.data_kind = "SIMULATED"
                row.source += f"; SIMULATED {event.event_id} {event.kind}"
            if outage:
                interrupted.add(key)
                row.available_units = 0
                row.data_kind = "SIMULATED"
                row.source += "; SIMULATED interruption outage"
            rows.append(MarketSnapshot.model_validate(row.model_dump()))
        return rows, interrupted

    @staticmethod
    def _definitions(session, slot):
        definitions = {job.id: job.model_copy(deep=True) for job in session.scenario.jobs}
        events = sorted(enumerate(session.events), key=lambda pair: (pair[1].slot, pair[0]))
        for _, event in events:
            if event.slot <= slot and event.kind == "JOB_ARRIVAL":
                definitions[event.job.id] = event.job.model_copy(deep=True)
        for _, event in events:
            if event.slot <= slot and event.kind == "DEADLINE_PRESSURE" and event.job_id in definitions:
                job = definitions[event.job_id]
                job.deadline_slot = max(event.slot, job.deadline_slot - int(event.magnitude))
        return definitions

    @staticmethod
    def _finish(run, job, slot, status, reason):
        job.status = status
        run.reservations = [row for row in run.reservations if row.job_id != job.id]
        run.outcomes.append(ReplayOutcome(job_id=job.id, slot=slot, status=status, reason=reason))

    def _boundary(self, run, slot):
        by_id = {job.id: job for job in run.jobs}
        for row in list(run.reservations):
            if row.end_slot <= slot:
                self._finish(run, by_id[row.job_id], row.end_slot, "COMPLETED", "SIMULATED_DURATION_ELAPSED")
        for job in run.jobs:
            if job.deadline_slot <= slot and job.status != "COMPLETED":
                if job.id not in run.missed_deadline_ids:
                    run.missed_deadline_ids.append(job.id)
                if job.status in {"PENDING", "RUNNING"}:
                    self._finish(run, job, slot, "FAILED" if job.status == "RUNNING" else "INFEASIBLE", "DEADLINE_MISSED")

    def _realize_capacity(self, run, market, interrupted, slot):
        remaining = {resource_key(row): row.available_units for row in market}
        by_id = {job.id: job for job in run.jobs}
        for reservation in sorted(list(run.reservations), key=lambda row: (row.start_slot, row.job_id)):
            key = resource_key(reservation)
            if key in interrupted:
                self._finish(run, by_id[reservation.job_id], slot, "FAILED", "SIMULATED_INTERRUPTION")
            elif remaining.get(key, 0) < reservation.resource_units:
                self._finish(run, by_id[reservation.job_id], slot, "FAILED", "REALIZED_CAPACITY_LOSS")
            else:
                remaining[key] -= reservation.resource_units

    def _dispatch(self, session, run, market, slot):
        if run.status != "ACTIVE":
            return
        inputs = OptimizationInput(current_slot=slot,
            pending_jobs=[job for job in run.jobs if job.status == "PENDING"],
            running_jobs=[job for job in run.jobs if job.status == "RUNNING"],
            forecasts=[], market=market, reservations=run.reservations, config=session.config, execution_mode="SIMULATED")
        allocations = {}
        if run.strategy in {"FIFO", "CHEAPEST_NOW"}:
            decisions = immediate_policy(inputs, cheapest_now=run.strategy == "CHEAPEST_NOW", allocations=allocations)
        else:
            mode = "ML" if run.strategy == "OPTIMIZER_WITH_ML" else "NAIVE"
            try:
                predictions = predict_checked(self.providers.get(mode), mode,
                    ForecastRequest(current_slot=slot, horizon_slots=6, history=deepcopy(session.history)))
                if run.forecasts and {row.model_version for row in run.forecasts} != {row.model_version for row in predictions}:
                    raise EngineUnavailable("REPLAY_MODEL_CHANGED", "Forecast model versions changed; reset replay")
                prior = [row for row in run.forecasts if row.target_slot == slot]
                run.forecasts = prior + predictions
                inputs.forecasts = run.forecasts
                plan = ConstrainedPortfolioOptimizer().plan(inputs)
                decisions, allocations = plan.decisions, plan.allocations
            except Exception as exc:
                run.status = "UNAVAILABLE" if self.providers.get(mode) is None else "ERROR"
                run.error = str(exc)
                return
        run.decisions.extend(decisions)
        by_id = {job.id: job for job in run.jobs}
        for decision in decisions:
            job = by_id[decision.job_id]
            if decision.action == "INFEASIBLE":
                self._finish(run, job, slot, "INFEASIBLE", decision.reason_code)
            elif decision.action in {"RUN", "ROUTE", "FALLBACK"}:
                job.status = "RUNNING"
                run.reservations.append(allocations[job.id])

    def _charge(self, run, market, slot, config):
        indexed = {resource_key(row): row for row in market}
        by_id = {job.id: job for job in run.jobs}
        for reservation in list(run.reservations):
            job = by_id[reservation.job_id]
            row = indexed[resource_key(reservation)]
            if config.carbon_price_usd_per_kg and row.carbon_kg_per_unit_hour is None:
                raise ValueError("Realized carbon valuation requires observed carbon data")
            charge = ReplayCharge(slot=slot, job_id=job.id,
                compute_usd=float(decimal_usd(Decimal(str(row.price_usd_per_unit_hour)) * job.resource_units)),
                startup_usd=float(decimal_usd(config.startup_cost_usd)) if reservation.start_slot == slot else 0,
                transfer_usd=float(decimal_usd(config.transfer_cost_usd)) if reservation.start_slot == slot
                    and reservation.region != job.allowed_regions[0] else 0,
                carbon_usd=float(decimal_usd(Decimal(str(row.carbon_kg_per_unit_hour or 0)) * job.resource_units
                                            * Decimal(str(config.carbon_price_usd_per_kg)))))
            spent = total_usd(value for item in run.charges if item.job_id == job.id
                              for value in [item.compute_usd, item.startup_usd, item.transfer_usd, item.carbon_usd])
            cost = total_usd([charge.compute_usd, charge.startup_usd, charge.transfer_usd, charge.carbon_usd])
            if not within_budget(total_usd([spent, cost]), job.max_budget_usd):
                self._finish(run, job, slot, "FAILED", "REALIZED_BUDGET_EXCEEDED")
            else:
                run.charges.append(charge)

    def _interval(self, session):
        slot = session.current_slot
        market, interrupted = self._world(session, slot)
        session.history.extend(market)
        definitions = self._definitions(session, slot)
        for run in session.runs:
            by_id = {job.id: job for job in run.jobs}
            for job_id, definition in definitions.items():
                if definition.arrival_slot > slot:
                    continue
                if job_id not in by_id:
                    run.jobs.append(Job(**definition.model_dump()))
                else:
                    by_id[job_id].deadline_slot = definition.deadline_slot
            self._boundary(run, slot)
            self._realize_capacity(run, market, interrupted, slot)
            self._dispatch(session, run, market, slot)
            self._charge(run, market, slot, session.config)
            self._boundary(run, slot + 1)
        session.current_slot += 1
