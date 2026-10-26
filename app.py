"""Running Coach — Flask application entry point.

LLM_BACKEND (set in .env):
  "claude"  — Anthropic API, model claude-sonnet-4-6
  "ollama"  — Local Ollama server (OLLAMA_MODEL, default qwen2.5:7b)

Start:  python app.py
"""

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template, request

load_dotenv()

import anthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from openai import OpenAI

from mcp_strava.strava_client import (
    exchange_code,
    get_auth_url,
    get_db,
    get_token,
    init_db,
    save_token,
)

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

CALLBACK_URL = "http://localhost:5000/callback"
MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mcp_strava", "server.py")

LLM_BACKEND = os.environ.get("LLM_BACKEND", "claude").lower()
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

SYSTEM_PROMPT = (
    "You are a knowledgeable, encouraging personal running coach. "
    "You have access to the athlete's Strava data via tools. "
    "Respond in the same language the user writes in. "
    "Analyse their performance, identify trends, and give concrete, "
    "personalised advice. Always use the Strava tools when the user "
    "asks about their training data."
)


# ── App initialisation ─────────────────────────────────────────────────────

with app.app_context():
    init_db()


# ── Conversation history ───────────────────────────────────────────────────

def load_history():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id ASC"
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def save_message(role: str, content: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (role, content) VALUES (?, ?)", (role, content)
        )


def clear_history():
    with get_db() as conn:
        conn.execute("DELETE FROM messages")


# ── MCP subprocess parameters ──────────────────────────────────────────────

def _mcp_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_PATH],
        env={**os.environ},
    )


# ── Claude backend ─────────────────────────────────────────────────────────

async def _chat_claude(user_message: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    async with stdio_client(_mcp_params()) as (read, write):  # noqa: SIM117
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            tools_result = await mcp_session.list_tools()

            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema,
                }
                for t in tools_result.tools
            ]

            history = load_history()
            history.append({"role": "user", "content": user_message})
            messages = list(history)
            full_response = ""

            while True:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )

                for block in response.content:
                    if block.type == "text":
                        full_response += block.text

                if response.stop_reason == "end_turn":
                    break

                if response.stop_reason == "tool_use":
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            result = await mcp_session.call_tool(
                                block.name, block.input
                            )
                            result_text = "\n".join(
                                c.text for c in result.content if hasattr(c, "text")
                            )
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_text,
                            })
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})
                else:
                    break

    return full_response


# ── Ollama backend ─────────────────────────────────────────────────────────

async def _chat_ollama(user_message: str) -> str:
    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    async with stdio_client(_mcp_params()) as (read, write):  # noqa: SIM117
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            tools_result = await mcp_session.list_tools()

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema,
                    },
                }
                for t in tools_result.tools
            ]

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for m in load_history():
                messages.append({"role": m["role"], "content": m["content"]})
            messages.append({"role": "user", "content": user_message})

            full_response = ""

            while True:
                response = client.chat.completions.create(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                msg = response.choices[0].message

                if msg.content:
                    full_response += msg.content

                if not msg.tool_calls:
                    break

                messages.append(msg)
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    result = await mcp_session.call_tool(tc.function.name, args)
                    result_text = "\n".join(
                        c.text for c in result.content if hasattr(c, "text")
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })

    return full_response


# ── Dispatcher ─────────────────────────────────────────────────────────────

async def chat_with_llm(user_message: str) -> str:
    if LLM_BACKEND == "ollama":
        return await _chat_ollama(user_message)
    return await _chat_claude(user_message)


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        authenticated=bool(get_token()),
        backend=LLM_BACKEND,
        ollama_model=OLLAMA_MODEL,
    )


@app.route("/auth/strava")
def auth_strava():
    return redirect(get_auth_url(CALLBACK_URL))


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if request.args.get("error") or not code:
        return redirect("/?error=auth_denied")
    data = exchange_code(code, CALLBACK_URL)
    save_token(
        data["access_token"],
        data["refresh_token"],
        data["expires_at"],
        data.get("athlete", {}).get("id"),
    )
    return redirect("/")


@app.route("/auth/logout")
def logout():
    with get_db() as conn:
        conn.execute("DELETE FROM tokens")
    return redirect("/")


@app.route("/api/chat", methods=["POST"])
def chat():
    if not get_token():
        return jsonify({"error": "Not authenticated with Strava"}), 401

    user_message = (request.get_json() or {}).get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    def generate():
        try:
            reply = asyncio.run(chat_with_llm(user_message))
            save_message("user", user_message)
            save_message("assistant", reply)
            yield f"data: {json.dumps({'text': reply, 'done': True})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc), 'done': True})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/history")
def history():
    return jsonify(load_history())


@app.route("/api/clear", methods=["POST"])
def clear():
    clear_history()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
