"""Person 2: replace with SQLite; this development store is process-local."""
from app.api.schemas import Job, JobCreate

class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def list(self) -> list[Job]:
        return list(self._jobs.values())

    def create(self, payload: JobCreate) -> Job:
        if payload.id in self._jobs:
            raise ValueError("Job ID already exists")
        job = Job(**payload.model_dump())
        self._jobs[job.id] = job
        return job
