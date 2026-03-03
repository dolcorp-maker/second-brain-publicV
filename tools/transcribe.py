"""
tools/transcribe.py

Handles voice message transcription using one of two engines:

1. LOCAL (faster-whisper) — used on your Mac where the library is installed.
   Runs entirely offline, completely free, ~1 second per voice note.

2. API (OpenAI Whisper API) — used on the Raspberry Pi where faster-whisper
   cannot be installed due to 32-bit ARM architecture limitations.
   Cost: ~$0.001 per voice note. Negligible for personal use.

The code automatically detects which engine is available and uses it.
You don't need to configure anything — it just works on both devices.
"""

import os

# Tell HuggingFace Hub to work offline — model is already cached locally.
# This prevents the "Ignored error while writing commit hash: Read-only file system"
# warning that appears when the hub tries to update the refs/main cache file.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# We try to import faster-whisper first. If it's installed (Mac), we use it.
# If it's not installed (Pi), we fall back to the OpenAI API instead.
# This pattern is called "graceful degradation" — the code adapts to its
# environment rather than crashing when an optional dependency is missing.
try:
    from faster_whisper import WhisperModel
    print("🎙️  Loading Whisper model (local)... this may take a moment on first run")
    _local_model = WhisperModel("base", device="cpu", compute_type="int8")
    USE_LOCAL = True
    print("✅ Local Whisper model ready!")

except ImportError:
    _local_model = None
    USE_LOCAL = False
    print("🌐 Local Whisper not available — using OpenAI Whisper API for transcription")


def transcribe_voice(audio_file_path: str) -> str:
    """
    Transcribe an audio file to text using whichever engine is available.
    main.py calls this function without knowing or caring which engine runs underneath.
    """
    if USE_LOCAL:
        return _transcribe_local(audio_file_path)
    else:
        return _transcribe_api(audio_file_path)


def _transcribe_local(audio_file_path: str) -> str:
    """Transcribe using local faster-whisper. Used on Mac, runs offline."""
    print(f"🎙️  Transcribing locally: {audio_file_path}")
    segments, info = _local_model.transcribe(audio_file_path, beam_size=5)
    transcribed_text = " ".join(segment.text.strip() for segment in segments).strip()
    print(f"✅ Transcription: '{transcribed_text}'")
    print(f"   Language: {info.language} ({info.language_probability:.0%} confidence)")
    return transcribed_text


def _transcribe_api(audio_file_path: str) -> str:
    """
    Transcribe using OpenAI Whisper API. Used on Raspberry Pi.
    Cost: $0.006 per minute of audio — a 10-second voice note costs $0.001.
    """
    print(f"🎙️  Transcribing via OpenAI API: {audio_file_path}")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in .env file")

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    with open(audio_file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
        )

    transcribed_text = response.text.strip()
    print(f"✅ Transcription: '{transcribed_text}'")
    return transcribed_text


def ensure_voice_dir():
    """Create the data/voice/ folder if it doesn't exist yet."""
    os.makedirs("data/voice", exist_ok=True)
