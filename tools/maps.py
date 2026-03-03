"""
tools/maps.py

Builds a Google Maps deep link for navigation.
Opens turn-by-turn navigation directly on mobile.

No API key required — uses the public maps.google.com URL scheme.
Origin defaults to HOME_ADDRESS from .env unless overridden.
Address resolution is handled by Google Maps itself (no external geocoding).
Claude normalises the destination text before calling this tool.
"""

import os
from urllib.parse import urlencode

HOME_ADDRESS = os.getenv("HOME_ADDRESS", "")


def build_maps_link(
    destination: str,
    origin: str = None,
    arrival_time: str = None,
    departure_time: str = None,
) -> dict:
    """
    Build a Google Maps navigation deep link.

    destination:    Where to go — must include street, city, and country.
                    Google Maps resolves the address; Hebrew and English both work.
    origin:         Where to leave from — defaults to HOME_ADDRESS from .env
    arrival_time:   Natural language arrival time (e.g. "12:00", "noon") — informational only
    departure_time: Natural language departure time (e.g. "10:30") — informational only

    Returns a dict with the Maps URL and a formatted message.
    """
    try:
        origin      = (origin or HOME_ADDRESS).strip()
        destination = destination.strip()

        if not destination:
            return {"error": "No destination provided."}

        # Build the deep link.
        # dir_action=navigate opens turn-by-turn immediately on mobile.
        # Google Maps resolves partial/misspelled/Hebrew addresses on its end.
        params = {
            "api":         "1",
            "origin":      origin,
            "destination": destination,
            "travelmode":  "driving",
            "dir_action":  "navigate",
        }
        url = "https://www.google.com/maps/dir/?" + urlencode(params)

        # Build a human-readable reply
        origin_label = "home" if origin == HOME_ADDRESS else origin
        lines = [f"🗺️ *Navigation to {destination}*"]
        lines.append(f"📍 From: {origin_label}")

        if arrival_time:
            lines.append(f"🕐 Arrive by: {arrival_time}")
        if departure_time:
            lines.append(f"🚗 Depart around: {departure_time}")

        lines.append(f"\n[▶ Open in Google Maps]({url})")
        lines.append("_Tap the link to start navigation on your phone._")

        return {
            "success":        True,
            "url":            url,
            "origin":         origin,
            "destination":    destination,
            "arrival_time":   arrival_time,
            "departure_time": departure_time,
            "message":        "\n".join(lines),
        }

    except Exception as e:
        return {"error": str(e)}
