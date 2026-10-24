import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Tests never read or modify the development database."""
    monkeypatch.setenv("COMPUTE_DB_PATH", str(tmp_path / "test.sqlite3"))
