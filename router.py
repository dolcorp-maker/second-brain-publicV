"""
router.py

Classifies messages as 'simple' (Gemini, free) or 'complex' (Claude, paid).

Key fix: keyword matching now uses whole-word boundaries via regex,
so 'hi' won't match inside 'machines', 'this' won't match 'thinking', etc.

Google Calendar create/add operations are forced to Claude — Gemini
consistently picks the local add_event tool instead of add_calendar_event.
"""

import re
import logging

logger = logging.getLogger(__name__)


def _matches(keyword: str, text: str) -> bool:
    """
    Check if keyword appears in text as a whole phrase, not a substring.
    'hi' will NOT match 'machines' or 'this'.
    """
    escaped = re.escape(keyword)
    pattern = r'\b' + escaped + r'\b'
    return bool(re.search(pattern, text))


# ── Force Claude for these — Gemini makes wrong tool choices ──────────────────
FORCE_CLAUDE = [
    # Calendar — all operations go through Google Calendar now
    "google calendar",
    "add to my calendar",
    "add to calendar",
    "create.*calendar",
    "put.*calendar",
    "schedule.*meeting",
    "schedule.*call",
    "schedule.*appointment",
    "add event", "new event", "create event",
    "show schedule", "my schedule", "today's schedule", "list events",
    "what's on", "whats on",
    # Email / Tasks (Google)
    "my emails",
    "unread emails",
    "check.*email",
    "google tasks",
    # GIF / video — broad coverage so any gif/video request hits Claude
    "make a gif",
    "create a gif",
    "generate a gif",
    "make gif",
    "gif of",
    "prepare.*gif",
    "prepare.*video",
    "want.*gif",
    "give me.*gif",
    "get me.*gif",
    # Single A/B/1/2 reply — routes follow-up GIF option selection back to Claude
    r"^\s*[ab]\s*$",
    r"^\s*[12]\s*$",
    # Notes vault — Gemini reliably fails to call get_notes/search_notes
    "my notes",
    "get notes",
    "show notes",
    "list notes",
    "my passwords",
    "show passwords",
    "list passwords",
    "get password",
    "my keys",
    "show keys",
    "list keys",
    "my api keys",
    "search notes",
    "find note",
    # Reminders — Gemini returns tool=none for set_reminder; Claude handles reliably
    "remind me",
    "set a reminder",
    "set reminder",
    "reminder for",
    "create.*reminder",
    "schedule.*reminder",
    # Navigation / Maps — Claude extracts destination, origin, times (Hebrew + English)
    "trip to",
    "plan a trip",
    "plan trip",
    "planning a trip",
    "driving to",
    "navigate to",
    "directions to",
    "i need to be in",
    "i need to be at",
    "i should be in",
    "i should be at",
    "i have to be in",
    "i have to be at",
    "need to arrive",
    "leave from",
    # Hebrew navigation phrases
    "נסיעה ל",
    "טיול ל",
    "לנסוע ל",
    "מתכנן לנסוע",
    "לתכנן נסיעה",
    "ניווט ל",
    "צריך להיות ב",
    "חייב להיות ב",
    "להגיע ל",
    "דרך ל",
]


COMPLEX_KEYWORDS = [
    "analyze", "analyse", "summary", "summarize", "summarise",
    "pattern", "patterns", "insight", "insights",
    "procrastinat", "prioritize", "prioritise",
    "plan my", "help me decide", "what should i",
    "review my week", "review my month",
    "compare", "suggest", "recommend", "advice",
    "why", "how should", "what do you think",
    "reflect", "reflection",
]

SIMPLE_KEYWORDS = [
    # Tasks
    "add task", "create task", "new task", "add a task",
    "list tasks", "show tasks", "my tasks", "pending tasks",
    "mark task", "update task", "complete task", "done task",
    "delete task", "remove task",
    # Thoughts
    "note this", "save this", "remember this", "add thought",
    "show thoughts", "list thoughts", "my thoughts", "search thoughts",
    "random thought", "note that", "write that down", "remember that",
    "had a thought", "new thought", "quick thought",
    # Weather
    "weather", "temperature", "forecast", "rain", "sunny", "cloudy",
    "what's the weather", "will it rain",
    # Search
    "search for", "look up", "find info", "what is", "who is",
    "latest news", "current price", "how much is",
    # Greetings — whole word only, no longer matches 'machines'
    "hi", "hello", "hey", "help", "what can you do",
    # Reminders — list/cancel are safe for Gemini; setting is FORCE_CLAUDE above
    "list reminders", "show reminders", "cancel reminder", "delete reminder",
    # Maccabi
    "maccabi", "next match", "next game",
    # Notes vault — write/modify ops stay simple; reads/searches are FORCE_CLAUDE above
    "save note", "store note", "add note", "new note",
    "delete note", "update note", "edit note",
]


def classify_message(message: str) -> str:
    """
    Classify a message as 'simple' (Gemini) or 'complex' (Claude).

    Priority:
    1. FORCE_CLAUDE  — Google services needing precise tool selection
    2. COMPLEX       — analytical / reasoning tasks
    3. SIMPLE        — straightforward actions
    4. Length        — long messages default to Claude
    """
    msg = message.lower().strip()

    # 0. Early GIF/video check on first 10 words — catches "prepare a gif...", "want a video..."
    #    before the word-count fallback fires.
    first_words = " ".join(msg.split()[:10])
    if (re.search(r'\b(gif|video|animation|animate)\b', first_words)
            and re.search(r'\b(make|create|generate|prepare|give|want|need|get|build)\b', first_words)):
        logger.info("[ROUTE] claude-forced (gif/video in first 10 words)")
        return "complex"

    # 1. Force Claude for Google Calendar / Gmail
    for phrase in FORCE_CLAUDE:
        if re.search(phrase, msg):
            logger.info(f"[ROUTE] claude-forced match='{phrase}'")
            return "complex"

    # 2. Complex keywords
    for keyword in COMPLEX_KEYWORDS:
        if _matches(keyword, msg):
            logger.info(f"[ROUTE] claude-complex match='{keyword}'")
            return "complex"

    # 3. Simple keywords
    for keyword in SIMPLE_KEYWORDS:
        if _matches(keyword, msg):
            logger.info(f"[ROUTE] gemini-simple match='{keyword}'")
            return "simple"

    # 4. Length fallback
    word_count = len(msg.split())
    if word_count > 30:
        logger.info(f"[ROUTE] claude-long words={word_count}")
        return "complex"

    logger.info("[ROUTE] gemini-default")
    return "simple"
