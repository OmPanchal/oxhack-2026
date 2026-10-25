"""Person 2 owns composition and routes. Start: uvicorn app.main:app --reload."""
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.schemas import (
    Decision, Forecast, Health, Job, JobCreate, MarketSnapshot, OptimizeRequest,
    OptimizerConfig, ReplayResetRequest, ReplayStepRequest,
)
from app.database import Database
from app.api.runtime_schemas import DecisionDetail, EngineState
from app.api.replay_schemas import ReplayScenario, ReplayShock, ReplayShockRequest, ReplayView
from app.api.market_schemas import AwsSpotPrices, MarketCapabilities
from app.api.metrics_schemas import LiveMetrics, ModelEvaluation, ModelMetrics, ReplayMetrics
from app.engine.accounting import AccountingError
from app.engine.metrics import ModelMetricsService, live_metrics
from app.engine.forecast_bridge import EngineUnavailable, ForecastMode
from app.engine.optimizer import OptimizationLimitError
from app.engine.runtime import ExecutionMonitor, RollingScheduler
from app.engine.simulator import ReplayService
from app.forecasting.interfaces import ForecastService
from app.market.adapter import JsonMarketSource, MarketSource
from app.market.aws import AwsSpotMarket
from app.market.history import AwsQuoteArchive
from app.jobs.store import DecisionStore, JobStore
from app.api.execution_schemas import ExecuteRequest, LocalExecution, TaskCatalog
from app.execution.docker import TASK
from app.execution.service import LocalExecutionService


def create_app(database_path: str | Path | None = None, *,
               forecast_services: dict[ForecastMode, ForecastService] | None = None,
               market_source: MarketSource | None = None, monitor: ExecutionMonitor | None = None,
               clock: Callable[[], datetime] | None = None,
               optimizer_config: OptimizerConfig | None = None,
               replay_scenarios: dict[str, ReplayScenario] | None = None,
               aws_market: AwsSpotMarket | None = None,
               model_metrics_provider: Callable[[], ModelEvaluation] | None = None,
               tick_interval_seconds: float | None = None, execution_adapter=None,
               allow_local_dispatch: bool | None = None) -> FastAPI:
    local_dispatch_enabled = (os.getenv("COMPUTE_ALLOW_LOCAL_DISPATCH", "0") == "1"
                              if allow_local_dispatch is None else allow_local_dispatch)
    interval = float(os.getenv("COMPUTE_TICK_SECONDS", "2")) if tick_interval_seconds is None else tick_interval_seconds
    from math import isfinite
    if not isfinite(interval) or interval < 0:
        raise ValueError("Tick interval must be finite and nonnegative")

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()

        async def watch():
            while not stop.is_set():
                await asyncio.to_thread(engine.poll)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(watch()) if interval > 0 else None
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task

    app = FastAPI(title="Compute Arbitrage Engine", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )
    database = Database(database_path if database_path is not None else os.getenv(
        "COMPUTE_DB_PATH", str(Path(__file__).resolve().parents[1] / "state" / "engine.sqlite3"),
    ))
    store = JobStore(database)
    decision_store = DecisionStore(database)
    source_path = os.getenv("COMPUTE_MARKET_FILE")
    source_mode = os.getenv("COMPUTE_MARKET_SOURCE", "json" if source_path else "none").lower()
    if source_mode not in {"none", "json", "aws"}:
        raise ValueError("COMPUTE_MARKET_SOURCE must be none, json or aws")
    if aws_market is not None and market_source is not None and market_source is not aws_market:
        raise ValueError("Configure one market source per engine")
    if aws_market is None and isinstance(market_source, AwsSpotMarket):
        aws_market = market_source
    if source_mode == "aws" and aws_market is None and market_source is None:
        aws_market = AwsSpotMarket(os.getenv("COMPUTE_AWS_REGIONS", "").split(","),
            instance_types=[name.strip() for name in os.getenv("COMPUTE_AWS_INSTANCE_TYPES", "").split(",") if name.strip()], clock=clock)
    if source_mode == "json" and not source_path and market_source is None and aws_market is None:
        raise ValueError("JSON market mode requires COMPUTE_MARKET_FILE")
    if aws_market is not None and aws_market.quote_archive is None:
        aws_market.quote_archive = AwsQuoteArchive(database)
    source = market_source if market_source is not None else aws_market if aws_market is not None else (
        JsonMarketSource(source_path) if source_mode == "json" else None)
    origin = datetime.fromisoformat(os.environ["COMPUTE_ORIGIN_UTC"]) if os.getenv("COMPUTE_ORIGIN_UTC") else None
    engine = RollingScheduler(database, market_source=source, forecast_services=forecast_services,
                              monitor=monitor, clock=clock, config=optimizer_config,
                              auto_tick_enabled=interval > 0, origin_utc=origin)
    app.state.engine = engine
    executions = LocalExecutionService(database, engine, adapter=execution_adapter)
    engine.local_dispatcher = executions if local_dispatch_enabled else None
    engine.local_monitor = executions
    app.state.executions = executions
    replay = ReplayService(database, scenarios=replay_scenarios, forecast_services=forecast_services,
                           config=optimizer_config)
    app.state.replay = replay
    model_metrics_service = ModelMetricsService(model_metrics_provider, clock)

    @app.exception_handler(AccountingError)
    async def accounting_error(request: Request, exc: AccountingError):
        return JSONResponse(status_code=409, content={"detail": {"code": "METRICS_LEDGER_MISMATCH", "message": str(exc)}})

    @app.exception_handler(EngineUnavailable)
    async def unavailable(request: Request, exc: EngineUnavailable):
        return JSONResponse(status_code=503, content={"detail": {"code": exc.code, "message": str(exc)}})

    @app.exception_handler(OptimizationLimitError)
    async def search_limit(request: Request, exc: OptimizationLimitError):
        return JSONResponse(status_code=503, content={"detail": {"code": "OPTIMIZATION_LIMIT", "message": str(exc)}})

    @app.get("/api/health", response_model=Health)
    def health():
        return Health()

    @app.get("/api/jobs", response_model=list[Job])
    def jobs():
        return store.list()

    @app.post("/api/jobs", response_model=Job, status_code=201)
    def create_job(payload: JobCreate):
        try:
            return store.create(payload)
        except ValueError as exc:
            raise HTTPException(409, detail=str(exc)) from exc

    @app.get("/api/market", response_model=list[MarketSnapshot])
    def market():
        return engine.market()

    @app.get("/api/capabilities", response_model=MarketCapabilities)
    def capabilities():
        if aws_market is not None:
            return aws_market.capabilities()
        rows = engine.market()
        return MarketCapabilities(provider="CONFIGURED_MARKET" if rows else "NONE",
            status="READY" if rows else "NOT_CONFIGURED", capacity_status="SOURCE_DEFINED" if rows else "UNKNOWN",
            allowed_gpu_types=sorted({row.gpu_type for row in rows if row.resource_type == "GPU" and row.gpu_type}),
            allowed_regions=sorted({row.region for row in rows}))

    @app.get("/api/market/aws/spot", response_model=AwsSpotPrices)
    def aws_spot_prices():
        return aws_market.prices() if aws_market is not None else AwsSpotPrices(status="NOT_CONFIGURED")

    @app.get("/api/forecasts", response_model=list[Forecast])
    def forecasts(forecastMode: Literal["NAIVE", "ML"] | None = None):
        return engine.forecasts(forecastMode)

    @app.post("/api/optimize", response_model=list[Decision])
    def optimize(payload: OptimizeRequest):
        try:
            return engine.tick(payload.current_slot, forecast_mode=payload.forecast_mode,
                               execution_mode=payload.execution_mode, force=True).decisions
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "SCHEDULING_CONFLICT", "message": str(exc)}) from exc

    @app.get("/api/decisions", response_model=list[Decision])
    def decisions():
        return decision_store.list()

    @app.get("/api/decisions/details", response_model=list[DecisionDetail])
    def decision_details():
        return engine.details()

    @app.get("/api/engine/state", response_model=EngineState)
    def engine_state():
        return engine.state()

    @app.post("/api/engine/pause", response_model=EngineState)
    def pause_dispatch(payload: ExecuteRequest = Body(default=ExecuteRequest())):
        return engine.pause()

    @app.post("/api/engine/resume", response_model=EngineState)
    def resume_dispatch(payload: ExecuteRequest = Body(default=ExecuteRequest())):
        try:
            return engine.resume()
        except ValueError as exc:
            raise HTTPException(409, detail={"code": getattr(exc, "code", "RESUME_CONFLICT"), "message": str(exc)}) from exc

    @app.get("/api/replay/state", response_model=ReplayView)
    def replay_state():
        return replay.state()

    @app.post("/api/replay/reset", response_model=ReplayView)
    def replay_reset(payload: ReplayResetRequest):
        try:
            return replay.reset(payload.scenario_id, payload.seed)
        except KeyError as exc:
            raise HTTPException(404, detail={"code": "SCENARIO_NOT_FOUND", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "REPLAY_CONFLICT", "message": str(exc)}) from exc

    @app.post("/api/replay/step", response_model=ReplayView)
    def replay_step(payload: ReplayStepRequest):
        try:
            return replay.step(payload.slots)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "REPLAY_CONFLICT", "message": str(exc)}) from exc

    @app.post("/api/replay/shock", response_model=ReplayShock)
    def replay_shock(payload: ReplayShockRequest):
        try:
            return replay.shock(payload)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "REPLAY_CONFLICT", "message": str(exc)}) from exc

    @app.get("/api/metrics", response_model=ReplayMetrics | LiveMetrics)
    def metrics(scope: Literal["REPLAY", "LIVE"] = "REPLAY"):
        return replay.metrics() if scope == "REPLAY" else live_metrics(database)

    @app.get("/api/models/metrics", response_model=ModelMetrics)
    def model_metrics():
        return model_metrics_service.read()

    @app.get("/api/execution/tasks", response_model=TaskCatalog)
    def execution_tasks():
        return TaskCatalog(tasks=[TASK], automatic_dispatch_enabled=engine.local_dispatcher is not None)

    @app.get("/api/executions", response_model=list[LocalExecution])
    def local_executions():
        executions.poll()
        return executions.list()

    @app.get("/api/executions/{executionId}", response_model=LocalExecution)
    def local_execution(executionId: str):
        try:
            return executions.refresh(executionId)
        except KeyError as exc:
            raise HTTPException(404, detail="Execution not found") from exc

    @app.post("/api/execute/{jobId}", response_model=LocalExecution)
    def execute(jobId: str, payload: ExecuteRequest = Body(default=ExecuteRequest())):
        try:
            return executions.execute(jobId)
        except KeyError as exc:
            raise HTTPException(404, detail="Job not found") from exc
        except ValueError as exc:
            raise HTTPException(409, detail={"code": getattr(exc, "code", "EXECUTION_CONFLICT"), "message": str(exc)}) from exc

    return app

app = create_app()
