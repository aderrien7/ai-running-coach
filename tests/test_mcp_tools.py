"""Tests for the 5 MCP tools using mocked Strava API responses."""

import pytest
from unittest.mock import patch, MagicMock

# ── Helpers ────────────────────────────────────────────────────────────────

def _mock_api(return_value):
    return patch("mcp_strava.server.api_get", return_value=return_value)


# ── get_athlete_profile ────────────────────────────────────────────────────

def test_get_athlete_profile():
    from mcp_strava.server import _dispatch
    payload = {
        "firstname": "Jane",
        "lastname": "Doe",
        "city": "Paris",
        "country": "France",
        "follower_count": 42,
        "friend_count": 18,
        "id": 9999,
    }
    with _mock_api(payload):
        result = _dispatch("get_athlete_profile", {})
    assert "Jane Doe" in result
    assert "Paris" in result
    assert "France" in result


# ── get_recent_activities ──────────────────────────────────────────────────

def test_get_recent_activities_returns_list():
    from mcp_strava.server import _dispatch
    activities = [
        {
            "id": 1001,
            "name": "Morning Run",
            "type": "Run",
            "distance": 5020.0,
            "moving_time": 1800,
            "start_date_local": "2026-06-01T07:00:00Z",
        },
        {
            "id": 1002,
            "name": "Evening Ride",
            "type": "Ride",
            "distance": 20000.0,
            "moving_time": 3600,
            "start_date_local": "2026-06-02T18:00:00Z",
        },
    ]
    with _mock_api(activities):
        result = _dispatch("get_recent_activities", {"per_page": 2})
    assert "[1001]" in result
    assert "Morning Run" in result
    assert "5.02 km" in result
    assert "[1002]" in result


def test_get_recent_activities_empty():
    from mcp_strava.server import _dispatch
    with _mock_api([]):
        result = _dispatch("get_recent_activities", {})
    assert "No activities found" in result


def test_get_recent_activities_caps_per_page():
    from mcp_strava.server import _dispatch
    with patch("mcp_strava.server.api_get", return_value=[]) as mock_get:
        _dispatch("get_recent_activities", {"per_page": 999})
        _, kwargs = mock_get.call_args
        assert mock_get.call_args[0][1]["per_page"] == 30


# ── get_activity_detail ────────────────────────────────────────────────────

def test_get_activity_detail_run():
    from mcp_strava.server import _dispatch
    activity = {
        "name": "Long Run",
        "type": "Run",
        "start_date_local": "2026-05-20T08:00:00Z",
        "distance": 10010.0,
        "moving_time": 3600,
        "average_speed": 2.78,  # ~6:00/km
        "average_heartrate": 148,
        "max_heartrate": 165,
        "total_elevation_gain": 85,
        "calories": 620,
        "description": "Easy long run",
    }
    with _mock_api(activity):
        result = _dispatch("get_activity_detail", {"activity_id": 1001})
    assert "Long Run" in result
    assert "10.01 km" in result
    assert "148 bpm" in result
    assert "/km" in result


def test_get_activity_detail_non_run_has_no_pace():
    from mcp_strava.server import _dispatch
    activity = {
        "name": "Sunday Ride",
        "type": "Ride",
        "start_date_local": "2026-05-18T09:00:00Z",
        "distance": 40000.0,
        "moving_time": 5400,
        "average_speed": 7.4,
        "average_heartrate": 135,
        "max_heartrate": 160,
        "total_elevation_gain": 300,
        "calories": 900,
        "description": "",
    }
    with _mock_api(activity):
        result = _dispatch("get_activity_detail", {"activity_id": 1003})
    assert "N/A" in result  # pace should be N/A for non-Run


# ── get_athlete_stats ──────────────────────────────────────────────────────

def test_get_athlete_stats():
    from mcp_strava.server import _dispatch
    athlete = {"id": 9999}
    stats = {
        "all_run_totals": {
            "count": 150,
            "distance": 1200000,
            "moving_time": 432000,
            "elevation_gain": 9500,
        },
        "ytd_run_totals": {
            "count": 40,
            "distance": 320000,
            "moving_time": 115200,
        },
    }

    def side_effect(path, params=None):
        if path == "/athlete":
            return athlete
        return stats

    with patch("mcp_strava.server.api_get", side_effect=side_effect):
        result = _dispatch("get_athlete_stats", {})

    assert "1200.0 km" in result
    assert "150" in result
    assert "Year-to-date" in result
    assert "320.0 km" in result


# ── get_activity_zones ─────────────────────────────────────────────────────

def test_get_activity_zones():
    from mcp_strava.server import _dispatch
    zones = [
        {
            "type": "heartrate",
            "distribution_buckets": [
                {"min": 0, "max": 115, "time": 120},
                {"min": 115, "max": 152, "time": 1800},
                {"min": 152, "max": 171, "time": 600},
            ],
        }
    ]
    with _mock_api(zones):
        result = _dispatch("get_activity_zones", {"activity_id": 1001})
    assert "heartrate" in result
    assert "1800 s" in result


def test_get_activity_zones_empty():
    from mcp_strava.server import _dispatch
    with _mock_api([]):
        result = _dispatch("get_activity_zones", {"activity_id": 1001})
    assert "No zone data" in result


# ── unknown tool ───────────────────────────────────────────────────────────

def test_unknown_tool_raises():
    from mcp_strava.server import _dispatch
    with pytest.raises(ValueError, match="Unknown tool"):
        _dispatch("nonexistent_tool", {})
