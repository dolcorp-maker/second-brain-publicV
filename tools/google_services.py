"""
sed -i 's/from googleapiclient.discovery import build/import logging\nlogging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)\nfrom googleapiclient.discovery import build/' ~/second-brain-bot/tools/google_services.py
tools/google_services.py

Google Calendar, Gmail, and Tasks integration using the Google API.

Authentication flow:
- First run: opens browser for OAuth authorization, saves token.json
- Subsequent runs: loads token.json automatically, refreshes if expired
- token.json is sensitive — it's in .gitignore and never transferred accidentally

Scopes requested:
- Calendar: read and write events
- Gmail: read and send emails
- Tasks: read and write tasks
"""
import logging
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_tz = ZoneInfo(os.getenv("TIMEZONE", "UTC"))


def _tz_name() -> str:
    return os.getenv("TIMEZONE", "UTC")


def _tz_offset() -> str:
    """Return UTC offset string like '+0300' for use in ISO timestamps."""
    return datetime.now(_tz).strftime("%z")
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── Scopes ─────────────────────────────────────────────────────────────────────
# These define exactly what permissions we're requesting from Google.
# If you change scopes after already having a token.json, delete token.json
# and re-authorize so the new permissions are included.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/tasks",
]

# ── File paths ─────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


def get_credentials() -> Credentials:
    """
    Load or refresh Google OAuth credentials.

    Flow:
    1. If token.json exists and is valid → use it directly
    2. If token.json exists but is expired → refresh it automatically
    3. If no token.json → open browser for one-time authorization

    After step 3, token.json is saved so you never need to authorize again
    unless you revoke access in your Google account settings.
    """
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but we have a refresh token — get a new one silently
            creds.refresh(Request())
        else:
            # No token yet — run the authorization flow
            # This opens a browser window for you to sign in and grant permission
            if not CREDENTIALS_FILE.exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


# ── CALENDAR ───────────────────────────────────────────────────────────────────

def get_calendar_events(days_ahead: int = 7, max_results: int = 10) -> dict:
    """
    Fetch upcoming events from Google Calendar.

    days_ahead: how many days into the future to look (default 7)
    max_results: maximum number of events to return (default 10)

    Returns a list of events with title, date, time, location, and description.
    """
    try:
        creds = get_credentials()
        if not creds:
            return {"error": "Google credentials not found. Run python authorize_google.py first."}

        service = build("calendar", "v3", credentials=creds)

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])

        if not events:
            return {
                "events": [],
                "message": f"No events in the next {days_ahead} days.",
            }

        formatted = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            end = event["end"].get("dateTime", event["end"].get("date", ""))

            # Parse the datetime for nicer formatting
            try:
                if "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    date_str = dt.strftime("%A, %d %B")
                    time_str = dt.strftime("%H:%M")
                else:
                    dt = datetime.fromisoformat(start)
                    date_str = dt.strftime("%A, %d %B")
                    time_str = "All day"
            except Exception:
                date_str = start
                time_str = ""

            formatted.append({
                "title": event.get("summary", "Untitled"),
                "date": date_str,
                "time": time_str,
                "location": event.get("location", ""),
                "description": event.get("description", ""),
                "id": event.get("id", ""),
            })

        return {
            "events": formatted,
            "count": len(formatted),
            "period": f"Next {days_ahead} days",
        }

    except HttpError as e:
        return {"error": f"Google Calendar API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Calendar fetch failed: {str(e)}"}


def add_calendar_event(
    title: str,
    date: str,
    time: str = "",
    duration_minutes: int = 60,
    location: str = "",
    description: str = "",
) -> dict:
    """
    Add a new event to Google Calendar.

    date: in any reasonable format like "tomorrow", "March 5", "2026-03-05"
    time: like "14:00", "2pm", "14:30" — leave empty for all-day event
    duration_minutes: how long the event is (default 60 minutes)
    """
    try:
        creds = get_credentials()
        if not creds:
            return {"error": "Google credentials not found. Run python authorize_google.py first."}

        service = build("calendar", "v3", credentials=creds)

        # Parse the date/time — we let the AI pass natural language dates
        # and convert them here to ISO format that Google expects
        event_date = _parse_date(date)
        if not event_date:
            return {"error": f"Could not parse date: {date}"}

        if time:
            # Timed event
            start_time = _parse_time(time, event_date)
            end_time = start_time + timedelta(minutes=duration_minutes)
            event_body = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": _tz_name(),
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": _tz_name(),
                },
            }
        else:
            # All-day event
            event_body = {
                "summary": title,
                "location": location,
                "description": description,
                "start": {"date": event_date.strftime("%Y-%m-%d")},
                "end": {"date": event_date.strftime("%Y-%m-%d")},
            }

        created = service.events().insert(
            calendarId="primary",
            body=event_body,
        ).execute()

        return {
            "success": True,
            "message": f"Event '{title}' added to Google Calendar",
            "event_id": created.get("id"),
            "link": created.get("htmlLink"),
        }

    except HttpError as e:
        return {"error": f"Google Calendar API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to create event: {str(e)}"}


def get_todays_google_events() -> dict:
    """Get all Google Calendar events for today specifically."""
    try:
        creds = get_credentials()
        if not creds:
            return {"error": "Google credentials not found."}

        service = build("calendar", "v3", credentials=creds)

        # Today's boundaries in UTC
        now = datetime.now()
        start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0)
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59)

        result = service.events().list(
            calendarId="primary",
            timeMin=start_of_day.isoformat() + _tz_offset(),
            timeMax=end_of_day.isoformat() + _tz_offset(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])

        if not events:
            return {"events": [], "message": "Nothing scheduled for today."}

        formatted = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            try:
                if "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = "All day"
            except Exception:
                time_str = start

            formatted.append({
                "title": event.get("summary", "Untitled"),
                "time": time_str,
                "location": event.get("location", ""),
            })

        return {
            "events": formatted,
            "count": len(formatted),
            "date": now.strftime("%A, %d %B %Y"),
        }

    except Exception as e:
        return {"error": f"Failed to fetch today's events: {str(e)}"}


# ── GMAIL ──────────────────────────────────────────────────────────────────────

def get_unread_emails(max_results: int = 5) -> dict:
    """
    Fetch unread emails from Gmail inbox.
    Returns sender, subject, date, and a short snippet for each email.
    """
    try:
        creds = get_credentials()
        if not creds:
            return {"error": "Google credentials not found."}

        service = build("gmail", "v1", credentials=creds)

        # Search for unread emails in inbox
        result = service.users().messages().list(
            userId="me",
            q="is:unread in:inbox",
            maxResults=max_results,
        ).execute()

        messages = result.get("messages", [])
        if not messages:
            return {"emails": [], "message": "No unread emails."}

        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers = {
                h["name"]: h["value"]
                for h in detail.get("payload", {}).get("headers", [])
            }

            emails.append({
                "from": headers.get("From", "Unknown"),
                "subject": headers.get("Subject", "No subject"),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
                "id": msg["id"],
            })

        return {
            "emails": emails,
            "count": len(emails),
            "unread_total": result.get("resultSizeEstimate", len(emails)),
        }

    except HttpError as e:
        return {"error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to fetch emails: {str(e)}"}


# ── GOOGLE TASKS ───────────────────────────────────────────────────────────────

def get_google_tasks(max_results: int = 10) -> dict:
    """Fetch incomplete tasks from Google Tasks."""
    try:
        creds = get_credentials()
        if not creds:
            return {"error": "Google credentials not found."}

        service = build("tasks", "v1", credentials=creds)

        # Get the default task list
        tasklists = service.tasklists().list().execute()
        lists = tasklists.get("items", [])
        if not lists:
            return {"tasks": [], "message": "No task lists found."}

        # Use the first (default) task list
        task_list_id = lists[0]["id"]

        result = service.tasks().list(
            tasklist=task_list_id,
            maxResults=max_results,
            showCompleted=False,
            showHidden=False,
        ).execute()

        tasks = result.get("items", [])
        if not tasks:
            return {"tasks": [], "message": "No pending Google Tasks."}

        formatted = []
        for task in tasks:
            due = task.get("due", "")
            if due:
                try:
                    due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    due = due_dt.strftime("%d %B %Y")
                except Exception:
                    pass

            formatted.append({
                "title": task.get("title", "Untitled"),
                "due": due,
                "notes": task.get("notes", ""),
                "id": task.get("id", ""),
            })

        return {
            "tasks": formatted,
            "count": len(formatted),
        }

    except HttpError as e:
        return {"error": f"Google Tasks API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to fetch tasks: {str(e)}"}


def add_google_task(title: str, due_date: str = "", notes: str = "") -> dict:
    """Add a new task to Google Tasks."""
    try:
        creds = get_credentials()
        if not creds:
            return {"error": "Google credentials not found."}

        service = build("tasks", "v1", credentials=creds)

        tasklists = service.tasklists().list().execute()
        lists = tasklists.get("items", [])
        if not lists:
            return {"error": "No task lists found."}

        task_list_id = lists[0]["id"]

        task_body = {"title": title, "notes": notes}

        if due_date:
            parsed = _parse_date(due_date)
            if parsed:
                task_body["due"] = parsed.strftime("%Y-%m-%dT00:00:00.000Z")

        created = service.tasks().insert(
            tasklist=task_list_id,
            body=task_body,
        ).execute()

        return {
            "success": True,
            "message": f"Task '{title}' added to Google Tasks",
            "task_id": created.get("id"),
        }

    except Exception as e:
        return {"error": f"Failed to create Google Task: {str(e)}"}


# ── Date/time parsing helpers ──────────────────────────────────────────────────

def _parse_date(date_str: str) -> datetime | None:
    """
    Parse a natural language or formatted date string into a datetime object.
    Handles: 'today', 'tomorrow', 'Monday', 'March 5', '2026-03-05', etc.
    """
    date_str = date_str.strip().lower()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if date_str in ("today", "now"):
        return today
    if date_str == "tomorrow":
        return today + timedelta(days=1)
    if date_str == "yesterday":
        return today - timedelta(days=1)

    # Day names
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if date_str in days:
        target = days.index(date_str)
        current = today.weekday()
        delta = (target - current) % 7
        if delta == 0:
            delta = 7  # Next week if today
        return today + timedelta(days=delta)

    # Try standard date formats
    formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
        "%d %B %Y", "%B %d %Y", "%B %d, %Y",
        "%d %B", "%B %d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # If no year specified, assume current year (or next if in the past)
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
                if parsed < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed
        except ValueError:
            continue

    return None


def _parse_time(time_str: str, base_date: datetime) -> datetime:
    """Parse a time string like '14:00', '2pm', '14:30' into a datetime."""
    time_str = time_str.strip().lower()

    # Handle am/pm format
    for fmt in ["%I:%M%p", "%I%p", "%H:%M", "%H"]:
        try:
            parsed = datetime.strptime(time_str, fmt)
            return base_date.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            continue

    # Default to noon if we can't parse
    return base_date.replace(hour=12, minute=0, second=0, microsecond=0)
