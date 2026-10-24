"""Commit scheduling against fresh SQLite state. No cloud or Docker execution."""
from app.api.schemas import ExecutionMode, Forecast, Job, MarketSnapshot, OptimizationInput, OptimizerConfig, Reservation
from app.audit.events import append_event
from app.database import Database
from app.engine.optimizer import ConstrainedPortfolioOptimizer, OptimizationPlan
from app.jobs.store import write_job


class SchedulingService:
    def __init__(self, database: Database, optimizer: ConstrainedPortfolioOptimizer | None = None):
        self.database = database
        self.optimizer = optimizer or ConstrainedPortfolioOptimizer()

    def run(self, *, current_slot: int, market: list[MarketSnapshot], forecasts: list[Forecast],
            config: OptimizerConfig | None = None, execution_mode: ExecutionMode = "PAPER") -> OptimizationPlan:
        if execution_mode not in {"PAPER", "SIMULATED"}:
            raise ValueError("LOCAL dispatch requires the execution adapter; use PAPER to inspect a plan")
        with self.database.transaction() as connection:
            jobs = [Job.model_validate_json(row["payload"]) for row in
                    connection.execute("SELECT payload FROM jobs ORDER BY id")]
            reservations = [Reservation.model_validate_json(row["payload"]) for row in
                            connection.execute("SELECT payload FROM reservations ORDER BY job_id")]
            inputs = OptimizationInput(
                current_slot=current_slot, pending_jobs=[job for job in jobs if job.status == "PENDING"],
                running_jobs=[job for job in jobs if job.status == "RUNNING"], market=market,
                forecasts=forecasts, reservations=reservations, config=config or OptimizerConfig(),
                execution_mode=execution_mode,
            )
            plan = self.optimizer.plan(inputs)
            by_id = {job.id: job for job in inputs.pending_jobs}
            for decision in plan.decisions:
                connection.execute("INSERT INTO decisions (job_id, payload) VALUES (?, ?)",
                                   (decision.job_id, decision.model_dump_json(by_alias=True)))
                append_event(connection, "DECISION_RECORDED", decision.job_id,
                             decision.model_dump(mode="json", by_alias=True), execution_mode)
                if execution_mode == "PAPER":
                    continue
                job = by_id[decision.job_id]
                if decision.action in {"RUN", "ROUTE", "FALLBACK"}:
                    reservation = Reservation(
                        job_id=job.id, region=decision.region, resource_type=job.resource_type,
                        gpu_type=job.gpu_type, resource_units=job.resource_units,
                        start_slot=decision.planned_start_slot, end_slot=decision.planned_end_slot,
                    )
                    connection.execute("INSERT INTO reservations (job_id, payload) VALUES (?, ?)",
                                       (job.id, reservation.model_dump_json(by_alias=True)))
                    job.status = "RUNNING"
                    write_job(connection, job)
                    append_event(connection, "JOB_STARTED", job.id,
                                 reservation.model_dump(mode="json", by_alias=True), execution_mode)
                elif decision.action == "INFEASIBLE":
                    job.status = "INFEASIBLE"
                    write_job(connection, job)
                    append_event(connection, "JOB_STATUS_CHANGED", job.id,
                                 {"fromStatus": "PENDING", "toStatus": "INFEASIBLE",
                                  "reason": decision.reason_code}, execution_mode)
            return plan
