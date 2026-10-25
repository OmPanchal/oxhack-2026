"""Fixed local Docker adapter. No user-controlled image, command or mounts."""
import os
from pathlib import Path
from datetime import datetime
from app.api.execution_schemas import LocalTask
from app.engine.forecast_bridge import EngineUnavailable

TASK = LocalTask(id="cpu-hash-v1", name="Deterministic SHA-256 CPU demonstration",
                 image="python:3.11-alpine")
SCRIPT = """import hashlib,json
value=b'compute-arbitrage-local-demo'
for _ in range(100000):
    value=hashlib.sha256(value).digest()
print(json.dumps({'taskId':'cpu-hash-v1','iterations':100000,'sha256':value.hex()}))
"""
LOG_LIMIT = 65536


def docker_time(value):
    if not value or value.startswith("0001-"):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class DockerAdapter:
    @staticmethod
    def endpoint():
        if os.name == 'nt':
            return 'npipe:////./pipe/docker_engine'
        # Docker Desktop has a separate daemon on Linux. Prefer its socket
        # over the system daemon so containers appear in the Desktop UI.
        sockets = [Path.home()/'.docker/desktop/docker.sock', Path.home()/'.docker/run/docker.sock',
                   Path('/var/run/docker.sock')]
        socket = next((path for path in sockets if path.exists()), sockets[-1])
        return f'unix://{socket}'

    def client(self, endpoint=None):
        # Explicit local socket: remote contexts/DOCKER_HOST cannot be labeled LOCAL.
        client = None
        try:
            import docker
            # Docker Desktop commonly exposes a per-user local socket. Never
            # inherit a remote DOCKER_HOST/context while labelling execution LOCAL.
            endpoint = endpoint or self.endpoint()
            if not endpoint.startswith(('unix:///', 'npipe:////./pipe/')):
                raise ValueError('LOCAL execution requires a local Docker socket')
            client = docker.DockerClient(base_url=endpoint, timeout=15)
            if client.info().get("OSType") != "linux":
                raise ValueError("Local execution requires a Linux Docker engine")
            return client
        except Exception as exc:
            if client is not None:
                client.close()
            raise EngineUnavailable("DOCKER_UNAVAILABLE", str(exc)) from exc

    def prepare(self):
        self.prepared_endpoint = self.endpoint()
        client = self.client(self.prepared_endpoint)
        try:
            from docker.errors import ImageNotFound
            try:
                image = client.images.get(TASK.image)
            except ImageNotFound:
                image = client.images.pull(TASK.image)
            return image.id
        except Exception as exc:
            raise EngineUnavailable("DOCKER_IMAGE_UNAVAILABLE", str(exc)) from exc
        finally:
            client.close()

    def launch(self, execution):
        client = self.client(execution.docker_endpoint) if execution.docker_endpoint else self.client()
        try:
            container = client.containers.create(
                execution.image_id, ["python", "-I", "-u", "-c", SCRIPT],
                name=execution.container_name,
                labels={"compute.execution": execution.id, "compute.job": execution.job_id},
                network_disabled=True, read_only=True, user="65534:65534",
                cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
                mem_limit="256m", nano_cpus=1000000000, pids_limit=64,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
                log_config={"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
            )
            # A lost response may still mean it ran. Never retry start.
            container.start()
        finally:
            client.close()

    def inspect(self, execution):
        from docker.errors import NotFound
        client = self.client(execution.docker_endpoint) if execution.docker_endpoint else self.client()
        try:
            try:
                container = client.containers.get(execution.container_name)
            except NotFound:
                return None
            attrs = container.attrs
            if attrs["Config"].get("Labels", {}).get("compute.execution") != execution.id:
                raise ValueError("Container identity does not match execution")
            state = attrs["State"]
            result = dict(container_id=container.id, state=state["Status"],
                started_at_utc=docker_time(state.get("StartedAt")),
                completed_at_utc=docker_time(state.get("FinishedAt")),
                exit_code=state.get("ExitCode"), error=state.get("Error") or None,
                oom=state.get("OOMKilled", False))
            for name in ("stdout", "stderr"):
                try:
                    raw = container.logs(stdout=name == "stdout", stderr=name == "stderr", tail=1000)
                    result[name] = raw[:LOG_LIMIT].decode("utf-8", errors="replace")
                    result[name + "_truncated"] = len(raw) > LOG_LIMIT or raw.count(b'\n') >= 1000
                except Exception:
                    # Confirmed exit state is still authoritative if the log API
                    # fails. Retain previously captured output and disclose gaps.
                    result["log_error"] = "Container state observed, but one or more log streams could not be read"
            return result
        finally:
            client.close()

    def kill(self, execution):
        client = self.client(execution.docker_endpoint) if execution.docker_endpoint else self.client()
        try:
            container = client.containers.get(execution.container_name)
            if container.attrs["Config"].get("Labels", {}).get("compute.execution") != execution.id:
                raise ValueError("Container identity does not match execution")
            container.kill()
        finally:
            client.close()
