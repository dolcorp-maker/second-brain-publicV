"""
web_dashboard.py

Flask web server that serves the Second Brain dashboard.
Runs on port 8080. Access at http://<SERVER_IP>:8080

Architecture:
- /              → internal: full dashboard (no login needed on LAN)
                   external: lite dashboard (login required, max 4 concurrent sessions)
- /architecture  → architecture + API panel (internal only)
- /login         → login page (external only)
- /logout        → clear session
- /api/data      → live metrics JSON
- /api/system    → real-time system stats (internal only)
- /api/config    → API keys from .env (internal only)
- /api/log       → bot log lines (internal only)
- /api/thoughts  → thoughts data (internal only)
- /api/tasks     → tasks data (internal only)
- /api/traces    → last 100 per-request comm traces (internal only)
"""

import json
import time
import os
import psutil
from pathlib import Path
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv, dotenv_values
from flask import (
    Flask, render_template, jsonify, request,
    session, redirect, url_for, send_file
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

app = Flask(__name__)
# Global rate limit removed — was exhausting 200/day cap in ~2min from kiosk polling.
# Login endpoint still has its own 3/min limit below.
limiter = Limiter(get_remote_address, app=app)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

METRICS_FILE = Path("data/metrics.json")
START_TIME   = time.time()

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
if not DASHBOARD_PASSWORD:
    raise RuntimeError("DASHBOARD_PASSWORD is not set in .env — refusing to start.")

SERVER_IP = os.getenv("SERVER_IP")
if not SERVER_IP:
    raise RuntimeError("SERVER_IP is not set in .env — refusing to start.")

# LAN_SUBNET: IP prefix for your local network (e.g. "192.168.1.").
# Requests from matching IPs get the full dashboard without login.
# Leave unset to disable LAN detection (external login required for everyone).
LAN_SUBNET = os.getenv("LAN_SUBNET", "")

# ── External session cap ───────────────────────────────────────────────────────
# Tracks external sessions: {session_token: last_seen_timestamp}
# Max 4 concurrent external visitors. Sessions expire after 30 min of inactivity.
MAX_EXTERNAL_SESSIONS = 4
SESSION_TTL = 30 * 60  # 30 minutes in seconds
_external_sessions: dict = {}  # session_id → last_seen float


def _cleanup_expired_sessions():
    """Remove sessions inactive for more than SESSION_TTL seconds."""
    now = time.time()
    expired = [sid for sid, ts in _external_sessions.items() if now - ts > SESSION_TTL]
    for sid in expired:
        _external_sessions.pop(sid, None)


def _register_external_session() -> bool:
    """
    Register or refresh the current external session.
    Returns True if allowed, False if at capacity.
    """
    _cleanup_expired_sessions()
    sid = session.get("session_id")
    now = time.time()

    if sid and sid in _external_sessions:
        # Known session — refresh timestamp and allow
        _external_sessions[sid] = now
        return True

    if len(_external_sessions) >= MAX_EXTERNAL_SESSIONS:
        return False

    # New session — assign an ID and register it
    import secrets
    new_sid = secrets.token_hex(16)
    session["session_id"] = new_sid
    _external_sessions[new_sid] = now
    return True


# ── Auth helpers ───────────────────────────────────────────────────────────────

def is_local():
    real_ip = request.headers.get("X-Real-IP", request.remote_addr)
    if real_ip in {"127.0.0.1", "::1", SERVER_IP}:
        return True
    if LAN_SUBNET and real_ip.startswith(LAN_SUBNET):
        return True
    return False


def login_required(f):
    """Full auth — used for internal-only API routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if is_local() or session.get("logged_in"):
            return f(*args, **kwargs)
        return redirect(url_for("login"))
    return decorated


def external_login_required(f):
    """Auth for external-facing routes — also enforces session cap."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if is_local():
            return f(*args, **kwargs)
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if not _register_external_session():
            return render_template("capacity.html"), 429
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("3 per minute")
def login():
    if is_local():
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            if not _register_external_session():
                session.clear()
                return render_template("capacity.html"), 429
            return redirect(url_for("index"))
        error = "Wrong password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    sid = session.get("session_id")
    if sid:
        _external_sessions.pop(sid, None)
    session.clear()
    return redirect(url_for("login"))


# ── Page routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if is_local():
        return render_template("dashboard.html")
    # External — requires login + session cap
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if not _register_external_session():
        return render_template("capacity.html"), 429
    return render_template("dashboard_external.html")


@app.route("/architecture")
@login_required
def architecture():
    arch_path = Path("architecture.html")
    if arch_path.exists():
        return send_file(str(arch_path.absolute()))
    return "Architecture page not found", 404


# ── Data helpers ───────────────────────────────────────────────────────────────

def read_metrics() -> dict:
    try:
        if METRICS_FILE.exists():
            with open(METRICS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_system_stats() -> dict:
    stats = {
        "cpu_percent":   psutil.cpu_percent(interval=0.1),
        "ram_percent":   psutil.virtual_memory().percent,
        "ram_used_mb":   psutil.virtual_memory().used  // (1024 * 1024),
        "ram_total_mb":  psutil.virtual_memory().total // (1024 * 1024),
        "disk_percent":  psutil.disk_usage("/").percent,
        "disk_used_gb":  psutil.disk_usage("/").used  / (1024 ** 3),
        "disk_total_gb": psutil.disk_usage("/").total / (1024 ** 3),
        "uptime_seconds": int(time.time() - START_TIME),
    }
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ["cpu_thermal", "coretemp", "bcm2835"]:
                if key in temps and temps[key]:
                    stats["cpu_temp"] = round(temps[key][0].current, 1)
                    break
            else:
                first_key = list(temps.keys())[0]
                if temps[first_key]:
                    stats["cpu_temp"] = round(temps[first_key][0].current, 1)
    except Exception:
        stats["cpu_temp"] = None
    return stats


# ── API routes — INTERNAL ONLY ─────────────────────────────────────────────────

@app.route("/api/data")
@login_required
def api_data():
    return jsonify(read_metrics())


@app.route("/api/system")
@login_required
def api_system():
    return jsonify(get_system_stats())


@app.route("/api/thoughts")
@login_required
def api_thoughts():
    try:
        p = Path("data/thoughts.json")
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            if isinstance(data, list):
                return jsonify({"thoughts": data})
            return jsonify(data)
    except Exception:
        pass
    return jsonify({"thoughts": []})


@app.route("/api/tasks")
@login_required
def api_tasks():
    try:
        p = Path("data/tasks.json")
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            if isinstance(data, list):
                return jsonify({"tasks": data})
            return jsonify(data)
    except Exception:
        pass
    return jsonify({"tasks": []})


@app.route("/api/traces")
@login_required
def api_traces():
    """
    Return the last 100 per-request communication traces written by tools/comm_trace.py.

    Each trace:
        id        — 6-char hex request identifier
        source    — "text" or "voice"
        msg       — first 60 chars of user message
        ts        — HH:MM:SS
        date      — DD Mon
        stages    — {stage_name: elapsed_ms} (model, send, total, ...)
        status    — "ok" | "error" | "timeout" | "in_progress"
        error     — error string or null

    Use for: debugging slow requests, spotting timeouts, correlating errors with messages.
    Query example: curl http://<SERVER_IP>:8080/api/traces | python3 -m json.tool
    """
    try:
        p = Path("data/traces.json")
        if p.exists():
            traces = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(traces, list):
                return jsonify({"traces": traces[-100:], "count": len(traces)})
    except Exception as e:
        return jsonify({"traces": [], "error": str(e)})
    return jsonify({"traces": [], "count": 0})


@app.route("/api/services")
@login_required
def api_services():
    import subprocess
    SERVICES = [
        ("secondbrain.service",           "Bot"),
        ("secondbrain-dashboard.service", "Dashboard"),
        ("secondbrain-scheduler.service", "Scheduler"),
    ]
    results = []
    for unit, display in SERVICES:
        try:
            out = subprocess.check_output(
                ["systemctl", "show", unit,
                 "--property=ActiveState,SubState,ExecMainStartTimestamp"],
                text=True, timeout=3
            )
            props = {}
            for line in out.strip().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v

            active = props.get("ActiveState", "") == "active"
            state  = props.get("SubState", "unknown")
            uptime_str = ""
            ts = props.get("ExecMainStartTimestamp", "")
            if ts and ts != "n/a":
                try:
                    parts = ts.split()
                    if len(parts) >= 3:
                        dt = datetime.strptime(parts[1] + " " + parts[2], "%Y-%m-%d %H:%M:%S")
                        delta = datetime.now() - dt
                        s = int(delta.total_seconds())
                        if s < 3600:
                            uptime_str = f"{s//60}m"
                        elif s < 86400:
                            uptime_str = f"{s//3600}h {(s%3600)//60}m"
                        else:
                            uptime_str = f"{s//86400}d {(s%86400)//3600}h"
                except Exception:
                    pass

            results.append({"unit": unit, "display": display,
                             "active": active, "state": state, "uptime": uptime_str})
        except Exception:
            results.append({"unit": unit, "display": display,
                             "active": False, "state": "error", "uptime": ""})
    return jsonify({"services": results})


@app.route("/api/config")
@login_required
def api_config():
    """Return masked API keys — confirms they are set without exposing values."""
    env = dotenv_values(".env")

    def mask(val):
        if not val:
            return ""
        if len(val) <= 12:
            return "***"
        return val[:6] + "..." + val[-4:]

    return jsonify({
        "anthropic": mask(env.get("ANTHROPIC_API_KEY", "")),
        "gemini":    mask(env.get("GEMINI_API_KEY", "")),
        "openai":    mask(env.get("OPENAI_API_KEY", "")),
        "brave":     mask(env.get("BRAVE_API_KEY", "")),
        "weather":   mask(env.get("OPENWEATHER_API_KEY", "")),
        "server_ip": SERVER_IP,
        "dashboard": f"http://{SERVER_IP}:8080",
    })


@app.route("/api/log")
@login_required
def api_log():
    """Return recent bot log lines from data/bot.log (written by secondbrain service)."""
    log_path = Path("data/bot.log")
    try:
        if not log_path.exists():
            return jsonify({"lines": ["[bot.log not found — bot may not have started yet]"]})
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        lines = [l.rstrip() for l in lines[-60:] if l.strip()]
        return jsonify({"lines": lines})
    except Exception as e:
        return jsonify({"lines": [f"[log read error] {e}"], "error": str(e)})


# ── API routes — EXTERNAL (lite, read-only) ────────────────────────────────────

@app.route("/api/ext/status")
@external_login_required
def api_ext_status():
    """Lite status endpoint for external dashboard — bot counters + weather + match."""
    d = read_metrics()
    return jsonify({
        "status":         d.get("status", "unknown"),
        "last_update":    d.get("last_update", "--"),
        "total_requests": d.get("total_requests", 0),
        "gemini_count":   d.get("gemini_count", 0),
        "claude_count":   d.get("claude_count", 0),
        "weather":        d.get("weather", {}),
        "next_match":     d.get("next_match", {}),
        "api_status":     d.get("api_status", {}),
    })


@app.route("/api/ext/services")
@external_login_required
def api_ext_services():
    """Services status for external dashboard."""
    import subprocess
    SERVICES = [
        ("secondbrain.service",           "Bot"),
        ("secondbrain-dashboard.service", "Dashboard"),
        ("secondbrain-scheduler.service", "Scheduler"),
    ]
    results = []
    for unit, display in SERVICES:
        try:
            out = subprocess.check_output(
                ["systemctl", "show", unit, "--property=ActiveState,SubState"],
                text=True, timeout=3
            )
            props = {}
            for line in out.strip().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v
            active = props.get("ActiveState", "") == "active"
            state  = props.get("SubState", "unknown")
            results.append({"display": display, "active": active, "state": state})
        except Exception:
            results.append({"display": display, "active": False, "state": "error"})
    return jsonify({"services": results})


# ── Health check ───────────────────────────────────────────────────────────────

@app.route("/api/health")
@login_required
def api_health():
    checks = {}
    file_errors = []

    for p in ["data/tasks.json", "data/thoughts.json", "data/reminders.json", "data/metrics.json"]:
        try:
            if Path(p).exists():
                with open(p) as f:
                    json.load(f)
        except Exception as e:
            file_errors.append(f"{p}: {e}")
    checks["data_files"] = len(file_errors) == 0

    disk = psutil.disk_usage("/")
    disk_free_gb = round(disk.free / (1024 ** 3), 1)
    checks["disk_space"] = disk_free_gb > 1.0

    log_path = Path("data/bot.log")
    log_size_kb = round(log_path.stat().st_size / 1024) if log_path.exists() else 0
    checks["log_file"] = log_path.exists()

    status = "ok" if all(checks.values()) else "degraded"
    return jsonify({
        "status": status,
        "checks": checks,
        "disk_free_gb": disk_free_gb,
        "log_size_kb": log_size_kb,
        "file_errors": file_errors,
    })


@app.route("/api/test_weather")
@login_required
def api_test_weather():
    import urllib.request
    import urllib.error
    import json as _json
    key = os.getenv("OPENWEATHER_API_KEY", "")
    if not key:
        return jsonify({"ok": False, "message": "OPENWEATHER_API_KEY not set in .env"})
    city = os.getenv("USER_CITY", "London")
    try:
        url = (f"https://api.openweathermap.org/data/2.5/weather"
               f"?q={city}&appid={key}&units=metric")
        with urllib.request.urlopen(url, timeout=5) as resp:
            d = _json.loads(resp.read())
        if d.get("cod") == 200:
            desc = d["weather"][0]["description"]
            temp = d["main"]["temp"]
            return jsonify({"ok": True, "message": f"Valid · {city}: {temp}°C, {desc}"})
        return jsonify({"ok": False, "message": d.get("message", "Invalid key")})
    except urllib.error.HTTPError as e:
        try:
            msg = _json.loads(e.read()).get("message", str(e))
        except Exception:
            msg = str(e)
        return jsonify({"ok": False, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


# ── Task CRUD ─────────────────────────────────────────────────────────────────

@app.route("/api/update_task", methods=["POST"])
@login_required
def api_update_task():
    from tools.tasks import update_task, add_task
    data = request.json or {}
    if data.get("id") == "new":
        t = add_task(
            title=data.get("title", "").strip(),
            priority=data.get("priority", "medium"),
            due_date=data.get("due_date") or None,
            notes=data.get("notes") or None,
        )
        return jsonify({"success": True, "task": t})
    result = update_task(
        task_id=int(data["id"]),
        title=data.get("title"),
        status=data.get("status"),
        priority=data.get("priority"),
        due_date=data.get("due_date") or None,
        notes=data.get("notes") or None,
    )
    return jsonify(result)


@app.route("/api/delete_task", methods=["POST"])
@login_required
def api_delete_task():
    from tools.tasks import delete_task
    data = request.json or {}
    result = delete_task(int(data["id"]))
    return jsonify(result)


# ── Thought CRUD ──────────────────────────────────────────────────────────────

@app.route("/api/update_thought", methods=["POST"])
@login_required
def api_update_thought():
    from tools.thoughts import _load, _save, add_thought
    data = request.json or {}
    if data.get("id") == "new":
        result = add_thought(
            content=data.get("content", "").strip(),
            tags=[t.strip() for t in data.get("tags", "").split(",") if t.strip()],
        )
        return jsonify({"success": True, "thought": result})
    thoughts_data = _load()
    thoughts_list = thoughts_data if isinstance(thoughts_data, list) else thoughts_data.get("thoughts", [])
    for t in thoughts_list:
        if str(t.get("id")) == str(data.get("id")):
            if "content" in data:
                t["content"] = data["content"]
            if "tags" in data:
                t["tags"] = [x.strip() for x in data["tags"].split(",") if x.strip()]
            break
    _save(thoughts_data)
    return jsonify({"success": True})


@app.route("/api/delete_thought", methods=["POST"])
@login_required
def api_delete_thought():
    from tools.thoughts import _load, _save
    data = request.json or {}
    thoughts_data = _load()
    thoughts_list = thoughts_data if isinstance(thoughts_data, list) else thoughts_data.get("thoughts", [])
    updated = [t for t in thoughts_list if str(t.get("id")) != str(data.get("id"))]
    if isinstance(thoughts_data, list):
        _save(updated)
    else:
        thoughts_data["thoughts"] = updated
        _save(thoughts_data)
    return jsonify({"success": True})


# ── Session info (for external dashboard footer) ───────────────────────────────

@app.route("/api/ext/sessions")
@external_login_required
def api_ext_sessions():
    """How many external sessions are active (for footer display)."""
    _cleanup_expired_sessions()
    return jsonify({
        "active": len(_external_sessions),
        "max": MAX_EXTERNAL_SESSIONS,
    })


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
