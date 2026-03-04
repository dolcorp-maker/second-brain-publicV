"""
tools/tts.py

Text-to-speech using OpenAI TTS (tts-1 model, nova voice).
Warm, natural voice — handles Hebrew and English natively.
~$0.015 per 1,000 characters (~$0.002 per average 150-char reply).

Voice reply triggers:
  1. User sent a voice note (source="voice" in handle_text_input)
  2. User message contains an explicit speak keyword (should_speak returns True)

Never triggered for:
  - Regular text messages without speak keywords
  - Error messages
  - Responses longer than 500 chars (trimmed inside speak_reply)
"""

import logging
import os
import re
import tempfile

from openai import OpenAI

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Speak trigger phrases — only fire when user explicitly requests a voice reply.
SPEAK_TRIGGERS = [
    "speak",             # "speak", "speak it", "speak the answer"
    "read me",           # "read me this", "read me back"
    "read it",           # "read it out"
    "out loud",          # "say it out loud", "read out loud"
    "answer with voice",
    "reply with voice",
    "voice reply",
    "voice answer",
    "say out loud",
    "read out loud",
    "אמור",              # Hebrew: "say"
    "דבר",               # Hebrew: "speak"
    "בקול",              # Hebrew: "out loud"
    "תקרא לי",           # Hebrew: "read to me"
    "תגיד",              # Hebrew: "say/tell"
]


def should_speak(user_message: str) -> bool:
    """Return True only when the user explicitly requests a voice reply."""
    msg = user_message.lower()
    return any(trigger in msg for trigger in SPEAK_TRIGGERS)


def clean_text_for_speech(text: str) -> str:
    """
    Clean up bot reply text for better TTS output.
    - Remove markdown formatting (* ** ` etc)
    - Remove emoji (TTS reads them as unicode descriptions)
    - Collapse whitespace
    """
    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'#+\s*', '', text)

    # Remove emoji — match unicode emoji ranges
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)

    # Collapse multiple spaces/newlines
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def text_to_speech(text: str) -> bytes | None:
    """
    Convert text to MP3 bytes using OpenAI TTS (tts-1, nova voice).
    Returns mp3 bytes on success, None on error (bot stays silent, doesn't crash).
    """
    try:
        response = _client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=text[:4096],  # OpenAI TTS limit
        )
        return response.content
    except Exception as e:
        logger.error(f"[TTS] OpenAI TTS failed: {e}")
        return None


async def speak_reply(text: str, chat_id: int, bot) -> bool:
    """
    Convert text to speech and send as a Telegram voice message.

    text    — the bot's reply text to speak
    chat_id — Telegram chat ID to send to
    bot     — the python-telegram-bot Bot instance

    Returns True if successful, False if TTS failed (text reply already sent).
    """
    try:
        cleaned = clean_text_for_speech(text)
        if not cleaned:
            return False

        # Limit to 500 chars for voice — long replies should stay as text
        if len(cleaned) > 500:
            cleaned = cleaned[:500] + "... and more in the text above."

        mp3_bytes = text_to_speech(cleaned)
        if not mp3_bytes:
            return False

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            await bot.send_voice(
                chat_id=chat_id,
                voice=audio_file,
                caption="🔊",
            )

        os.unlink(tmp_path)
        return True

    except Exception as e:
        logger.error(f"[TTS] speak_reply failed: {e}")
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return False
