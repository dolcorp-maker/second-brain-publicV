"""
main.py
Telegram bot entry point.

Two message types:
- Text → agent
- Voice → transcribe → agent

If user message contains a speak trigger word (speak, say, read me, etc.)
the bot also sends a voice reply via Google TTS after the text reply.
"""

import warnings
# Suppress google.api_core FutureWarning about Python 3.10 end-of-life.
# This is cosmetic only — google-api-core still works fine on 3.10.
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

import os
import re
import json
import time
import signal
import logging
import logging.handlers
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from agent import process_message, process_photo, consume_pending_gif_path, consume_pending_image_bytes
from tools.tts import should_speak, speak_reply
from tools.comm_trace import new_trace, mark_stage, finish_trace
from tools.tasks import list_tasks
from tools.thoughts import list_thoughts
from tools.reminders import list_reminders
from tools.search import get_weather

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID    = os.getenv("ALLOWED_USER_ID")

_LOG_FORMAT  = "%(asctime)s | %(levelname)-8s | %(message)s"
_LOG_DATEFMT = "%H:%M:%S"

logging.basicConfig(
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
    level=logging.INFO,
)

# Rotating file log — 5 MB × 3 backups = 15 MB max, readable by dashboard
Path("data").mkdir(exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    "data/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
logging.getLogger().addHandler(_fh)

logger = logging.getLogger(__name__)
# Silence noisy third-party loggers
for _noisy in ("httpx", "httpcore", "telegram.ext", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

try:
    from tools.transcribe import transcribe_voice, ensure_voice_dir
    VOICE_ENABLED = True
    print("🎙️  Voice transcription enabled")
except ImportError:
    VOICE_ENABLED = False
    print("⚠️  Voice transcription disabled — faster-whisper not installed")

conversation_histories: dict[int, list] = {}

HISTORY_DIR = Path("data/history")
MAX_HISTORY_MESSAGES = 20  # 10 back-and-forth exchanges


def _save_history(user_id: int, history: list):
    """Persist only text-content messages (no SDK objects or tool blocks)."""
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        clean = [m for m in history if isinstance(m.get("content"), str)]
        clean = clean[-MAX_HISTORY_MESSAGES:]
        path = HISTORY_DIR / f"{user_id}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(clean, f)
        tmp.rename(path)
    except Exception as e:
        logger.warning(f"Could not save history for {user_id}: {e}")


def _load_history(user_id: int) -> list:
    """Load persisted conversation history from disk."""
    try:
        path = HISTORY_DIR / f"{user_id}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Could not load history for {user_id}: {e}")
    return []


def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USER_ID:
        return True
    return str(user_id) == ALLOWED_USER_ID



def _extract_gif_path(new_messages: list) -> str | None:
    """
    Check only the messages added in the current exchange for a GIF result.
    new_messages must be the slice of history added after the last user turn
    (i.e. updated_history[history_len_before_call:]).
    Handles both Claude (tool_result blocks) and Gemini (string content) formats.
    Returns the GIF file path if found, None otherwise.
    """
    import json
    import re
    from pathlib import Path

    for msg in reversed(new_messages):
        raw = msg.get("content", [])

        # Claude format — list of typed blocks
        if isinstance(raw, list):
            for block in raw:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    try:
                        result = json.loads(block.get("content", "{}"))
                        path = result.get("path", "")
                        if result.get("success") and path.endswith(".gif") and Path(path).exists():
                            return path
                    except Exception:
                        pass

        # Gemini / string format — scan for a .gif path in the text
        if isinstance(raw, str):
            matches = re.findall(r'[\w/.\-]+\.gif', raw)
            for match in matches:
                if Path(match).exists():
                    return match

    return None


def split_long_reply(text: str, max_len: int = 4096) -> list[str]:
    """Split a reply into ≤4096-char chunks (Telegram message limit)."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks


async def handle_text_input(
    update: Update,
    context,
    user_message: str,
    source: str = "text",
):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"User {user_id} [{source}]: {user_message}")

    if user_id not in conversation_histories:
        conversation_histories[user_id] = _load_history(user_id)
    history = conversation_histories[user_id]

    # Send a status message immediately — replaces bare reply_text and the typing indicator.
    # All subsequent replies edit this message so there are never two overlapping messages.
    video_keywords = ["make a gif", "create a gif", "make a video", "generate a gif",
                      "gif of", "prepare a gif", "prepare gif", "want a gif",
                      "give me a gif", "get me a gif", "animate"]
    is_video = any(kw in user_message.lower() for kw in video_keywords)
    # Single A/B/1/2 reply = option selection — always treat as video to get 120 s timeout.
    # History scanning was unreliable (Claude's proposal may not mention "gif"/"video").
    if not is_video and re.match(r'^\s*[ab12]\s*$', user_message.strip()):
        is_video = True
    initial_text = "🎬 Generating your video... (~30-60 seconds, hang tight!)" if is_video else "⏳ Processing..."

    trace = new_trace(source, user_message)
    t_total = time.monotonic()
    status_msg = None
    try:
        status_msg = await update.message.reply_text(initial_text)
        history_len_before = len(history)

        # Bug #1 fix: enforce a hard timeout on AI processing.
        # Video requests get 120 s (Veo generation takes ~30-60 s + ffmpeg + send).
        # asyncio.to_thread keeps the event loop free during the blocking call.
        t_model = time.monotonic()
        _timeout = 120.0 if is_video else 60.0
        try:
            reply, updated_history = await asyncio.wait_for(
                asyncio.to_thread(process_message, user_message, history),
                timeout=_timeout,
            )
        except asyncio.TimeoutError:
            mark_stage(trace, "model", t_model)
            mark_stage(trace, "total", t_total)
            finish_trace(trace, status="timeout")
            logger.warning(f"AI timeout for user {user_id}: {user_message[:60]!r}")
            await status_msg.edit_text("⏰ Took too long, please try again.")
            return
        mark_stage(trace, "model", t_model)

        conversation_histories[user_id] = updated_history
        _save_history(user_id, updated_history)

        # Only scan messages added in THIS exchange — prevents old GIF results
        # from previous turns being re-attached to unrelated replies.
        # Fallback: Gemini tool results never enter conversation_history, so check
        # the module-level _pending_gif_path set by run_tool() as a safety net.
        gif_path = _extract_gif_path(updated_history[history_len_before:])
        if not gif_path:
            gif_path = consume_pending_gif_path()

        if gif_path:
            # Send the animation first, then edit status_msg with the full reply text below it.
            # This order ensures the video appears before the caption in the chat history.
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_video")
            with open(gif_path, "rb") as gif_file:
                await context.bot.send_animation(
                    chat_id=chat_id,
                    animation=gif_file,
                    write_timeout=180,
                    read_timeout=60,
                )

        # Send DALL-E generated image if one was produced this turn
        image_bytes = consume_pending_image_bytes()
        if image_bytes:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
            import io
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(image_bytes),
            )

        # Bug #3 fix: split reply into ≤4096-char chunks; edit status_msg with first chunk,
        # send subsequent chunks as new messages (rare — only for very long responses).
        t_send = time.monotonic()
        chunks = split_long_reply(reply)
        await status_msg.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await update.message.reply_text(chunk)
        mark_stage(trace, "send", t_send)
        mark_stage(trace, "total", t_total)
        finish_trace(trace, status="ok")

        # Send voice reply when: user sent a voice note, OR used an explicit speak keyword.
        # Guard: skip if reply is an error message or too long (speak_reply trims at 500 chars).
        if (source == "voice" or should_speak(user_message)) and not reply.startswith("⚠️"):
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_voice")
            await speak_reply(reply, chat_id, context.bot)

    except Exception as e:
        # Bug #5 fix: exc_info=True logs the full traceback, not just str(e)
        mark_stage(trace, "total", t_total)
        finish_trace(trace, status="error", error=str(e))
        logger.error(f"Error processing message from user {user_id}: {e}", exc_info=True)
        if status_msg:
            await status_msg.edit_text("⚠️ Something went wrong. Please try again.")
        else:
            await update.message.reply_text("⚠️ Something went wrong. Please try again.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze a photo sent to the bot using GPT-4o vision."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Sorry, this is a private bot.")
        return

    status_msg = await update.message.reply_text("🔍 Analyzing your photo...")
    try:
        photo = update.message.photo[-1]  # largest available size
        file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())
        caption = update.message.caption or ""

        response = await asyncio.to_thread(process_photo, image_bytes, caption)
        await status_msg.edit_text(response)
    except Exception as e:
        logger.error(f"handle_photo error for user {user_id}: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ Couldn't analyze the photo. Please try again.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Sorry, this is a private bot.")
        return
    await handle_text_input(update, context, update.message.text, source="text")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Sorry, this is a private bot.")
        return

    if not VOICE_ENABLED:
        await update.message.reply_text(
            "⚠️ Voice transcription not available. Please type your message."
        )
        return

    transcribe_status = await update.message.reply_text("🎙️ Got your voice note, transcribing...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        ensure_voice_dir()

        # Bug #13 fix: reject oversized voice files before downloading
        voice = update.message.voice
        if voice.file_size and voice.file_size > 10 * 1024 * 1024:  # 10 MB guard
            await transcribe_status.edit_text(
                "⚠️ Voice note too large (max 10 MB). Please send a shorter message."
            )
            return

        voice_file = await context.bot.get_file(voice.file_id)
        audio_path = f"data/voice/{voice.file_id}.ogg"
        await voice_file.download_to_drive(audio_path)

        t_transcribe = time.monotonic()
        try:
            # Bug #2 fix: run transcription in a thread so the event loop stays free
            # (faster-whisper inference can take 5-15 s on long notes)
            transcribed_text = await asyncio.to_thread(transcribe_voice, audio_path)
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        _voice_trace_ms = round((time.monotonic() - t_transcribe) * 1000)
        logger.info(f"Transcription done for user {user_id} in {_voice_trace_ms}ms")

        # Edit transcribing status in-place — no orphaned message left in chat
        await transcribe_status.edit_text(
            f"📝 I heard: *{transcribed_text}*",
            parse_mode="Markdown"
        )

        await handle_text_input(update, context, transcribed_text, source="voice")

    except Exception as e:
        # Bug #5 fix: exc_info=True logs the full traceback
        logger.error(f"Voice error for user {user_id}: {e}", exc_info=True)
        await transcribe_status.edit_text(
            "⚠️ Trouble processing your voice note. Please try again."
        )


def _run_systemctl(action: str, service: str) -> bool:
    """Try systemctl without sudo, fall back to sudo -n. Returns True on success."""
    for cmd in [
        ["systemctl", action, service],
        ["sudo", "-n", "systemctl", action, service],
    ]:
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0:
            return True
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Sorry, this is a private bot.")
        return

    conversation_histories[user_id] = []
    _save_history(user_id, [])

    await update.message.reply_text(
        "👋 Hey\\! I'm your *Second Brain* assistant\\.\n\n"
        "Talk naturally or use /help for all commands\\.",
        parse_mode="MarkdownV2"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return
    voice_line = "🎙 *Voice in:* Send a voice note — I'll transcribe it\n" if VOICE_ENABLED else ""
    await update.message.reply_text(
        "🧠 *Second Brain — All Commands*\n\n"
        "*Quick data views*\n"
        "/tasks — pending & in\\-progress tasks\n"
        "/thoughts — your 10 most recent thoughts\n"
        "/reminders — pending reminders\n"
        "/weather — current Tel Aviv weather\n"
        "/status — services & system health\n\n"
        "*Memory*\n"
        "/clear — wipe conversation memory\n"
        "/start — fresh start \\(also clears memory\\)\n\n"
        "*System*\n"
        "/restart — restart bot, dashboard & scheduler\n"
        "/shutdown — stop all services\n\n"
        "*Just talk naturally, for example:*\n"
        "📝 \"Note this: I want to try cold showers\"\n"
        "✅ \"Add task: Call dentist, high priority\"\n"
        "✅ \"Mark task 3 as done\" / \"Delete task 5\"\n"
        "📅 \"Schedule standup tomorrow at 10am\"\n"
        "📅 \"What's on my calendar today?\"\n"
        "⏰ \"Remind me in 2 hours to take a break\"\n"
        "🌤 \"Will it rain tomorrow?\"\n"
        "🔍 \"Search for latest AI news\"\n"
        "⚽ \"Maccabi next match?\"\n"
        "🎬 \"Make a gif of a cat doing yoga\"\n"
        f"{voice_line}"
        "🔊 Start with *speak* or *read me* for voice reply",
        parse_mode="MarkdownV2"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Not authorized.")
        return
    conversation_histories[user_id] = []
    _save_history(user_id, [])
    await update.message.reply_text("🧹 Memory cleared! Starting fresh.")


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return
    result = list_tasks()
    all_tasks = result.get("tasks", [])
    open_tasks = [t for t in all_tasks if t.get("status") != "done"]
    if not open_tasks:
        await update.message.reply_text("✅ No open tasks — you're all caught up!")
        return
    priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines = [f"📋 *Tasks ({len(open_tasks)} open)*\n"]
    for t in open_tasks:
        icon = priority_icon.get(t.get("priority", "medium"), "🟡")
        status = "⏳ " if t.get("status") == "in_progress" else ""
        due = f"  _{t['due_date']}_" if t.get("due_date") else ""
        title = t['title'].replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[')
        lines.append(f"{icon} *#{t['id']}* {status}{title}{due}")
    lines.append('\n_"mark task 3 done" · "delete task 2" · "add task: ..."_')
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def thoughts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return
    all_thoughts = list_thoughts()
    recent = all_thoughts[-10:][::-1]  # last 10, newest first
    if not recent:
        await update.message.reply_text("💭 No thoughts saved yet.\nTry: \"Note this: ...\"")
        return
    lines = [f"💭 *Recent Thoughts* (showing {len(recent)} of {len(all_thoughts)})\n"]
    for t in recent:
        snippet = t["content"][:80].replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")
        if len(t["content"]) > 80:
            snippet += "…"
        lines.append(f"*#{t['id']}* {snippet}")
    lines.append('\n_"search thoughts <keyword>" to find specific ones_')
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return
    result = list_reminders()
    reminders = result.get("reminders", [])
    if not reminders:
        await update.message.reply_text("⏰ No pending reminders.\nTry: \"Remind me in 2 hours to ...\"")
        return
    lines = [f"⏰ *Reminders ({len(reminders)} pending)*\n"]
    for r in reminders:
        due_display = r.get("due_display", r.get("due", ""))
        time_until = r.get("time_until", "")
        text = r["text"].replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")
        lines.append(f"*#{r['id']}* {text}\n   _{due_display}_ ({time_until})")
    lines.append('\n_"cancel reminder 2" to remove one_')
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    data = await asyncio.to_thread(get_weather, os.getenv("USER_CITY", "London"))
    if "error" in data:
        await update.message.reply_text(f"⚠️ {data['error']}")
        return
    c = data.get("current", {})
    t = data.get("tomorrow", {})
    tomorrow_line = (
        f"\n🔮 *Tomorrow:* {t['temperature']}°C, {t['description']}"
        if t else ""
    )
    await update.message.reply_text(
        f"🌤 *{data['city']}, {data['country']}*\n\n"
        f"*Now:* {c['temperature']}°C, {c['description']}\n"
        f"Feels like {c['feels_like']}°C · Humidity {c['humidity']}% · Wind {c['wind_speed']} m/s"
        f"{tomorrow_line}",
        parse_mode="Markdown"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    SERVICES = [
        ("secondbrain",           "Bot"),
        ("secondbrain-dashboard", "Dashboard"),
        ("secondbrain-scheduler", "Scheduler"),
    ]
    service_lines = []
    for unit, label in SERVICES:
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
        active = r.stdout.strip() == "active"
        icon = "🟢" if active else "🔴"
        service_lines.append(f"{icon} *{label}*")

    try:
        import psutil
        cpu   = psutil.cpu_percent(interval=0.3)
        ram   = psutil.virtual_memory()
        disk  = psutil.disk_usage("/")
        sys_lines = (
            f"CPU: {cpu}% · RAM: {ram.percent}% "
            f"({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\n"
            f"Disk: {disk.percent}% "
            f"({disk.used / (1024**3):.1f}GB / {disk.total / (1024**3):.1f}GB)"
        )
    except Exception:
        sys_lines = "_(system stats unavailable)_"

    now = datetime.now().strftime("%H:%M, %d %b")
    await update.message.reply_text(
        f"⚡ *Status* — {now}\n\n"
        + "\n".join(service_lines)
        + f"\n\n{sys_lines}",
        parse_mode="Markdown"
    )


async def shutdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Not authorized.")
        return

    await update.message.reply_text(
        "⚠️ *SHUTDOWN INITIATED*\n\nStopping Dashboard · Scheduler · Bot...",
        parse_mode="Markdown"
    )
    subprocess.Popen([
        "bash", "-c",
        "sleep 1 && "
        "systemctl stop secondbrain-dashboard ; "
        "systemctl stop secondbrain-scheduler ; "
        "systemctl stop secondbrain"
    ])


async def restart_services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Not authorized.")
        return

    failed = []
    for svc in ["secondbrain-dashboard", "secondbrain-scheduler"]:
        if not _run_systemctl("restart", svc):
            failed.append(svc)

    if failed:
        await update.message.reply_text(
            "⚠️ *Could not restart:* " + ", ".join(failed) + "\n\n"
            "To fix, run this once on the server:\n"
            "`sudo visudo` and add:\n"
            "`youruser ALL=(ALL) NOPASSWD: /bin/systemctl restart secondbrain*`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🔄 *Dashboard & Scheduler restarted.*\n"
            "Bot restarting now — back in ~5 seconds.",
            parse_mode="Markdown"
        )

    # Restart the bot itself cleanly — systemd (Restart=always) brings it back
    async def _self_restart():
        await asyncio.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)
    asyncio.create_task(_self_restart())


async def _send_startup_notification(app):
    """Send a Telegram message to the owner when the bot comes online."""
    if not ALLOWED_USER_ID:
        return
    try:
        now = datetime.now().strftime("%H:%M")
        await app.bot.send_message(
            chat_id=int(ALLOWED_USER_ID),
            text=f"🤖 *Second Brain is online* \\— {now}\n\nReady\\.",
            parse_mode="MarkdownV2",
        )
        logger.info("✅ Startup notification sent to owner.")
    except Exception as e:
        logger.warning(f"Could not send startup notification: {e}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env!")

    logger.info("🚀 Starting Second Brain Bot...")
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(read_timeout=120, connect_timeout=30, write_timeout=120)
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .post_init(_send_startup_notification)
        .build()
    )

    app.add_handler(CommandHandler("start",     start_command))
    app.add_handler(CommandHandler("help",      help_command))
    app.add_handler(CommandHandler("clear",     clear_command))
    app.add_handler(CommandHandler("tasks",     tasks_command))
    app.add_handler(CommandHandler("thoughts",  thoughts_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("weather",   weather_command))
    app.add_handler(CommandHandler("status",    status_command))
    app.add_handler(CommandHandler("restart",   restart_services_command))
    app.add_handler(CommandHandler("shutdown",  shutdown_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✅ Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
