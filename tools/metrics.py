"""
tools/metrics.py

Writes bot activity and status data to data/metrics.json so the dashboard
can read and visualize it. This module must NEVER crash the bot — every
function is wrapped in try/except so failures are silent.
"""

import json
import time
from datetime import datetime
from pathlib import Path

METRICS_FILE = Path("data/metrics.json")
MAX_RECENT_MESSAGES = 20
MAX_EXCHANGES       = 5   # Full prompt/response exchanges to keep


def _load() -> dict:
    try:
        if METRICS_FILE.exists():
            with open(METRICS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save(data: dict):
    try:
        METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = METRICS_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, default=str)
        tmp.rename(METRICS_FILE)
    except Exception:
        pass


def set_status(status: str):
    try:
        data = _load()
        data["status"] = status
        data["last_update"] = datetime.now().strftime("%H:%M:%S")
        _save(data)
    except Exception:
        pass


def record_message(
    text: str,
    model: str,
    tool: str = "",
    response: str = "",
    tool_chain: list = None,
    elapsed_ms: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
):
    """
    Record a processed message for the activity log and transmission log.

    text       — the user's message
    model      — 'gemini' or 'claude'
    tool       — primary tool called (for the activity badge)
    response   — the bot's full reply text
    tool_chain — list of dicts: [{name, input_summary, result_summary}, ...]
    elapsed_ms — how long the full exchange took in milliseconds
    """
    try:
        data = _load()

        # ── Counters ──────────────────────────────────────────────────────────
        data["total_requests"] = data.get("total_requests", 0) + 1
        if model == "gemini":
            data["gemini_count"] = data.get("gemini_count", 0) + 1
        else:
            data["claude_count"] = data.get("claude_count", 0) + 1

        now = datetime.now()

        # ── Activity log (short, for the top panel) ───────────────────────────
        recent = data.get("recent_messages", [])
        recent.append({
            "text":  text[:60],
            "model": model,
            "tool":  tool,
            "time":  now.strftime("%H:%M"),
        })
        data["recent_messages"] = recent[-MAX_RECENT_MESSAGES:]

        # ── Full transmission log (for the new prompt/response panel) ─────────
        exchanges = data.get("exchanges", [])
        exchanges.append({
            "timestamp":  now.strftime("%H:%M:%S"),
            "date":       now.strftime("%d %b"),
            "model":      model,
            "prompt":     text,
            "response":   response[:800] if response else "",  # cap at 800 chars
            "tool_chain": tool_chain or [],
            "elapsed_ms": elapsed_ms,
        })
        data["exchanges"] = exchanges[-MAX_EXCHANGES:]

        # ── Timing stats ──────────────────────────────────────────────────────
        times = data.get("response_times", [])
        if elapsed_ms > 0:
            times.append(elapsed_ms)
        data["response_times"] = times[-20:]
        if times:
            data["avg_response_ms"] = int(sum(times) / len(times))

        data["last_update"] = now.strftime("%H:%M:%S")
        _save(data)
    except Exception:
        pass


def update_weather(weather_data: dict):
    try:
        data = _load()
        data["weather"] = weather_data
        _save(data)
    except Exception:
        pass


def update_next_match(match_data: dict):
    try:
        data = _load()
        data["next_match"] = match_data
        _save(data)
    except Exception:
        pass


def set_api_status(service: str, ok: bool):
    try:
        data = _load()
        if "api_status" not in data:
            data["api_status"] = {}
        data["api_status"][service] = ok
        _save(data)
    except Exception:
        pass
