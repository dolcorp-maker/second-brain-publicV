"""
tools/gif_generator.py

Generates animated GIFs from a text prompt using Imagen 4 Fast.

Flow:
1. User says "make a gif of a sunset over the ocean"
2. We generate 5 frames via Imagen with progressively evolved prompts
3. Stitch frames into an animated GIF using PIL
4. Return the GIF file path for main.py to send via Telegram
"""

import os
import io
import base64
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GIF_DIR = Path("data/gifs")
IMAGEN_MODEL = "imagen-4.0-fast-generate-001"
FRAME_COUNT = 5
FRAME_DURATION = 120  # ms per frame — 5 frames × 120ms = ~0.6s loop, plays fast


def _build_frame_prompts(base_prompt: str) -> list[str]:
    """
    Given a base prompt, generate 5 progressive variations for animation frames.
    We ask Gemini to evolve the scene slightly between frames.
    Uses simple suffix injection to imply motion/progression.
    """
    progressions = [
        "beginning, first moment, static",
        "slightly progressed, early stage",
        "midpoint, halfway through",
        "late stage, nearly complete",
        "final moment, conclusion",
    ]

    return [
        f"{base_prompt}, animation frame {i+1} of 5, {prog}, "
        f"seamless loop, consistent style, no text, no watermark"
        for i, prog in enumerate(progressions)
    ]


def generate_gif(prompt: str) -> dict:
    """
    Generate an animated GIF from a text prompt.

    Returns:
        {"success": True, "path": "/path/to/gif", "frames": 5}
        {"error": "..."}
    """
    try:
        from google import genai
        from google.genai import types
        from PIL import Image

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        GIF_DIR.mkdir(parents=True, exist_ok=True)

        frame_prompts = _build_frame_prompts(prompt)
        frames = []

        print(f"🎬 Generating {FRAME_COUNT} frames for: {prompt}")

        for i, frame_prompt in enumerate(frame_prompts):
            print(f"  Frame {i+1}/{FRAME_COUNT}...")

            response = client.models.generate_images(
                model=IMAGEN_MODEL,
                prompt=frame_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="1:1",
                    safety_filter_level="block_low_and_above",
                ),
            )

            if not response.generated_images:
                return {"error": f"Imagen returned no image for frame {i+1}"}

            # Decode base64 image data
            img_data = response.generated_images[0].image.image_bytes
            img = Image.open(io.BytesIO(img_data)).convert("RGBA")

            # Resize to small GIF size — keeps file size low and sends fast
            img = img.resize((320, 320), Image.LANCZOS)
            frames.append(img)

        # Stitch frames into animated GIF
        output_path = GIF_DIR / f"gif_{hash(prompt) % 100000}.gif"

        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            optimize=False,
            duration=FRAME_DURATION,
            loop=0,  # 0 = loop forever
            format="GIF",
        )

        size_kb = output_path.stat().st_size // 1024
        print(f"✅ GIF saved: {output_path} ({size_kb}KB)")

        return {
            "success": True,
            "path": str(output_path),
            "frames": FRAME_COUNT,
            "size_kb": size_kb,
            "prompt": prompt,
        }

    except ImportError as e:
        return {"error": f"Missing dependency: {e}. Run: pip install pillow"}
    except Exception as e:
        return {"error": f"GIF generation failed: {str(e)}"}
