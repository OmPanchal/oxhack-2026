"""Opt-in genuine LOCAL execution through the HTTP API; never part of unit CI.

Run from backend: .venv/Scripts/python.exe scripts/docker_smoke.py
Requires pip install -e '.[dev,execution]' and a running local Linux Docker engine.
"""
import hashlib
import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import create_app
from app.api.schemas import MarketSnapshot
from app.market.adapter import MemoryMarketSource


def verify_record(record):
    assert record["status"] == "COMPLETED", record
    assert record["exitCode"] == 0 and record["containerId"] and record["imageId"]
    assert record["executionMode"] == "LOCAL" and record["region"] == "local"
    assert record["startedAtUtc"] and record["completedAtUtc"]
    value = b"compute-arbitrage-local-demo"
    for _ in range(100000):
        value = hashlib.sha256(value).digest()
    assert json.loads(record["stdout"])["sha256"] == value.hex()


def automatic_smoke():
    """Two real tasks dispatched by the background loop, without execute calls."""
    root = Path(__file__).resolve().parents[1]
    run_id = uuid4().hex
    database = root / "state" / f"automatic-smoke-{run_id}.sqlite3"
    source = MemoryMarketSource([MarketSnapshot(slot=0, region="local", resource_type="CPU",
        price_usd_per_unit_hour=0, available_units=1, source="local smoke planning fixture",
        data_kind="SIMULATED")])
    app = create_app(database, tick_interval_seconds=0.2, market_source=source, allow_local_dispatch=True)
    with TestClient(app) as client:
        client.post("/api/engine/pause").raise_for_status()
        for job_id in ("automatic-a", "automatic-b"):
            client.post("/api/jobs", json={"id": job_id, "name": job_id, "arrivalSlot": 0,
                "durationSlots": 1, "deadlineSlot": 3, "resourceType": "CPU", "resourceUnits": 1,
                "allowedRegions": ["local"], "dockerTaskId": "cpu-hash-v1"}).raise_for_status()
        response = client.post("/api/optimize", json={"currentSlot": 0, "executionMode": "LOCAL"})
        response.raise_for_status()
        assert client.get("/api/executions").json() == []
        client.post("/api/engine/resume").raise_for_status()
        end = time.monotonic() + 60
        records = []
        while time.monotonic() < end:
            records = client.get("/api/executions").json()
            if len(records) == 2 and all(row["status"] in {"COMPLETED", "FAILED"} for row in records):
                break
            time.sleep(0.2)
        client.post("/api/engine/pause").raise_for_status()
        report = root / "state" / f"automatic-smoke-{run_id}.json"
        report.write_text(json.dumps({"planningDataKind": "SIMULATED", "executionMode": "LOCAL",
            "executions": records, "engineState": client.get("/api/engine/state").json()}, indent=2), encoding="utf-8")
        assert len(records) == 2, records
        for record in records:
            verify_record(record)
        assert len({row["containerId"] for row in records}) == 2
    restarted = TestClient(create_app(database, tick_interval_seconds=0, market_source=source, allow_local_dispatch=True))
    assert restarted.get("/api/engine/state").json()["dispatch"]["paused"]
    assert restarted.get("/api/executions").json() == records
    print(json.dumps({"status": "COMPLETED", "executionMode": "LOCAL", "automaticJobs": len(records),
        "manualExecuteCalls": 0, "report": str(report)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-dispatch-controls", action="store_true")
    parser.add_argument("--automatic", action="store_true")
    args = parser.parse_args()
    if args.automatic:
        automatic_smoke()
        return
    root = Path(__file__).resolve().parents[1]
    run_id = uuid4().hex
    database = root / "state" / f"docker-smoke-{run_id}.sqlite3"
    source = MemoryMarketSource([MarketSnapshot(slot=0, region="local", resource_type="CPU",
        price_usd_per_unit_hour=0, available_units=1, source="local smoke planning fixture",
        data_kind="SIMULATED")]) if args.check_dispatch_controls else None
    app = create_app(database, tick_interval_seconds=0, market_source=source)
    client = TestClient(app)
    slot = app.state.engine.state().current_slot
    response = client.post("/api/jobs", json={
        "id": "docker-smoke", "name": "Genuine local Docker smoke run", "arrivalSlot": slot,
        "durationSlots": 1, "deadlineSlot": slot + 2, "resourceType": "CPU", "resourceUnits": 1,
        "allowedRegions": ["local"], "dockerTaskId": "cpu-hash-v1",
    })
    response.raise_for_status()
    if args.check_dispatch_controls:
        assert client.post("/api/engine/pause").json()["dispatch"]["paused"]
        assert client.post("/api/execute/docker-smoke").json()["detail"]["code"] == "DISPATCH_PAUSED"
        client = TestClient(create_app(database, tick_interval_seconds=0, market_source=source))
        assert client.get("/api/engine/state").json()["dispatch"]["paused"]
        response = client.post("/api/engine/resume")
        response.raise_for_status()
        assert response.json()["dispatch"]["paused"] is False
        assert client.get("/api/decisions").json()[-1]["action"] == "RUN"
    response = client.post("/api/execute/docker-smoke", json={})
    response.raise_for_status()
    record = response.json()
    if args.check_dispatch_controls:
        assert client.post("/api/engine/pause").json()["dispatch"]["paused"]
    end = time.monotonic() + 60
    while record["status"] not in {"COMPLETED", "FAILED"} and time.monotonic() < end:
        time.sleep(0.2)
        response = client.get("/api/executions/" + record["id"])
        response.raise_for_status()
        record = response.json()
    report = root / "state" / f"docker-smoke-{run_id}.json"
    report.write_text(json.dumps(record, indent=2), encoding="utf-8")
    verify_record(record)
    restarted = TestClient(create_app(database, tick_interval_seconds=0, market_source=source))
    assert restarted.post("/api/execute/docker-smoke").json() == record
    assert restarted.get("/api/jobs").json()[0]["status"] == "COMPLETED"
    print(json.dumps({"status": record["status"], "executionMode": record["executionMode"],
        "exitCode": record["exitCode"], "containerId": record["containerId"], "report": str(report),
        "dispatchControlsChecked": args.check_dispatch_controls}, indent=2))


if __name__ == "__main__":
    main()
