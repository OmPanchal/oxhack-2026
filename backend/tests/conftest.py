import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Tests never read or modify the development database."""
    monkeypatch.setenv("COMPUTE_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("COMPUTE_TICK_SECONDS", "0")
    monkeypatch.delenv("COMPUTE_MARKET_FILE", raising=False)
    monkeypatch.delenv("COMPUTE_ORIGIN_UTC", raising=False)
    monkeypatch.delenv("COMPUTE_MARKET_SOURCE", raising=False)
    monkeypatch.delenv("COMPUTE_AWS_REGIONS", raising=False)
    monkeypatch.delenv("COMPUTE_AWS_INSTANCE_TYPES", raising=False)
    monkeypatch.delenv("COMPUTE_ALLOW_LOCAL_DISPATCH", raising=False)
