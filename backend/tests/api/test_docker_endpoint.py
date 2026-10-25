from pathlib import Path

import pytest

from app.execution.docker import DockerAdapter


def test_desktop_socket_wins_over_system_socket(monkeypatch):
    monkeypatch.setattr('app.execution.docker.os.name', 'posix')
    monkeypatch.setattr(Path, 'home', lambda: Path('/home/test'))
    monkeypatch.setattr(Path, 'exists', lambda path: str(path) in {
        '/home/test/.docker/desktop/docker.sock', '/var/run/docker.sock'})
    assert DockerAdapter.endpoint() == 'unix:///home/test/.docker/desktop/docker.sock'


def test_system_socket_used_when_desktop_is_absent(monkeypatch):
    monkeypatch.setattr('app.execution.docker.os.name', 'posix')
    monkeypatch.setattr(Path, 'exists', lambda path: str(path) == '/var/run/docker.sock')
    assert DockerAdapter.endpoint() == 'unix:///var/run/docker.sock'


def test_inspection_stays_on_saved_engine(monkeypatch):
    pytest.importorskip('docker')
    from app.api.execution_schemas import LocalExecution
    from datetime import datetime, timezone
    from types import SimpleNamespace
    record=LocalExecution(id='test',job_id='job',task_id='cpu-hash-v1',container_name='compute-test',
        image_id='image',requested_at_utc=datetime.now(timezone.utc),docker_endpoint='unix:///saved/docker.sock')
    calls=[]
    def client(endpoint=None):
        calls.append(endpoint)
        def missing(name):
            from docker.errors import NotFound
            raise NotFound('not found')
        return SimpleNamespace(containers=SimpleNamespace(get=missing),close=lambda:None)
    adapter=DockerAdapter()
    monkeypatch.setattr(adapter,'client',client)
    assert adapter.inspect(record) is None
    assert calls == ['unix:///saved/docker.sock']


def test_saved_camelcase_endpoint_survives_reading_and_legacy_records():
    from app.api.execution_schemas import LocalExecution
    payload = {
        'id': 'saved', 'jobId': 'job', 'taskId': 'cpu-hash-v1',
        'containerName': 'compute-saved', 'imageId': 'image',
        'requestedAtUtc': '2026-10-25T10:00:00Z',
        'dockerEndpoint': 'unix:///home/om/.docker/desktop/docker.sock',
    }
    record = LocalExecution.model_validate(payload)
    assert record.docker_endpoint == payload['dockerEndpoint']
    restored = LocalExecution.model_validate_json(record.model_dump_json(by_alias=True))
    assert restored.docker_endpoint == payload['dockerEndpoint']
    del payload['dockerEndpoint']
    assert LocalExecution.model_validate(payload).docker_endpoint is None


def test_execution_api_reads_saved_endpoint_without_dropping_it(tmp_path):
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.jobs.store import JobStore
    from app.api.schemas import JobCreate
    from app.database import Database
    import json

    database = Database(tmp_path / 'saved-execution.sqlite3')
    store = JobStore(database)
    store.create(JobCreate(id='job', name='Local task', arrival_slot=0,
        duration_slots=1, deadline_slot=2, resource_type='CPU', resource_units=1,
        allowed_regions=['local'], docker_task_id='cpu-hash-v1'))
    payload = {'id': 'saved', 'jobId': 'job', 'taskId': 'cpu-hash-v1',
        'status': 'COMPLETED', 'containerName': 'compute-saved', 'imageId': 'image',
        'exitCode': 0, 'stdout': 'saved output',
        'requestedAtUtc': '2026-10-25T10:00:00Z',
        'dockerEndpoint': 'unix:///home/om/.docker/desktop/docker.sock'}
    with database.transaction() as connection:
        connection.execute('INSERT INTO local_executions(id, job_id, payload) VALUES (?, ?, ?)',
                           ('saved', 'job', json.dumps(payload)))
    client = TestClient(create_app(database.path, clock=lambda: datetime(2026,10,25,10,tzinfo=timezone.utc)))
    response = client.get('/api/executions')
    assert response.status_code == 200
    assert response.json()[0]['dockerEndpoint'] == payload['dockerEndpoint']
    assert response.json()[0]['stdout'] == 'saved output'
