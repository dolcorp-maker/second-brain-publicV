"""
tools/notes.py
Important notes vault — categorized storage for passwords, keys, API credentials,
random notes, and headlines. Data stored locally in data/notes.json.

Categories: passwords | keys | api | random | headlines
"""

import json
import os
from datetime import datetime

DATA_FILE = "data/notes.json"

VALID_CATEGORIES = {"passwords", "keys", "api", "random", "headlines"}


def _load() -> list:
    try:
        if not os.path.exists(DATA_FILE):
            return []
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(notes: list):
    os.makedirs("data", exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(notes, f, indent=2)
    os.replace(tmp, DATA_FILE)


def _next_id(notes: list) -> int:
    return max((n["id"] for n in notes), default=0) + 1


def save_note(title: str, content: str, category: str) -> dict:
    """
    Save an important note under a category.
    Categories: passwords, keys, api, random, headlines.
    Example: save_note("GitHub token", "ghp_abc123...", "keys")
    """
    try:
        category = category.lower().strip()
        if category not in VALID_CATEGORIES:
            return {"error": f"Invalid category '{category}'. Use: {', '.join(sorted(VALID_CATEGORIES))}"}
        notes = _load()
        note = {
            "id": _next_id(notes),
            "title": title,
            "content": content,
            "category": category,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        notes.append(note)
        _save(notes)
        return note
    except Exception as e:
        return {"error": f"Failed to save note: {e}"}


def get_notes(category: str = None) -> list:
    """
    Retrieve all notes, optionally filtered by category.
    Categories: passwords, keys, api, random, headlines.
    Example: get_notes(category="api") returns all API credential notes.
    """
    try:
        notes = _load()
        if category:
            category = category.lower().strip()
            notes = [n for n in notes if n.get("category") == category]
        return notes
    except Exception as e:
        return {"error": f"Failed to retrieve notes: {e}"}


def search_notes(query: str) -> list:
    """
    Search notes by keyword across title and content.
    Example: search_notes("github") finds notes mentioning GitHub.
    """
    try:
        notes = _load()
        q = query.lower()
        return [
            n for n in notes
            if q in n.get("title", "").lower() or q in n.get("content", "").lower()
        ]
    except Exception as e:
        return {"error": f"Failed to search notes: {e}"}


def update_note(note_id: int, title: str = None, content: str = None, category: str = None) -> dict:
    """
    Update an existing note by ID. Only provided fields are changed.
    Example: update_note(3, content="new_password_value")
    """
    try:
        notes = _load()
        for note in notes:
            if note["id"] == note_id:
                if title is not None:
                    note["title"] = title
                if content is not None:
                    note["content"] = content
                if category is not None:
                    category = category.lower().strip()
                    if category not in VALID_CATEGORIES:
                        return {"error": f"Invalid category '{category}'. Use: {', '.join(sorted(VALID_CATEGORIES))}"}
                    note["category"] = category
                note["updated_at"] = datetime.now().isoformat()
                _save(notes)
                return note
        return {"error": f"Note with id={note_id} not found."}
    except Exception as e:
        return {"error": f"Failed to update note: {e}"}


def delete_note(note_id: int) -> dict:
    """
    Delete a note by its ID. Returns confirmation or error.
    Example: delete_note(5)
    """
    try:
        notes = _load()
        original = len(notes)
        notes = [n for n in notes if n["id"] != note_id]
        if len(notes) < original:
            _save(notes)
            return {"deleted": True, "id": note_id}
        return {"error": f"Note with id={note_id} not found."}
    except Exception as e:
        return {"error": f"Failed to delete note: {e}"}
