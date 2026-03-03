"""
scheduler.py

Background service that fires reminders at the right time by sending
Telegram messages directly to the user. Runs as a separate systemd service
so it survives bot restarts and crashes independently.

Architecture:
- Reads data/reminders.json every 60 seconds
- When a reminder is due, calls the Telegram Bot API directly (no bot framework)
- Fetches relevant context (weather, pending tasks) to enrich the message
- Completely independent from main.py — two processes, one reminders file

Run it:
    cd ~/second-brain-bot
    source venv/bin/activate
    python scheduler.py
"""

import time
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID  = os.getenv("ALLOWED_USER_ID")
CHECK_INTERVAL   = 60   # seconds between reminder checks
SCHEDULER_LOG    = Path("data/scheduler.log")


# ── Logging ────────────────────────────────────────────────────────────────────
def log(msg: str):
    """Write a timestamped log entry to both stdout and the log file."""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        SCHEDULER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SCHEDULER_LOG, "a") as f:
            f.write(line + "\n")
        # Keep log file from growing indefinitely — trim to last 500 lines
        lines = SCHEDULER_LOG.read_text().splitlines()
        if len(lines) > 500:
            SCHEDULER_LOG.write_text("\n".join(lines[-500:]) + "\n")
    except Exception:
        pass


# ── Telegram sender ────────────────────────────────────────────────────────────
def send_telegram(text: str) -> bool:
    """
    Send a message to the user via Telegram Bot API.
    Uses urllib directly — no telegram library dependency — so the scheduler
    stays lightweight and independent.
    """
    if not TELEGRAM_TOKEN or not ALLOWED_USER_ID:
        log("ERROR: TELEGRAM_BOT_TOKEN or ALLOWED_USER_ID not set in .env")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id":    ALLOWED_USER_ID,
        "text":       text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"ERROR sending Telegram message: {e}")
        return False


# ── Context builder ────────────────────────────────────────────────────────────
def get_context() -> str:
    """
    Build a short context block to append to every reminder.
    Pulls from metrics.json (weather) and tasks.json (pending tasks).
    Gracefully returns empty string if anything fails.
    """
    lines = []

    # ── Weather ───────────────────────────────────────────────────────────────
    try:
        metrics_file = Path("data/metrics.json")
        if metrics_file.exists():
            with open(metrics_file) as f:
                metrics = json.load(f)
            w = metrics.get("weather", {}).get("current", {})
            if w:
                temp = w.get("temperature", "?")
                desc = w.get("description", "")
                lines.append(f"🌤️ <b>Weather:</b> {temp}°C, {desc}")
    except Exception:
        pass

    # ── Pending tasks ─────────────────────────────────────────────────────────
    try:
        tasks_file = Path("data/tasks.json")
        if tasks_file.exists():
            with open(tasks_file) as f:
                tasks_data = json.load(f)
            pending = [
                t for t in tasks_data.get("tasks", [])
                if t.get("status") in ("pending", "in_progress")
            ]
            high = [t for t in pending if t.get("priority") == "high"]
            if high:
                task_list = ", ".join(t["title"] for t in high[:3])
                lines.append(f"🔴 <b>High priority:</b> {task_list}")
            elif pending:
                lines.append(f"✅ <b>Pending tasks:</b> {len(pending)} items")
    except Exception:
        pass

    # ── Upcoming reminders ────────────────────────────────────────────────────
    try:
        from tools.reminders import list_reminders
        result = list_reminders()
        upcoming = result.get("reminders", [])
        # Exclude the one currently firing — show what's next
        if len(upcoming) > 1:
            nxt = upcoming[1]
            lines.append(f"⏰ <b>Next reminder:</b> {nxt.get('time_until', '')} — {nxt['text']}")
    except Exception:
        pass

    if not lines:
        return ""

    return "\n\n<i>— Context —</i>\n" + "\n".join(lines)


# ── Message formatter ──────────────────────────────────────────────────────────
def build_message(reminder: dict) -> str:
    """
    Build the full Telegram message for a fired reminder.
    Includes the reminder text + relevant context block.
    """
    now_str = datetime.now().strftime("%H:%M")
    text = reminder.get("text", "Reminder")

    msg = f"⏰ <b>REMINDER</b> · {now_str}\n\n{text}"
    msg += get_context()
    return msg


# ── Main loop ──────────────────────────────────────────────────────────────────
def run():
    log("Scheduler started — checking reminders every 60 seconds")

    while True:
        try:
            from tools.reminders import get_due_reminders
            due = get_due_reminders()

            for reminder in due:
                log(f"Firing reminder #{reminder['id']}: {reminder['text']}")
                message = build_message(reminder)
                success = send_telegram(message)
                if success:
                    log(f"Reminder #{reminder['id']} sent successfully")
                else:
                    log(f"Reminder #{reminder['id']} FAILED to send")

        except Exception as e:
            log(f"ERROR in scheduler loop: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
