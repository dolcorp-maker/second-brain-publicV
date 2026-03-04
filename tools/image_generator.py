"""
tools/image_generator.py

Generate images from text descriptions using DALL-E 3.
Two-step pipeline:
  1. Enhance prompt via GPT-4o-mini (mirrors video_generator.py pattern)
  2. Generate via DALL-E 3 (standard quality, 1024×1024 → ~$0.04/image)

Returns image bytes so main.py can send them directly as a Telegram photo.
"""

import base64
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_ENHANCE_SYSTEM = (
    "You are a DALL-E 3 prompt engineer. Take the user's description and rewrite it "
    "as a vivid, detailed image generation prompt. Be specific about style, lighting, "
    "composition. Keep it under 200 words. Return only the enhanced prompt, nothing else."
)


def generate_image(prompt: str) -> dict:
    """
    Enhance prompt via GPT-4o-mini, then generate image via DALL-E 3.

    Returns:
        {"image_bytes": bytes, "revised_prompt": str}
    On error:
        {"error": "..."}
    """
    try:
        # Step 1: Enhance the prompt
        enhance_resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _ENHANCE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
        )
        enhanced_prompt = enhance_resp.choices[0].message.content.strip()
        logger.info(f"[IMAGE_GEN] prompt enhanced: {enhanced_prompt[:80]}…")

        # Step 2: Generate via DALL-E 3
        gen_resp = _client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
            response_format="b64_json",
        )

        b64 = gen_resp.data[0].b64_json
        image_bytes = base64.b64decode(b64)
        revised_prompt = gen_resp.data[0].revised_prompt or enhanced_prompt

        logger.info(f"[IMAGE_GEN] generated {len(image_bytes)} bytes")
        return {"image_bytes": image_bytes, "revised_prompt": revised_prompt}

    except Exception as e:
        logger.error(f"[IMAGE_GEN] error: {e}")
        return {"error": str(e)}
