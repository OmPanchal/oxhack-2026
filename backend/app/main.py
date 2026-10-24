"""Person 2 owns composition and routes. Start: uvicorn app.main:app --reload."""
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.api.schemas import (
    Decision, Forecast, Health, Job, JobCreate, MarketSnapshot, OptimizeRequest,
    ReplayResetRequest, ReplayState, ReplayStepRequest, ShockRequest,
)
from app.jobs.store import JobStore


def create_app() -> FastAPI:
    app = FastAPI(title="Compute Arbitrage Engine", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )
    store = JobStore()

    def unfinished(feature: str):
        raise HTTPException(501, detail={"code": "NOT_IMPLEMENTED", "feature": feature})

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
        return []

    @app.get("/api/forecasts", response_model=list[Forecast])
    def forecasts():
        return []

    @app.post("/api/optimize", response_model=list[Decision])
    def optimize(payload: OptimizeRequest):
        unfinished("portfolio optimizer")

    @app.get("/api/decisions", response_model=list[Decision])
    def decisions():
        return []

    @app.get("/api/replay/state", response_model=ReplayState)
    def replay_state():
        return ReplayState(status="NOT_IMPLEMENTED", current_slot=0, seed=42, strategies=[
            "FIFO", "CHEAPEST_NOW", "OPTIMIZER_WITH_NAIVE_FORECAST", "OPTIMIZER_WITH_ML",
        ])

    @app.post("/api/replay/reset")
    def replay_reset(payload: ReplayResetRequest):
        unfinished("replay reset")

    @app.post("/api/replay/step")
    def replay_step(payload: ReplayStepRequest):
        unfinished("replay step")

    @app.post("/api/replay/shock")
    def replay_shock(payload: ShockRequest):
        unfinished("simulated market shocks")

    @app.get("/api/metrics")
    def metrics():
        unfinished("benchmark accounting")

    @app.get("/api/models/metrics")
    def model_metrics():
        unfinished("model evaluation")

    @app.post("/api/execute/{jobId}")
    def execute(jobId: str):
        unfinished("allowlisted local Docker execution")

    return app

app = create_app()
