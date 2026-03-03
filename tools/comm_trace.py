"""
tools/comm_trace.py

Lightweight per-request trace recorder for the Telegram ↔ bot communication layer.

Usage in main.py:
    trace = new_trace("text", user_message)
    t0 = time.monotonic()
    ...
    t_model = time.monotonic()
    # ... AI call ...
    mark_stage(trace, "model", t_model)
    ...
    finish_trace(trace, status="ok")

Each trace is a dict:
    id        — 6-char hex (e.g. "a3f9b1")
    source    — "text" or "voice"
    msg       — first 60 chars of user message
    ts        — HH:MM:SS timestamp when trace was created
    date      — DD Mon
    stages    — dict of stage_name → elapsed_ms
    status    — "ok" | "error" | "timeout" | "in_progress"
    error     — error string if status == "error", else None

Query via: GET /api/traces  (internal dashboard only)
File:       data/traces.json  (last MAX_TRACES entries)

Never crashes the bot — all public functions wrapped in try/except.
"""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

TRACES_FILE = Path("data/traces.json")
MAX_TRACES  = 100


def new_trace(source: str, message_preview: str) -> dict:
    """
    Create and return a new trace context dict.
    Call this at the very start of request handling.
    """
    now = datetime.now()
    return {
        "id":     uuid.uuid4().hex[:6],
        "source": source,                      # "text" or "voice"
        "msg":    message_preview[:60],
        "ts":     now.strftime("%H:%M:%S"),
        "date":   now.strftime("%d %b"),
        "stages": {},
        "status": "in_progress",
        "error":  None,
    }


def mark_stage(trace: dict, stage: str, start: float) -> None:
    """
    Record elapsed milliseconds for a named stage.

    stage — one of: "route", "transcribe", "model", "tool", "send", "total"
    start — time.monotonic() value captured before the stage began
    """
    try:
        trace["stages"][stage] = round((time.monotonic() - start) * 1000)
    except Exception:
        pass


def finish_trace(trace: dict, status: str = "ok", error: str = None) -> None:
    """
    Finalise the trace and persist it to data/traces.json.

    status — "ok", "error", or "timeout"
    error  — short error description (first 200 chars used)
    """
    try:
        trace["status"] = status
        if error:
            trace["error"] = str(error)[:200]
        _persist(trace)
    except Exception:
        pass


# ── Internal ──────────────────────────────────────────────────────────────────

def _persist(trace: dict) -> None:
    """Append trace to traces.json (ring buffer, keeps last MAX_TRACES)."""
    try:
        TRACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing: list = []
        if TRACES_FILE.exists():
            try:
                existing = json.loads(TRACES_FILE.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        existing.append(trace)
        existing = existing[-MAX_TRACES:]
        tmp = TRACES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, default=str), encoding="utf-8")
        tmp.rename(TRACES_FILE)
    except Exception:
        pass
