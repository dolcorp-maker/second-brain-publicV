"""
tools/tasks.py
Handles creating, updating, and managing to-do tasks with priorities.
Data is stored locally in data/tasks.json
"""

import json
import os
from datetime import datetime
from pathlib import Path

DATA_FILE = Path("data/tasks.json")

VALID_PRIORITIES = ["low", "medium", "high"]
VALID_STATUSES   = ["pending", "in_progress", "done"]


def _load() -> list:
    try:
        if not DATA_FILE.exists():
            return []
        with open(DATA_FILE) as f:
            data = json.load(f)
        # Accept both plain list and {"tasks": [...]} dict
        return data if isinstance(data, list) else data.get("tasks", [])
    except Exception:
        return []


def _save(tasks: list):
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(tasks, f, indent=2)
        tmp.rename(DATA_FILE)
    except Exception:
        pass


def _next_id(tasks: list) -> int:
    """Generate next ID safely — not affected by deletions."""
    return max((t.get("id", 0) for t in tasks), default=0) + 1


def add_task(title: str, priority: str = "medium", due_date: str = None, notes: str = None) -> dict:
    """
    Create a new task — something the user needs to DO.
    - title: short action description (e.g. "Call John", "Buy groceries")
    - priority: 'low', 'medium', or 'high'
    - due_date: optional ISO date string (e.g. '2026-03-01') or natural text
    - notes: optional extra context
    """
    tasks = _load()
    task = {
        "id":         _next_id(tasks),
        "title":      title,
        "priority":   priority if priority in VALID_PRIORITIES else "medium",
        "status":     "pending",
        "due_date":   due_date,
        "notes":      notes,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "completed_at": None,
    }
    tasks.append(task)
    _save(tasks)
    return task


def list_tasks(status: str = None, priority: str = None) -> dict:
    """
    List tasks, optionally filtered by status and/or priority.
    Returns a dict with a 'tasks' list and a 'count'.
    """
    tasks = _load()
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    if priority:
        tasks = [t for t in tasks if t.get("priority") == priority]
    priority_order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda t: (priority_order.get(t.get("priority", "medium"), 1), t.get("created_at", "")))
    return {"tasks": tasks, "count": len(tasks)}


def update_task(
    task_id: int,
    title: str = None,
    status: str = None,
    priority: str = None,
    due_date: str = None,
    notes: str = None,
) -> dict:
    """
    Update an existing task. Only provide the fields you want to change.
    Automatically records completed_at when status is set to 'done'.
    """
    tasks = _load()
    for task in tasks:
        if task.get("id") == task_id:
            if title is not None:
                task["title"] = title
            if status and status in VALID_STATUSES:
                task["status"] = status
                if status == "done" and not task.get("completed_at"):
                    task["completed_at"] = datetime.now().isoformat()
                elif status != "done":
                    task["completed_at"] = None
            if priority and priority in VALID_PRIORITIES:
                task["priority"] = priority
            if due_date is not None:
                task["due_date"] = due_date
            if notes is not None:
                task["notes"] = notes
            task["updated_at"] = datetime.now().isoformat()
            _save(tasks)
            return {"success": True, "task": task}
    return {"error": f"Task #{task_id} not found"}


def delete_task(task_id: int) -> dict:
    """Delete a task permanently by ID."""
    tasks = _load()
    original_count = len(tasks)
    tasks = [t for t in tasks if t.get("id") != task_id]
    if len(tasks) < original_count:
        _save(tasks)
        return {"success": True, "message": f"Task #{task_id} deleted"}
    return {"error": f"Task #{task_id} not found"}
