"""
tools/image_analyzer.py

Analyze photos sent to Telegram using GPT-4o vision.
Auto-detects mode from caption keywords:
  - food   : nutrition facts (calories, macros, ingredients)
  - plant  : identification (EN + HE name, edible/toxic, care tips)
  - general: factual description (default)

Image pre-processing: Pillow resize to ≤1280px and JPEG re-encode
to keep payloads under 1 MB for mobile photos that can be 5–10 MB.
"""

import base64
import io
import logging
import os

from PIL import Image
from openai import OpenAI

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

FOOD_KEYWORDS  = ["food", "eat", "eating", "calories", "nutrition", "meal", "dish", "recipe"]
PLANT_KEYWORDS = ["plant", "flower", "tree", "leaf", "herb", "bush", "weed", "grow"]

_SYSTEM_PROMPTS = {
    "food": (
        "You are a nutrition expert. Analyze this food photo and return:\n"
        "- Dish name\n"
        "- Estimated calories (range)\n"
        "- Macros: protein / carbs / fat (rough grams)\n"
        "- Key ingredients visible\n"
        "- One interesting fact about this dish\n"
        "Keep it concise, friendly, use emojis. "
        "Reply in the same language the user captioned the photo (default English)."
    ),
    "plant": (
        "You are a botanist. Analyze this plant photo and return:\n"
        "- Common name in English\n"
        "- Common name in Hebrew (if known, else write \"לא ידוע\")\n"
        "- Edible / Toxic / Not for consumption (be clear)\n"
        "- Brief care guide: watering, sunlight, soil\n"
        "- Where it naturally grows\n"
        "Keep it concise. Use ✅ for edible, ⚠️ for toxic, ❓ for unknown."
    ),
    "general": (
        "You are a helpful assistant. Describe this image clearly and factually:\n"
        "- Main subjects / objects\n"
        "- Colors, setting, context\n"
        "- Any text visible in the image\n"
        "- Anything notable or unusual\n"
        "Keep it to 3–5 sentences. Be objective."
    ),
}


def compress_image(image_bytes: bytes, max_size: int = 1280) -> bytes:
    """Resize so longest side <= max_size, re-encode as JPEG quality=85."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")  # strip alpha, handle HEIC edge cases
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _detect_mode(caption: str) -> str:
    """Detect analysis mode from caption keywords."""
    cap = caption.lower()
    for kw in FOOD_KEYWORDS:
        if kw in cap:
            return "food"
    for kw in PLANT_KEYWORDS:
        if kw in cap:
            return "plant"
    return "general"


def analyze_photo(image_bytes: bytes, caption: str = "", mode: str = "") -> dict:
    """
    Analyze a photo using GPT-4o vision.

    image_bytes — raw bytes of the photo (any format Pillow supports)
    caption     — optional user caption (used for mode detection + user prompt)
    mode        — override auto-detection: 'food', 'plant', or 'general'

    Returns:
        {"result": "...", "mode": "food|plant|general"}
    On error:
        {"error": "..."}
    """
    try:
        resolved_mode = mode if mode in _SYSTEM_PROMPTS else _detect_mode(caption)
        detail = "high" if resolved_mode == "plant" else "low"

        compressed = compress_image(image_bytes)
        b64 = base64.b64encode(compressed).decode("utf-8")

        user_text = caption if caption else "Analyze this image."

        response = _client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPTS[resolved_mode]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": detail,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
            max_tokens=600,
        )

        result = response.choices[0].message.content
        logger.info(f"[IMAGE_ANALYZER] mode={resolved_mode} detail={detail} chars={len(result)}")
        return {"result": result, "mode": resolved_mode}

    except Exception as e:
        logger.error(f"[IMAGE_ANALYZER] error: {e}")
        return {"error": str(e)}
