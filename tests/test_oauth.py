"""Tests for Strava OAuth2 flow and token management."""

import time
from unittest.mock import MagicMock, patch

# ── DB initialisation ──────────────────────────────────────────────────────

def test_init_db_creates_tables(tmp_db):
    import sqlite3

    from mcp_strava.strava_client import init_db
    init_db()
    conn = sqlite3.connect(str(tmp_db))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tokens" in tables
    assert "messages" in tables
    conn.close()


# ── Token storage ──────────────────────────────────────────────────────────

def test_save_and_get_token(tmp_db):
    from mcp_strava.strava_client import get_token, init_db, save_token
    init_db()
    future = int(time.time()) + 3600
    save_token("acc_123", "ref_456", future, athlete_id=42)
    token = get_token()
    assert token["access_token"] == "acc_123"
    assert token["refresh_token"] == "ref_456"
    assert token["athlete_id"] == 42


def test_get_token_returns_none_when_empty(tmp_db):
    from mcp_strava.strava_client import get_token, init_db
    init_db()
    assert get_token() is None


def test_save_token_replaces_previous(tmp_db):
    from mcp_strava.strava_client import get_token, init_db, save_token
    init_db()
    future = int(time.time()) + 3600
    save_token("old_token", "old_ref", future)
    save_token("new_token", "new_ref", future)
    assert get_token()["access_token"] == "new_token"


# ── Token refresh ──────────────────────────────────────────────────────────

def test_refresh_not_needed_when_token_valid(tmp_db):
    from mcp_strava.strava_client import init_db, refresh_token_if_needed, save_token
    init_db()
    future = int(time.time()) + 7200
    save_token("valid_token", "ref", future)
    result = refresh_token_if_needed()
    assert result == "valid_token"


def test_refresh_performed_when_token_expired(tmp_db):
    from mcp_strava.strava_client import init_db, refresh_token_if_needed, save_token
    init_db()
    past = int(time.time()) - 100  # already expired
    save_token("expired_token", "old_ref", past)

    new_expiry = int(time.time()) + 3600
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "access_token": "refreshed_token",
        "refresh_token": "new_ref",
        "expires_at": new_expiry,
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("mcp_strava.strava_client.requests.post", return_value=mock_resp):
        result = refresh_token_if_needed()

    assert result == "refreshed_token"


def test_refresh_returns_none_when_no_token(tmp_db):
    from mcp_strava.strava_client import init_db, refresh_token_if_needed
    init_db()
    assert refresh_token_if_needed() is None


# ── OAuth URL generation ───────────────────────────────────────────────────

def test_get_auth_url_contains_client_id():
    from mcp_strava.strava_client import get_auth_url
    url = get_auth_url("http://localhost:5000/callback")
    assert "test_client_id" in url
    assert "code" in url
    assert "scope" in url


def test_get_auth_url_contains_redirect_uri():
    from mcp_strava.strava_client import get_auth_url
    url = get_auth_url("http://localhost:5000/callback")
    assert "localhost" in url


# ── OAuth code exchange ────────────────────────────────────────────────────

def test_exchange_code_calls_strava(tmp_db):
    from mcp_strava.strava_client import exchange_code
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "access_token": "new_acc",
        "refresh_token": "new_ref",
        "expires_at": int(time.time()) + 3600,
        "athlete": {"id": 77},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("mcp_strava.strava_client.requests.post", return_value=mock_resp) as mock_post:
        result = exchange_code("auth_code_xyz", "http://localhost:5000/callback")

    assert result["access_token"] == "new_acc"
    call_kwargs = mock_post.call_args[1]["data"]
    assert call_kwargs["code"] == "auth_code_xyz"
    assert call_kwargs["grant_type"] == "authorization_code"


# ── Flask OAuth routes ─────────────────────────────────────────────────────

def test_index_redirects_to_connect_when_unauthenticated(flask_client):
    resp = flask_client.get("/")
    assert resp.status_code == 200
    assert b"Connect" in resp.data


def test_auth_strava_redirects(flask_client):
    resp = flask_client.get("/auth/strava")
    assert resp.status_code == 302
    assert "strava.com" in resp.headers["Location"]


def test_callback_with_error_redirects(flask_client):
    resp = flask_client.get("/callback?error=access_denied")
    assert resp.status_code == 302
    assert "error=auth_denied" in resp.headers["Location"]


def test_callback_missing_code_redirects(flask_client):
    resp = flask_client.get("/callback")
    assert resp.status_code == 302
    assert "error=auth_denied" in resp.headers["Location"]


def test_chat_returns_401_when_unauthenticated(flask_client):
    resp = flask_client.post(
        "/api/chat",
        json={"message": "hello"},
        content_type="application/json",
    )
    assert resp.status_code == 401


def test_chat_returns_400_on_empty_message(flask_client, tmp_db):
    from mcp_strava.strava_client import init_db, save_token
    init_db()
    save_token("tok", "ref", int(time.time()) + 3600)
    resp = flask_client.post(
        "/api/chat",
        json={"message": "  "},
        content_type="application/json",
    )
    assert resp.status_code == 400
