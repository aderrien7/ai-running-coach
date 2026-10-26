"""Shared pytest fixtures."""

import os
import tempfile
import pytest

# Point the app at a temp DB so tests never touch a real coach.db
@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH_OVERRIDE", str(db_file))
    # Patch DB_PATH directly in the module
    import mcp_strava.strava_client as sc
    monkeypatch.setattr(sc, "DB_PATH", str(db_file))
    return db_file


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "test_client_secret")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test_flask_secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")
    monkeypatch.setenv("LLM_BACKEND", "claude")


@pytest.fixture
def flask_client(tmp_db):
    import app as flask_app
    from mcp_strava.strava_client import init_db
    flask_app.app.config["TESTING"] = True
    with flask_app.app.app_context():
        init_db()
    with flask_app.app.test_client() as client:
        yield client
