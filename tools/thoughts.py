"""
tools/thoughts.py
Handles capturing, tagging, and retrieving random thoughts.
Data is stored locally in data/thoughts.json
"""

import json
import os
from datetime import datetime

DATA_FILE = "data/thoughts.json"


def _load() -> list:
    """Load thoughts from the JSON file. Returns empty list if file doesn't exist."""
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def _save(thoughts: list):
    """Save thoughts list back to the JSON file."""
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(thoughts, f, indent=2)


def add_thought(content: str, tags: list[str] = None) -> dict:
    """
    Save a new thought with optional tags.
    Example: add_thought("I should explore meditation apps", tags=["health", "ideas"])
    """
    thoughts = _load()
    thought = {
        "id": len(thoughts) + 1,
        "content": content,
        "tags": tags or [],
        "created_at": datetime.now().isoformat(),
    }
    thoughts.append(thought)
    _save(thoughts)
    return thought


def list_thoughts(tag: str = None) -> list:
    """
    List all thoughts, optionally filtered by a tag.
    Example: list_thoughts(tag="ideas") returns only thoughts tagged 'ideas'
    """
    thoughts = _load()
    if tag:
        thoughts = [t for t in thoughts if tag.lower() in [x.lower() for x in t.get("tags", [])]]
    return thoughts


def search_thoughts(query: str) -> list:
    """
    Search thoughts by keyword in their content.
    Example: search_thoughts("meditation") returns thoughts mentioning meditation
    """
    thoughts = _load()
    query_lower = query.lower()
    return [t for t in thoughts if query_lower in t["content"].lower()]


def delete_thought(thought_id: int) -> bool:
    """Delete a thought by its ID. Returns True if found and deleted."""
    thoughts = _load()
    original_count = len(thoughts)
    thoughts = [t for t in thoughts if t["id"] != thought_id]
    if len(thoughts) < original_count:
        _save(thoughts)
        return True
    return False
