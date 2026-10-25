"""Clients select predefined tasks, never images or commands."""
from datetime import datetime
from typing import Literal
from pydantic import Field
from app.api.schemas import Contract

class ExecuteRequest(Contract):
    pass

class LocalTask(Contract):
    id: str
    name: str
    image: str
    resource_type: Literal["CPU"] = "CPU"
    resource_units: int = 1
    region: Literal["local"] = "local"
    timeout_seconds: int = 30

class TaskCatalog(Contract):
    tasks: list[LocalTask]
    automatic_dispatch_enabled: bool = False

class LocalExecution(Contract):
    id: str
    job_id: str
    task_id: str
    execution_mode: Literal["LOCAL"] = "LOCAL"
    region: Literal["local"] = "local"
    status: Literal["STARTING", "RUNNING", "COMPLETED", "FAILED"] = "STARTING"
    container_name: str
    # Persist and serve the same camelCase key; older records may omit it.
    docker_endpoint: str | None = Field(default=None, alias="dockerEndpoint")
    container_id: str | None = None
    image_id: str
    requested_at_utc: datetime
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    failure_reason: str | None = None
    last_monitor_error: str | None = None
    timeout_requested: bool = False
