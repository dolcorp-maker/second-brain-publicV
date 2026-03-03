"""
clear_data.py
Clears all stored data (thoughts, tasks, events).
Run this after testing or when you want a fresh start.
Usage: python clear_data.py
"""

import json
import os

FILES = [
    "data/thoughts.json",
    "data/tasks.json",
    "data/events.json",
]

print("\n🗑  Clearing all data...\n")

for filepath in FILES:
    if os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump([], f)
        print(f"✅ Cleared {filepath}")
    else:
        print(f"⚠️  {filepath} not found — skipping")

print("\n✨ Done! All data files are empty and ready.\n")
