"""Strava OAuth2 client and REST API wrapper."""

import os
import sqlite3
import time

import requests

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "coach.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                athlete_id INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def get_token():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tokens ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def save_token(access_token, refresh_token, expires_at, athlete_id=None):
    with get_db() as conn:
        conn.execute("DELETE FROM tokens")
        conn.execute(
            "INSERT INTO tokens (access_token, refresh_token, expires_at, athlete_id) "
            "VALUES (?, ?, ?, ?)",
            (access_token, refresh_token, expires_at, athlete_id),
        )


def refresh_token_if_needed():
    token = get_token()
    if not token:
        return None
    if time.time() < token["expires_at"] - 60:
        return token["access_token"]
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    save_token(data["access_token"], data["refresh_token"], data["expires_at"])
    return data["access_token"]


def get_auth_url(redirect_uri):
    from urllib.parse import urlencode
    params = {
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "read,activity:read_all,profile:read_all",
    }
    return f"{STRAVA_AUTH_URL}?{urlencode(params)}"


def exchange_code(code, redirect_uri):
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def api_get(path, params=None):
    token = refresh_token_if_needed()
    if not token:
        raise RuntimeError("Not authenticated with Strava")
    resp = requests.get(
        f"{STRAVA_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
