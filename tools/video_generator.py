"""
tools/video_generator.py

Generates animated GIFs from a text prompt using Google Veo 3.

Flow:
1. Claude enhances the user's casual prompt into a motion-rich Veo prompt
2. Call Veo 3 Fast to generate a 5-second MP4
3. Poll until done
4. Download MP4 with API key auth
5. Convert to GIF with ffmpeg (320px wide, 10fps, loops forever)
6. Return GIF path for main.py to send via Telegram
"""

import os
import time
import subprocess
import urllib.request
import sys
# Force stdout to flush immediately so journalctl shows live progress
sys.stdout.reconfigure(line_buffering=True)
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

VIDEO_DIR     = Path("data/videos")
VEO_MODEL     = "models/veo-3.0-fast-generate-001"
POLL_INTERVAL = 5
MAX_WAIT      = 300


def _enhance_prompt(user_prompt: str) -> str:
    """
    Use Claude to rewrite a casual user prompt into a motion-rich,
    high-contrast, cinematic Veo prompt that produces dynamic video.

    Examples:
        "a sunset" →
        "a vibrant sunset, sun rapidly sinking below the horizon,
         dramatic orange and red clouds sweeping across the sky,
         golden light shifting and intensifying, cinematic, high contrast"

        "a man kicks another man" →
        "a cartoon man winds up and delivers a powerful kick, the other
         man flies through the air arms flailing, crashes through a glass
         window in an explosion of shards, looney tunes style, exaggerated
         motion, high contrast, dynamic action"
    """
    try:
        import anthropic
        client = anthropic.Anthropic()

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Rewrite this into a Veo video generation prompt. "
                    f"Make it motion-rich, high contrast, and visually dynamic. "
                    f"Emphasize movement, action, and dramatic visuals. "
                    f"Keep it under 80 words. Return ONLY the enhanced prompt, nothing else.\n\n"
                    f"User prompt: {user_prompt}"
                )
            }]
        )

        enhanced = response.content[0].text.strip()
        print(f"  ✨ Enhanced prompt: {enhanced}")
        return enhanced

    except Exception as e:
        print(f"  ⚠️ Prompt enhancement failed ({e}), using original")
        return user_prompt


def generate_video_gif(prompt: str) -> dict:
    """
    Generate an animated GIF from a text prompt via Veo 3.

    Returns:
        {"success": True, "path": "/path/to/file.gif", "prompt": "..."}
        {"error": "..."}
    """
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)

        # ── Step 1: Enhance prompt ────────────────────────────────────────────
        enhanced_prompt = _enhance_prompt(prompt)

        safe_name = "".join(
            c for c in prompt[:30] if c.isalnum() or c == " "
        ).strip().replace(" ", "_")
        ts = int(time.time())

        mp4_path = VIDEO_DIR / f"{safe_name}_{ts}.mp4"
        gif_path = VIDEO_DIR / f"{safe_name}_{ts}.gif"

        # ── Step 2: Start Veo generation ──────────────────────────────────────
        print(f"🎬 Starting Veo: {enhanced_prompt[:60]}...")
        operation = client.models.generate_videos(
            model=VEO_MODEL,
            prompt=enhanced_prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio="16:9",
                number_of_videos=1,
            ),
        )

        # ── Step 3: Poll until done ───────────────────────────────────────────
        waited = 0
        while not operation.done:
            print(f"  ⏳ Rendering... ({waited}s elapsed)")
            time.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
            operation = client.operations.get(operation)
            if waited >= MAX_WAIT:
                return {"error": "Veo timed out after 5 minutes"}

        if operation.error:
            return {"error": f"Veo error: {operation.error}"}

        # ── Step 4: Download MP4 ──────────────────────────────────────────────
        uri = operation.response.generated_videos[0].video.uri
        api_key = os.getenv("GEMINI_API_KEY")
        print(f"  ⬇️  Downloading MP4...")
        urllib.request.urlretrieve(uri + "&key=" + api_key, str(mp4_path))
        print(f"  MP4: {mp4_path.stat().st_size // 1024}KB")

        # ── Step 5: Convert to GIF ────────────────────────────────────────────
        print(f"  🔄 Converting to GIF...")
        result = subprocess.run([
            "ffmpeg", "-i", str(mp4_path),
            "-vf", "fps=10,scale=320:-1:flags=lanczos",
            "-loop", "0",
            str(gif_path), "-y",
        ], capture_output=True, text=True)

        if result.returncode != 0:
            return {"error": f"ffmpeg failed: {result.stderr[-200:]}"}

        gif_size_kb = gif_path.stat().st_size // 1024
        print(f"  ✅ GIF ready: {gif_path} ({gif_size_kb}KB)")

        mp4_path.unlink(missing_ok=True)

        return {
            "success":         True,
            "path":            str(gif_path),
            "size_kb":         gif_size_kb,
            "prompt":          prompt,
            "enhanced_prompt": enhanced_prompt,
        }

    except Exception as e:
        return {"error": f"Video generation failed: {str(e)}"}
