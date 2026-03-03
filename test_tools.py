"""
test_tools.py
Run this to test all tools locally without any API calls.
Usage: python test_tools.py
"""

from tools import thoughts, tasks, events

def separator(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)

def test_thoughts():
    separator("THOUGHTS")

    # Add thoughts
    t1 = thoughts.add_thought("Explore a new monitoring tool", tags=["work", "ideas"])
    t2 = thoughts.add_thought("Read about meditation apps", tags=["health"])
    t3 = thoughts.add_thought("Rethink morning routine", tags=["health", "personal"])
    print(f"✅ Added 3 thoughts")

    # List all
    all_thoughts = thoughts.list_thoughts()
    print(f"📋 All thoughts ({len(all_thoughts)} total):")
    for t in all_thoughts:
        print(f"   [{t['id']}] {t['content']} — tags: {t['tags']}")

    # Filter by tag
    health = thoughts.list_thoughts(tag="health")
    print(f"\n🏷  Filtered by 'health' ({len(health)} results):")
    for t in health:
        print(f"   [{t['id']}] {t['content']}")

    # Search
    results = thoughts.search_thoughts("monitoring")
    print(f"\n🔍 Search 'monitoring' ({len(results)} results):")
    for t in results:
        print(f"   [{t['id']}] {t['content']}")

    # Delete
    deleted = thoughts.delete_thought(t2["id"])
    print(f"\n🗑  Deleted thought #{t2['id']}: {deleted}")
    print(f"📋 Remaining thoughts: {len(thoughts.list_thoughts())}")


def test_tasks():
    separator("TASKS")

    # Add tasks
    t1 = tasks.add_task("Review server logs", priority="high", due_date="tomorrow")
    t2 = tasks.add_task("Update firewall rules", priority="medium", due_date="Friday")
    t3 = tasks.add_task("Write Q4 report", priority="low")
    print(f"✅ Added 3 tasks")

    # List all
    all_tasks = tasks.list_tasks()
    print(f"📋 All tasks ({len(all_tasks)} total):")
    for t in all_tasks:
        print(f"   [{t['id']}] [{t['priority'].upper()}] {t['title']} — {t['status']} — due: {t['due_date']}")

    # Filter by priority
    high = tasks.list_tasks(priority="high")
    print(f"\n🔴 High priority tasks ({len(high)}):")
    for t in high:
        print(f"   [{t['id']}] {t['title']}")

    # Update status
    updated = tasks.update_task(t1["id"], status="in_progress")
    print(f"\n✏️  Updated task #{t1['id']} → status: {updated['status']}")

    # Filter pending
    pending = tasks.list_tasks(status="pending")
    print(f"⏳ Pending tasks: {len(pending)}")

    # Mark done
    tasks.update_task(t1["id"], status="done")
    done = tasks.list_tasks(status="done")
    print(f"✅ Done tasks: {len(done)}")


def test_events():
    separator("CALENDAR / EVENTS")

    # Add events
    e1 = events.add_event("Team Standup", date="2026-02-25", time="10:00", duration_minutes=30)
    e2 = events.add_event("Server Maintenance", date="2026-02-26", time="22:00", notes="Backup first!")
    e3 = events.add_event("1:1 with Manager", date=str(__import__('datetime').date.today()), time="14:00")
    print(f"✅ Added 3 events")

    # List all
    all_events = events.list_events()
    print(f"📅 All events ({len(all_events)} total):")
    for e in all_events:
        print(f"   [{e['id']}] {e['title']} — {e['date']} at {e['time']} ({e['duration_minutes']}min)")

    # Today's schedule
    today = events.get_todays_schedule()
    print(f"\n📆 Today's schedule ({len(today)} events):")
    for e in today:
        print(f"   {e['time']} — {e['title']}")

    # Filter by date
    filtered = events.list_events(date="2026-02-25")
    print(f"\n🔍 Events on 2026-02-25: {len(filtered)}")

    # Delete
    deleted = events.delete_event(e2["id"])
    print(f"\n🗑  Deleted event #{e2['id']}: {deleted}")
    print(f"📅 Remaining events: {len(events.list_events())}")


if __name__ == "__main__":
    print("\n🧪 Running Second Brain Tool Tests (no API calls)\n")
    test_thoughts()
    test_tasks()
    test_events()
    print("\n\n✅ All tests complete! Check your data/ folder to see the saved JSON files.")
