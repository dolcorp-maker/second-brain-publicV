"""
agent.py
Routes messages to Gemini (simple/free) or Claude (complex/paid).
Now also records full prompt/response/tool-chain + timing to metrics.
"""

import json
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

import os
import anthropic
from google import genai
from google.genai import types
from tools import thoughts, tasks, notes
from tools.search import get_weather, web_search
from tools.maccabi import get_maccabi_matches
from tools.metrics import record_message, update_weather, update_next_match
from tools.google_services import (
    get_calendar_events, add_calendar_event, get_todays_google_events,
    get_unread_emails, get_google_tasks, add_google_task,
)
from tools.reminders import add_reminder, list_reminders, cancel_reminder, parse_reminder_due
from tools.video_generator import generate_video_gif
from tools.maps import build_maps_link
from tools.image_analyzer import analyze_photo
from tools.image_generator import generate_image
from router import classify_message

claude_client = anthropic.Anthropic()
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# GIF path produced by the last generate_video_gif call.
# Gemini tool results never enter conversation_history, so main.py uses this
# as a fallback to retrieve the path after Gemini generates a GIF.
_pending_gif_path: str | None = None

# Image bytes produced by the last generate_image call.
# Stored here so main.py can send them as a Telegram photo.
_pending_image_bytes: bytes | None = None


def consume_pending_gif_path() -> str | None:
    """Return and clear the pending GIF path (thread-safe enough for single-user bot)."""
    global _pending_gif_path
    path, _pending_gif_path = _pending_gif_path, None
    return path


def consume_pending_image_bytes() -> bytes | None:
    """Return and clear the pending image bytes."""
    global _pending_image_bytes
    data, _pending_image_bytes = _pending_image_bytes, None
    return data

SYSTEM_PROMPT = """
You are a personal second-brain assistant, available 24/7 via Telegram.
Your job is to help the user organize their thoughts, manage tasks, schedule events,
and answer questions about the world using web search and weather tools.

Personality:
- Friendly, concise, and proactive
- You speak like a smart personal assistant — not a robot
- Keep replies short unless the user asks for detail
- Use emojis sparingly for warmth (✅ 📝 📅 💡 🌤️ 🔍)

Capabilities:
- Capture and search random thoughts and ideas
- Create, update, and track to-do tasks with priorities
- Schedule events and manage your Google Calendar
- Read unread Gmail emails
- Read and create Google Tasks
- Get real-time weather for any city
- Search the web for current information, news, and facts
- Get Maccabi Haifa FC upcoming matches and recent results
- Store and retrieve important notes by category: passwords, keys, api, random, headlines
- Plan driving trips and get Google Maps navigation links (Hebrew and English)

When the user asks about their schedule, calendar, or events — use get_todays_google_events
or get_calendar_events to check their Google Calendar.
When the user wants to add an event, use add_calendar_event to add it to Google Calendar.
NEVER ask the user for the current date — always infer it from the current date provided below.
The user is based in Tel Aviv, Israel (timezone: Asia/Jerusalem).
Default to Tel Aviv for weather queries unless another city is specified.

When the user asks to make a gif or video:
- SHORT request (fewer than 30 words): propose exactly 2 creative directions as short bullet
  points labeled A and B, then wait. Call generate_video_gif only after they reply with A or B.
- DETAILED request (30 words or more): call generate_video_gif immediately using their full
  description. Do not propose options — start generating right away.
"""

CLAUDE_TOOLS = [
    {"name": "add_thought", "description": "Save a fact, idea, insight, or note — anything the user wants to REMEMBER but not necessarily DO. Use for 'note this', 'remember that', 'I was thinking...', facts, observations. Do NOT use if there's a clear action to take — use add_task for that.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["content"]}},
    {"name": "list_thoughts", "description": "List all saved thoughts, optionally filtered by tag.", "input_schema": {"type": "object", "properties": {"tag": {"type": "string"}}}},
    {"name": "search_thoughts", "description": "Search saved thoughts by keyword.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "add_task", "description": "Create a to-do item — something the user needs to DO or complete. Use when there is a clear action to take (buy, call, fix, finish, review...). Do NOT use for general notes, facts, or things the user just wants to remember — use add_thought for those.", "input_schema": {"type": "object", "properties": {"title": {"type": "string", "description": "Short action phrase, e.g. 'Call John', 'Review server logs'"}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "due_date": {"type": "string", "description": "ISO date e.g. '2026-03-01', or null"}, "notes": {"type": "string"}}, "required": ["title"]}},
    {"name": "list_tasks", "description": "List tasks, optionally filtered by status and/or priority.", "input_schema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["pending", "in_progress", "done"]}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}}}},
    {"name": "update_task", "description": "Update an existing task — change its title, status, priority, due date, or notes. Use task_id from list_tasks.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "title": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "due_date": {"type": "string"}, "notes": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "delete_task", "description": "Permanently delete a task by its ID. Use when the user says 'delete task', 'remove task', 'cancel task'. Requires the task_id — call list_tasks first if you don't know it.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    {"name": "get_weather", "description": "Get current weather and forecast. Default to Tel Aviv.", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    {"name": "web_search", "description": "Search the web for current information, news, or facts.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}},
    {"name": "get_maccabi_matches", "description": "Get Maccabi Haifa FC upcoming matches and recent results.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_calendar_events", "description": "Fetch upcoming events from Google Calendar.", "input_schema": {"type": "object", "properties": {"days_ahead": {"type": "integer"}, "max_results": {"type": "integer"}}}},
    {"name": "add_calendar_event", "description": "Add a new event to Google Calendar.", "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string"}, "time": {"type": "string"}, "duration_minutes": {"type": "integer"}, "location": {"type": "string"}, "description": {"type": "string"}}, "required": ["title", "date"]}},
    {"name": "get_todays_google_events", "description": "Get today's events from Google Calendar.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_unread_emails", "description": "Fetch unread emails from Gmail inbox.", "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer"}}}},
    {"name": "get_google_tasks", "description": "Fetch incomplete tasks from Google Tasks.", "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer"}}}},
    {"name": "add_google_task", "description": "Add a new task to Google Tasks.", "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "due_date": {"type": "string"}, "notes": {"type": "string"}}, "required": ["title"]}},
    # ── Reminders ──────────────────────────────────────────────────────────────
    {"name": "set_reminder", "description": "Set a reminder that fires at a specific time and sends a Telegram message. Use when the user says 'remind me to...', 'reminder for...', 'alert me when...'. Parse the time from the message (e.g. 'tomorrow at 6pm', 'in 2 hours', 'Friday at 9am').", "input_schema": {"type": "object", "properties": {"text": {"type": "string", "description": "What to remind the user about."}, "when": {"type": "string", "description": "When to fire — natural language like 'tomorrow at 6pm', 'in 2 hours', 'Friday at 9am'."}}, "required": ["text", "when"]}},
    {"name": "list_reminders", "description": "List all pending reminders.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_reminder", "description": "Cancel a reminder by its ID number.", "input_schema": {"type": "object", "properties": {"reminder_id": {"type": "integer"}}, "required": ["reminder_id"]}},
    # ── GIF generation ─────────────────────────────────────────────────────────
    {"name": "generate_video_gif", "description": "Generate an animated GIF from a text prompt using Google Veo AI video generation. Use when user says 'make a gif', 'create a gif', 'generate a gif', 'make a video', 'animate', etc. Takes ~30-60 seconds.", "input_schema": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Descriptive prompt, e.g. 'a man kicks another man and he flies through a window, cartoon style'"}}, "required": ["prompt"]}},
    # ── Important Notes Vault ──────────────────────────────────────────────────
    {"name": "save_note", "description": "Save an important note under a category. Use for passwords, API keys, access tokens, important credentials, random notes the user wants stored safely, or headline-style summaries. Categories: passwords, keys, api, random, headlines.", "input_schema": {"type": "object", "properties": {"title": {"type": "string", "description": "Short descriptive label, e.g. 'GitHub Personal Token', 'WiFi Password'"}, "content": {"type": "string", "description": "The actual note content, e.g. the password, key value, or note text"}, "category": {"type": "string", "enum": ["passwords", "keys", "api", "random", "headlines"], "description": "Category for this note"}}, "required": ["title", "content", "category"]}},
    {"name": "get_notes", "description": "Retrieve saved notes, optionally filtered by category. Use when user asks to show, list, or recall notes in a specific category (passwords, keys, api, random, headlines).", "input_schema": {"type": "object", "properties": {"category": {"type": "string", "enum": ["passwords", "keys", "api", "random", "headlines"], "description": "Optional: filter by category"}}}},
    {"name": "search_notes", "description": "Search all important notes by keyword across title and content. Use when user looks up a specific note by name or keyword.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "update_note", "description": "Edit an existing note — change its title, content, or category. Requires note_id from get_notes or search_notes.", "input_schema": {"type": "object", "properties": {"note_id": {"type": "integer"}, "title": {"type": "string"}, "content": {"type": "string"}, "category": {"type": "string", "enum": ["passwords", "keys", "api", "random", "headlines"]}}, "required": ["note_id"]}},
    {"name": "delete_note", "description": "Permanently delete a note by its ID. Requires note_id from get_notes or search_notes.", "input_schema": {"type": "object", "properties": {"note_id": {"type": "integer"}}, "required": ["note_id"]}},
    # ── Navigation ─────────────────────────────────────────────────────────────
    {"name": "navigate_maps", "description": "Build a Google Maps navigation deep link for driving directions. Use when the user mentions a trip, wants to navigate somewhere, needs directions, or says they need to be at a place by a certain time. Handles Hebrew and English. IMPORTANT: always build the most complete destination string before calling — include street number + street name + city + country. If address parts arrive across multiple messages, combine them. If city or country is missing, infer from context (user is in Israel by default). Examples: 'Brandeis 33 Hadera' → 'Brandeis 33, Hadera, Israel'; 'ברנדייס 33 חדרה' → 'ברנדייס 33, חדרה, ישראל'; 'I need to be in Haifa by 12' → 'Haifa, Israel'. Do NOT ask the user for more details — infer the best address and call the tool.", "input_schema": {"type": "object", "properties": {"destination": {"type": "string", "description": "Where the user wants to go, e.g. 'Hadera, Israel', 'Jerusalem', 'Ben Gurion Airport'"}, "origin": {"type": "string", "description": "Where to leave from. Leave empty to use home address from config. Only set if user explicitly says 'from [place]' or 'leave from [place]'."}, "arrival_time": {"type": "string", "description": "If user says 'by [time]' or 'arrive by [time]' or 'I need to be there at [time]' — pass that time here, e.g. '12:00', 'noon'."}, "departure_time": {"type": "string", "description": "If user says 'leave at [time]' or 'depart at [time]' or 'around [time]' — pass that time here."}}, "required": ["destination"]}},
    # ── Image generation ───────────────────────────────────────────────────────
    {"name": "generate_image", "description": "Generate an image from a text description using DALL-E 3. Use when the user says 'generate image', 'create image', 'draw', 'make an image', 'imagine', etc. Takes ~5-10 seconds.", "input_schema": {"type": "object", "properties": {"prompt": {"type": "string", "description": "What to generate, e.g. 'a sunset over Tel Aviv skyline, photorealistic'"}}, "required": ["prompt"]}},
]

GEMINI_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=t["input_schema"])
        for t in CLAUDE_TOOLS
    ]
)


def _get_system_prompt_with_date() -> str:
    """Inject the current date/time into the system prompt on every call."""
    current_dt = datetime.now().strftime("%A, %B %d %Y, %H:%M")
    return SYSTEM_PROMPT + f"\n\nCurrent date and time: {current_dt} (Asia/Jerusalem timezone)"


def _handle_set_reminder(tool_input: dict) -> dict:
    """Parse natural language time and save the reminder."""
    text = tool_input.get("text", "")
    when = tool_input.get("when", "")
    due_iso = parse_reminder_due(when)
    return add_reminder(text=text, due=due_iso)


def run_tool(tool_name: str, tool_input: dict):
    dispatch = {
        "add_thought":              lambda: thoughts.add_thought(**tool_input),
        "list_thoughts":            lambda: thoughts.list_thoughts(**tool_input),
        "search_thoughts":          lambda: thoughts.search_thoughts(**tool_input),
        "add_task":                 lambda: tasks.add_task(**tool_input),
        "list_tasks":               lambda: tasks.list_tasks(**tool_input),
        "update_task":              lambda: tasks.update_task(**tool_input),
        "delete_task":              lambda: tasks.delete_task(**tool_input),
        "get_weather":              lambda: get_weather(**tool_input),
        "web_search":               lambda: web_search(**tool_input),
        "get_maccabi_matches":      lambda: get_maccabi_matches(),
        "get_calendar_events":      lambda: get_calendar_events(**tool_input),
        "add_calendar_event":       lambda: add_calendar_event(**tool_input),
        "get_todays_google_events": lambda: get_todays_google_events(),
        "get_unread_emails":        lambda: get_unread_emails(**tool_input),
        "get_google_tasks":         lambda: get_google_tasks(**tool_input),
        "add_google_task":          lambda: add_google_task(**tool_input),
        "set_reminder":             lambda: _handle_set_reminder(tool_input),
        "list_reminders":           lambda: list_reminders(),
        "cancel_reminder":          lambda: cancel_reminder(**tool_input),
        "generate_video_gif":       lambda: generate_video_gif(**tool_input),
        "save_note":                lambda: notes.save_note(**tool_input),
        "get_notes":                lambda: notes.get_notes(**tool_input),
        "search_notes":             lambda: notes.search_notes(**tool_input),
        "update_note":              lambda: notes.update_note(**tool_input),
        "delete_note":              lambda: notes.delete_note(**tool_input),
        "navigate_maps":            lambda: build_maps_link(**tool_input),
        "generate_image":           lambda: generate_image(**tool_input),
    }
    fn = dispatch.get(tool_name)
    if fn:
        logger.info(f"[TOOL→] {tool_name} | {_summarise(tool_input)}")
        result = fn()
        if isinstance(result, dict) and "error" in result:
            logger.warning(f"[TOOL←] {tool_name} ERROR | {result['error']}")
        else:
            logger.info(f"[TOOL←] {tool_name} OK | {_summarise(result)}")
        if tool_name == "get_weather" and isinstance(result, dict) and "current" in result:
            update_weather(result)
        if tool_name == "get_maccabi_matches" and isinstance(result, dict) and "next_match" in result:
            update_next_match(result.get("next_match", {}))
        if tool_name == "generate_video_gif" and isinstance(result, dict) and result.get("success"):
            global _pending_gif_path
            _pending_gif_path = result.get("path")
        if tool_name == "generate_image" and isinstance(result, dict) and "image_bytes" in result:
            global _pending_image_bytes
            _pending_image_bytes = result["image_bytes"]
            # Return a JSON-serializable summary — the actual bytes are in _pending_image_bytes
            return {"success": True, "message": f"Image generated. Revised prompt: {result.get('revised_prompt', '')[:120]}"}
        return result
    logger.warning(f"[TOOL ERROR] unknown tool requested: {tool_name}")
    return {"error": f"Unknown tool: {tool_name}"}


def _extract_tool_used(conversation_history: list) -> str:
    for msg in reversed(conversation_history[-6:]):
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return block.get("name", "")
    return ""


def _summarise(obj, max_len=80) -> str:
    """Turn a tool input/result into a short human-readable string."""
    try:
        s = json.dumps(obj, default=str)
        return s[:max_len] + ("…" if len(s) > max_len else "")
    except Exception:
        return str(obj)[:max_len]


# ── GEMINI ─────────────────────────────────────────────────────────────────────
def process_with_gemini(user_message: str, conversation_history: list) -> tuple[str, list]:
    t_start = time.time()

    contents = []
    for msg in conversation_history:
        if isinstance(msg["content"], str):
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    config = types.GenerateContentConfig(
        system_instruction=_get_system_prompt_with_date(),
        tools=[GEMINI_TOOLS]
    )

    tool_chain = []

    while True:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite", contents=contents, config=config,
        )
        candidate = response.candidates[0]
        parts = (candidate.content.parts if candidate.content and candidate.content.parts else [])
        safe_parts = [p for p in parts if p is not None]
        tool_call_parts = [p for p in safe_parts if p.function_call is not None]
        text_parts = [p for p in safe_parts if hasattr(p, "text") and p.text]

        if tool_call_parts:
            contents.append(types.Content(role="model", parts=parts))
            result_parts = []
            for part in tool_call_parts:
                fn = part.function_call
                result = run_tool(fn.name, dict(fn.args))
                tool_chain.append({
                    "name":           fn.name,
                    "input_summary":  _summarise(dict(fn.args)),
                    "result_summary": _summarise(result),
                })
                result_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fn.name,
                        response={"result": json.dumps(result, default=str)},
                    )
                ))
            contents.append(types.Content(role="user", parts=result_parts))
        else:
            reply = "".join(p.text for p in text_parts if p.text)
            if not reply:
                reply = "⚠️ I got the data but couldn't form a response. Please try again."
            elapsed_ms = int((time.time() - t_start) * 1000)

            conversation_history.append({"role": "user", "content": user_message})
            conversation_history.append({"role": "assistant", "content": reply})

            primary_tool = tool_chain[0]["name"] if tool_chain else ""
            logger.info(
                f"[GEMINI] tool={primary_tool or 'none'} | {elapsed_ms}ms | {len(reply)}chars"
            )
            record_message(
                text=user_message, model="gemini", tool=primary_tool,
                response=reply, tool_chain=tool_chain, elapsed_ms=elapsed_ms,
            )
            return reply, conversation_history


# ── CLAUDE ─────────────────────────────────────────────────────────────────────
def process_with_claude(user_message: str, conversation_history: list) -> tuple[str, list]:
    t_start = time.time()
    conversation_history.append({"role": "user", "content": user_message})

    tool_chain = []

    while True:
        response = claude_client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024,
            system=_get_system_prompt_with_date(),
            tools=CLAUDE_TOOLS, messages=conversation_history,
        )
        logger.debug(f"[CLAUDE] stop_reason={response.stop_reason}")

        if response.stop_reason == "tool_use":
            conversation_history.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_chain.append({
                        "name":           block.name,
                        "input_summary":  _summarise(block.input),
                        "result_summary": _summarise(result),
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str) if result is not None else "{}",
                    })
            conversation_history.append({"role": "user", "content": tool_results})
        else:
            reply = "".join(block.text for block in response.content if hasattr(block, "text"))
            if not reply:
                reply = "⚠️ I got the data but couldn't form a response. Please try again."
            elapsed_ms = int((time.time() - t_start) * 1000)

            conversation_history.append({"role": "assistant", "content": reply})

            primary_tool = tool_chain[0]["name"] if tool_chain else ""
            logger.info(
                f"[CLAUDE] tool={primary_tool or 'none'} | {elapsed_ms}ms"
                f" | in={response.usage.input_tokens} out={response.usage.output_tokens} tok"
                f" | {len(reply)}chars"
            )
            record_message(
                text=user_message, model="claude", tool=primary_tool,
                response=reply, tool_chain=tool_chain, elapsed_ms=elapsed_ms,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            return reply, conversation_history


# ── GPT — image generation ─────────────────────────────────────────────────────
def process_with_gpt(user_message: str, conversation_history: list) -> tuple[str, list]:
    """Route image-generation requests to DALL-E 3 via generate_image()."""
    t_start = time.time()
    result = generate_image(user_message)
    elapsed_ms = int((time.time() - t_start) * 1000)

    if "error" in result:
        reply = f"⚠️ Image generation failed: {result['error']}"
    else:
        global _pending_image_bytes
        _pending_image_bytes = result["image_bytes"]
        short_prompt = result.get("revised_prompt", "")[:100]
        reply = f"🎨 Here's your image!\n_{short_prompt}_" if short_prompt else "🎨 Here's your image!"

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history.append({"role": "assistant", "content": reply})

    logger.info(f"[GPT] image_gen | {elapsed_ms}ms | {len(reply)}chars")
    record_message(
        text=user_message, model="gpt", tool="generate_image",
        response=reply, tool_chain=[], elapsed_ms=elapsed_ms,
    )
    return reply, conversation_history


def process_photo(image_bytes: bytes, caption: str = "") -> str:
    """
    Analyze a photo with GPT-4o vision and return a text description.
    Called directly from main.py handle_photo() — does not go through routing.
    """
    result = analyze_photo(image_bytes, caption)
    if "error" in result:
        return f"⚠️ Couldn't analyze the image: {result['error']}"
    return result["result"]


# ── Entry point ────────────────────────────────────────────────────────────────
def process_message(user_message: str, conversation_history: list, has_photo: bool = False) -> tuple[str, list]:
    route = classify_message(user_message, has_photo=has_photo)
    if route == "simple":
        return process_with_gemini(user_message, conversation_history)
    elif route == "gpt":
        return process_with_gpt(user_message, conversation_history)
    else:
        return process_with_claude(user_message, conversation_history)
