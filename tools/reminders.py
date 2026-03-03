"""
tools/reminders.py

Reminder storage and management.
Reminders are stored in data/reminders.json as a list of reminder objects.

Each reminder:
{
    "id":         1,
    "text":       "Call mom",
    "due":        "2026-03-01T18:00:00",   # ISO datetime
    "recurrence": null,                     # null | "daily" | "weekly"
    "fired":      false,
    "created":    "2026-02-24T10:00:00"
}

The scheduler reads this file every minute and fires due reminders.
The bot writes to this file when the user creates a reminder.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

REMINDERS_FILE = Path("data/reminders.json")


def _load() -> dict:
    try:
        if REMINDERS_FILE.exists():
            with open(REMINDERS_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"reminders": [], "next_id": 1}


def _save(data: dict):
    try:
        REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = REMINDERS_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, default=str, indent=2)
        tmp.rename(REMINDERS_FILE)
    except Exception:
        pass


def add_reminder(text: str, due: str, recurrence: str = None) -> dict:
    """
    Add a new reminder.

    text:       what to remind the user about
    due:        ISO datetime string when the reminder should fire
    recurrence: None, 'daily', or 'weekly'
    """
    try:
        data = _load()
        reminder = {
            "id":         data["next_id"],
            "text":       text,
            "due":        due,
            "recurrence": recurrence,
            "fired":      False,
            "created":    datetime.now().isoformat(),
        }
        data["reminders"].append(reminder)
        data["next_id"] += 1
        _save(data)

        # Format a nice due time for the confirmation message
        try:
            dt = datetime.fromisoformat(due)
            due_display = dt.strftime("%A, %d %B at %H:%M")
        except Exception:
            due_display = due

        return {
            "success": True,
            "id": reminder["id"],
            "message": f"Reminder set for {due_display}",
            "text": text,
            "due": due,
        }
    except Exception as e:
        return {"error": str(e)}


def list_reminders(include_fired: bool = False) -> dict:
    """List all pending (or all) reminders."""
    try:
        data = _load()
        reminders = data.get("reminders", [])

        if not include_fired:
            reminders = [r for r in reminders if not r.get("fired")]

        # Sort by due time
        reminders = sorted(reminders, key=lambda r: r.get("due", ""))

        # Add human-readable due time
        formatted = []
        for r in reminders:
            try:
                dt = datetime.fromisoformat(r["due"])
                r = dict(r)  # copy
                r["due_display"] = dt.strftime("%A, %d %B at %H:%M")

                # Calculate time until
                delta = dt - datetime.now()
                if delta.total_seconds() < 0:
                    r["time_until"] = "overdue"
                elif delta.total_seconds() < 3600:
                    mins = int(delta.total_seconds() / 60)
                    r["time_until"] = f"in {mins} minutes"
                elif delta.total_seconds() < 86400:
                    hours = int(delta.total_seconds() / 3600)
                    r["time_until"] = f"in {hours} hours"
                else:
                    days = int(delta.total_seconds() / 86400)
                    r["time_until"] = f"in {days} days"
            except Exception:
                pass
            formatted.append(r)

        return {
            "reminders": formatted,
            "count": len(formatted),
        }
    except Exception as e:
        return {"error": str(e)}


def cancel_reminder(reminder_id: int) -> dict:
    """Cancel a reminder by ID."""
    try:
        data = _load()
        reminders = data.get("reminders", [])
        original_count = len(reminders)
        data["reminders"] = [r for r in reminders if r.get("id") != reminder_id]

        if len(data["reminders"]) == original_count:
            return {"error": f"Reminder #{reminder_id} not found"}

        _save(data)
        return {"success": True, "message": f"Reminder #{reminder_id} cancelled"}
    except Exception as e:
        return {"error": str(e)}


def get_due_reminders() -> list:
    """
    Called by the scheduler every minute.
    Returns all reminders that are due now (within the last minute).
    Marks them as fired (or reschedules recurring ones).
    """
    try:
        data = _load()
        now = datetime.now()
        due = []

        for r in data["reminders"]:
            if r.get("fired"):
                continue
            try:
                due_dt = datetime.fromisoformat(r["due"])
            except Exception:
                continue

            # Fire if due time is within the past 90 seconds
            # (90s window accounts for scheduler timing imprecision)
            delta = (now - due_dt).total_seconds()
            if 0 <= delta <= 90:
                due.append(r)

                if r.get("recurrence") == "daily":
                    r["due"] = (due_dt + timedelta(days=1)).isoformat()
                elif r.get("recurrence") == "weekly":
                    r["due"] = (due_dt + timedelta(weeks=1)).isoformat()
                else:
                    r["fired"] = True

        if due:
            _save(data)

        return due
    except Exception:
        return []


def parse_reminder_due(when: str) -> str:
    """
    Convert a natural language time expression into an ISO datetime string.
    This is called by the agent tool before saving a reminder.

    Examples:
        "tomorrow at 6pm"    → "2026-03-01T18:00:00"
        "in 2 hours"         → "2026-02-24T14:30:00"
        "in 30 minutes"      → "2026-02-24T12:30:00"
        "Friday at 9am"      → "2026-02-28T09:00:00"
        "2026-03-05 at 15:00" → "2026-03-05T15:00:00"
    """
    from tools.google_services import _parse_date, _parse_time

    when = when.strip().lower()
    now = datetime.now()

    # ── "in X minutes/hours" ──────────────────────────────────────────────────
    import re
    m = re.match(r'in\s+(\d+)\s+(minute|minutes|min|hour|hours|hr|day|days)', when)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if 'minute' in unit or unit == 'min':
            return (now + timedelta(minutes=amount)).strftime("%Y-%m-%dT%H:%M:%S")
        elif 'hour' in unit or unit == 'hr':
            return (now + timedelta(hours=amount)).strftime("%Y-%m-%dT%H:%M:%S")
        elif 'day' in unit:
            return (now + timedelta(days=amount)).replace(
                hour=9, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")

    # ── "tomorrow at Xpm", "friday at 9am", etc ──────────────────────────────
    # Split on " at " to separate date and time parts
    if ' at ' in when:
        date_part, time_part = when.split(' at ', 1)
    else:
        date_part = when
        time_part = "09:00"

    base_date = _parse_date(date_part.strip())
    if not base_date:
        # Default to tomorrow at 9am if we can't parse
        base_date = now + timedelta(days=1)
        base_date = base_date.replace(hour=9, minute=0, second=0, microsecond=0)

    result_dt = _parse_time(time_part.strip(), base_date)
    return result_dt.strftime("%Y-%m-%dT%H:%M:%S")
