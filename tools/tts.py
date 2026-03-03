"""
tools/tts.py

Text-to-speech using gTTS (Google Translate TTS — free, no API key needed).
Converts bot reply text to an MP3 voice message and sends it via Telegram.

Triggered when the user's message contains a speak keyword:
  "speak", "say", "read me", "tell me", "voice"

Flow:
  1. Bot generates normal text reply
  2. main.py detects speak keyword in original user message
  3. Calls speak_reply(text, chat_id, bot) to generate and send audio
  4. Text reply is also sent so the user has both

Dependencies:
  pip install gtts pydub
  sudo apt install -y ffmpeg  (for audio conversion if needed)
"""

import os
import re
import tempfile
from pathlib import Path

# Speak trigger phrases — only fire when user explicitly requests a voice reply.
# Intentionally strict: "tell me", "say ", "voice", "audio" were removed
# because they match common queries like "tell me the weather" or "voice note".
SPEAK_TRIGGERS = [
    "speak",           # "speak", "speak it", "speak the answer"
    "read me",         # "read me this", "read me back"
    "read it",         # "read it out"
    "out loud",        # "say it out loud", "read out loud"
    "answer with voice",
    "reply with voice",
    "voice reply",
    "voice answer",
    "אמור",            # Hebrew: "say"
    "דבר",             # Hebrew: "speak"
    "בקול",            # Hebrew: "out loud"
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
    - Remove tool names and technical artifacts
    """
    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'#+\s*', '', text)

    # Remove emoji — match unicode emoji ranges
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)

    # Collapse multiple spaces/newlines
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def detect_language(text: str) -> str:
    """
    Detect if the text is primarily Hebrew or English.
    Returns 'iw' for Hebrew (Google TTS code), 'en' for English.
    """
    hebrew_chars = sum(1 for c in text if '\u05d0' <= c <= '\u05ea')
    return 'iw' if hebrew_chars > len(text) * 0.2 else 'en'


async def speak_reply(text: str, chat_id: int, bot) -> bool:
    """
    Convert text to speech and send as a Telegram voice message.

    text    — the bot's reply text to speak
    chat_id — Telegram chat ID to send to
    bot     — the python-telegram-bot Bot instance

    Returns True if successful, False if TTS failed (text reply already sent).
    """
    try:
        from gtts import gTTS

        cleaned = clean_text_for_speech(text)
        if not cleaned:
            return False

        # Limit to 500 chars for voice — long replies should stay as text
        if len(cleaned) > 500:
            cleaned = cleaned[:500] + "... and more in the text above."

        lang = detect_language(cleaned)

        # Generate TTS audio to a temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        tts = gTTS(text=cleaned, lang=lang, slow=False)
        tts.save(tmp_path)

        # Send as voice message via Telegram
        with open(tmp_path, "rb") as audio_file:
            await bot.send_voice(
                chat_id=chat_id,
                voice=audio_file,
                caption="🔊",
            )

        # Clean up temp file
        os.unlink(tmp_path)
        return True

    except ImportError:
        # gTTS not installed — fail silently
        return False
    except Exception as e:
        print(f"TTS error: {e}")
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return False
