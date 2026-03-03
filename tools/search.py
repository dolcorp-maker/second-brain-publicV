"""
tools/search.py

Provides two real-time information tools:

1. get_weather(city) — fetches current weather + tomorrow's forecast
   from OpenWeatherMap's free API. Requires OPENWEATHER_API_KEY in .env

2. web_search(query) — searches the web using Brave Search API.
   Requires BRAVE_SEARCH_API_KEY in .env
   Free tier: $5 credits/month (~1,000 searches) — plenty for personal use.
   Returns real, fresh web results including recent news.

Why Brave Search instead of DuckDuckGo?
   DuckDuckGo's Instant Answer API is a knowledge base — it answers
   encyclopedic questions well but can't find today's news or recent events.
   Brave Search has its own independent web index and returns genuinely
   fresh results, making it suitable for current events, news, and
   time-sensitive queries.
"""

import os
import json
import gzip
import urllib.request
import urllib.parse


# ── WEATHER ───────────────────────────────────────────────────────────────────

def get_weather(city: str) -> dict:
    """
    Get current weather and tomorrow's forecast for any city.
    Uses OpenWeatherMap's free API (1,000 calls/day limit).
    Returns temperature in Celsius, weather description, humidity, wind speed.
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        return {"error": "OPENWEATHER_API_KEY not set in .env file"}

    try:
        current_url = (
            f"http://api.openweathermap.org/data/2.5/weather"
            f"?q={urllib.parse.quote(city)}&appid={api_key}&units=metric"
        )
        with urllib.request.urlopen(current_url, timeout=10) as response:
            current = json.loads(response.read())

        forecast_url = (
            f"http://api.openweathermap.org/data/2.5/forecast"
            f"?q={urllib.parse.quote(city)}&appid={api_key}&units=metric&cnt=16"
        )
        with urllib.request.urlopen(forecast_url, timeout=10) as response:
            forecast = json.loads(response.read())

        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow_entries = [
            entry for entry in forecast["list"]
            if entry["dt_txt"].startswith(tomorrow)
        ]
        tomorrow_summary = None
        if tomorrow_entries:
            midday = next(
                (e for e in tomorrow_entries if "12:00" in e["dt_txt"]),
                tomorrow_entries[0]
            )
            tomorrow_summary = {
                "temperature": round(midday["main"]["temp"]),
                "feels_like": round(midday["main"]["feels_like"]),
                "description": midday["weather"][0]["description"],
                "humidity": midday["main"]["humidity"],
                "wind_speed": midday["wind"]["speed"],
            }

        return {
            "city": current.get("name", city),
            "country": current.get("sys", {}).get("country", ""),
            "current": {
                "temperature": round(current["main"]["temp"]),
                "feels_like": round(current["main"]["feels_like"]),
                "description": current["weather"][0]["description"],
                "humidity": current["main"]["humidity"],
                "wind_speed": current["wind"]["speed"],
            },
            "tomorrow": tomorrow_summary,
        }

    except Exception as e:
        return {"error": f"Weather fetch failed: {str(e)}"}


# ── WEB SEARCH ────────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> dict:
    """
    Search the web using Brave Search API.

    Important implementation note — the gzip encoding issue:
    When we send 'Accept-Encoding: gzip' in the request headers, Brave
    compresses the response to save bandwidth. But Python's urllib doesn't
    automatically decompress gzip responses — it hands back raw compressed
    bytes. When our code then tries to decode those bytes as UTF-8 text,
    it fails with 'invalid start byte' because compressed data looks like
    binary gibberish, not readable text.

    Our solution has two layers:
    1. We don't send 'Accept-Encoding: gzip' so Brave sends plain text by default.
    2. As a safety net, we check the first two bytes of the response — if they're
       0x1f 0x8b (the gzip magic number), we decompress before decoding.
       This handles cases where the server sends gzip anyway regardless of headers.
    """
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return {"error": "BRAVE_SEARCH_API_KEY not set in .env file"}

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count={max_results}&search_lang=en"

        headers = {
            "Accept": "application/json",
            # Deliberately NOT including Accept-Encoding: gzip
            # to avoid having to manually decompress the response.
            "X-Subscription-Token": api_key,
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()

        # Safety net: if the server sent gzip anyway, decompress it.
        # The gzip format always starts with the magic bytes 0x1f 0x8b.
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.decompress(raw)

        data = json.loads(raw.decode("utf-8"))

        raw_results = data.get("web", {}).get("results", [])

        if not raw_results:
            return {
                "query": query,
                "results": [],
                "note": "No results found. Try rephrasing your query.",
            }

        results = []
        for r in raw_results[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
                # 'age' tells us how fresh the result is (e.g. "2 hours ago")
                "age": r.get("age", ""),
                "source": r.get("meta_url", {}).get("hostname", ""),
            })

        return {
            "query": query,
            "results": results,
            "total_found": len(results),
        }

    except Exception as e:
        return {"error": f"Web search failed: {str(e)}"}
