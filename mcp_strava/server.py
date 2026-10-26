"""MCP server exposing 5 Strava tools via stdio transport.

Run standalone:  python mcp_strava/server.py
Spawned by app.py as a subprocess — communication over stdin/stdout.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
from mcp_strava.strava_client import api_get

server = Server("strava-coach")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_athlete_profile",
            description=(
                "Fetch the authenticated athlete's Strava profile: "
                "name, location, follower/friend counts."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_recent_activities",
            description=(
                "List the athlete's recent activities (runs, rides, swims…) "
                "with distance, duration and date."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "per_page": {
                        "type": "integer",
                        "description": "Number of activities to return (default 10, max 30).",
                        "default": 10,
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number.",
                        "default": 1,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_activity_detail",
            description=(
                "Fetch full details of a specific activity by ID: "
                "pace, heart rate, elevation gain, calories."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {
                        "type": "integer",
                        "description": "The Strava activity ID.",
                    }
                },
                "required": ["activity_id"],
            },
        ),
        types.Tool(
            name="get_athlete_stats",
            description=(
                "Fetch the athlete's all-time and year-to-date totals "
                "for running, cycling and swimming."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_activity_zones",
            description=(
                "Fetch heart-rate and power distribution zones for a specific activity."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {
                        "type": "integer",
                        "description": "The Strava activity ID.",
                    }
                },
                "required": ["activity_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = _dispatch(name, arguments)
        return [types.TextContent(type="text", text=result)]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"Error: {exc}")]


def _dispatch(name: str, args: dict) -> str:
    if name == "get_athlete_profile":
        d = api_get("/athlete")
        return (
            f"Athlete: {d.get('firstname', '')} {d.get('lastname', '')}\n"
            f"City: {d.get('city', 'N/A')}, {d.get('country', 'N/A')}\n"
            f"Followers: {d.get('follower_count', 0)}, Following: {d.get('friend_count', 0)}\n"
            f"ID: {d.get('id')}"
        )

    if name == "get_recent_activities":
        per_page = min(int(args.get("per_page", 10)), 30)
        page = int(args.get("page", 1))
        activities = api_get("/athlete/activities", {"per_page": per_page, "page": page})
        if not activities:
            return "No activities found."
        lines = []
        for a in activities:
            dist_km = round(a.get("distance", 0) / 1000, 2)
            duration_min = round(a.get("moving_time", 0) / 60, 1)
            date = a.get("start_date_local", "")[:10]
            lines.append(
                f"[{a['id']}] {date} — {a['name']} ({a['type']}) "
                f"{dist_km} km in {duration_min} min"
            )
        return "\n".join(lines)

    if name == "get_activity_detail":
        a = api_get(f"/activities/{int(args['activity_id'])}")
        dist_km = round(a.get("distance", 0) / 1000, 2)
        duration_min = round(a.get("moving_time", 0) / 60, 1)
        avg_pace = ""
        if a.get("average_speed", 0) > 0 and a.get("type") == "Run":
            sec_per_km = 1000 / a["average_speed"]
            avg_pace = f"{int(sec_per_km // 60)}:{int(sec_per_km % 60):02d}/km"
        return (
            f"Activity: {a['name']} ({a['type']})\n"
            f"Date: {a.get('start_date_local', '')[:10]}\n"
            f"Distance: {dist_km} km\n"
            f"Duration: {duration_min} min\n"
            f"Average pace: {avg_pace or 'N/A'}\n"
            f"Avg heart rate: {a.get('average_heartrate', 'N/A')} bpm\n"
            f"Max heart rate: {a.get('max_heartrate', 'N/A')} bpm\n"
            f"Elevation gain: {a.get('total_elevation_gain', 0)} m\n"
            f"Calories: {a.get('calories', 'N/A')}\n"
            f"Description: {a.get('description', '')}"
        )

    if name == "get_athlete_stats":
        athlete = api_get("/athlete")
        stats = api_get(f"/athletes/{athlete['id']}/stats")
        r = stats.get("all_run_totals", {})
        yr = stats.get("ytd_run_totals", {})
        return (
            f"All-time running:\n"
            f"  Activities: {r.get('count', 0)}\n"
            f"  Distance: {round(r.get('distance', 0) / 1000, 1)} km\n"
            f"  Time: {round(r.get('moving_time', 0) / 3600, 1)} h\n"
            f"  Elevation: {r.get('elevation_gain', 0)} m\n"
            f"\nYear-to-date running:\n"
            f"  Activities: {yr.get('count', 0)}\n"
            f"  Distance: {round(yr.get('distance', 0) / 1000, 1)} km\n"
            f"  Time: {round(yr.get('moving_time', 0) / 3600, 1)} h"
        )

    if name == "get_activity_zones":
        zones = api_get(f"/activities/{int(args['activity_id'])}/zones")
        if not zones:
            return "No zone data available for this activity."
        lines = []
        for group in zones:
            lines.append(f"\n{group.get('type', 'unknown')} zones:")
            for b in group.get("distribution_buckets", []):
                lines.append(f"  [{b.get('min')}-{b.get('max')}]: {b.get('time', 0)} s")
        return "\n".join(lines)

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
