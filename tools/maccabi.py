"""
tools/maccabi.py

Fetches Maccabi Haifa FC match information from their official website.

Strategy:
1. First try to extract the __NEXT_DATA__ JSON that Next.js embeds in every page.
   This gives us perfectly clean structured data with no ambiguity.
2. If that fails, fall back to a targeted HTML parser that looks specifically
   inside the matches section, not the entire page.
3. If both fail, return the hardcoded fallback data we already know is correct.
"""

import urllib.request
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime


# ── Translation tables ─────────────────────────────────────────────────────────

HEBREW_MONTHS = {
    "ינואר": "January", "פברואר": "February", "מרץ": "March",
    "אפריל": "April", "מאי": "May", "יוני": "June",
    "יולי": "July", "אוגוסט": "August", "ספטמבר": "September",
    "אוקטובר": "October", "נובמבר": "November", "דצמבר": "December",
}

HEBREW_DAYS = {
    "ראשון": "Sunday", "שני": "Monday", "שלישי": "Tuesday",
    "רביעי": "Wednesday", "חמישי": "Thursday", "שישי": "Friday", "שבת": "Saturday",
}

TEAM_NAMES = {
    "מכבי חיפה": "Maccabi Haifa",
    "הפועל תל אביב": "Hapoel Tel Aviv",
    "מכבי תל אביב": "Maccabi Tel Aviv",
    "הפועל פתח תקווה": "Hapoel Petah Tikva",
    "הפועל פ\"ת": "Hapoel Petah Tikva",
    "בני סכנין": "Bnei Sakhnin",
    'עירוני קריית שמונה': "Ironi Kiryat Shmona",
    'בית"ר ירושלים': "Beitar Jerusalem",
    "הפועל חיפה": "Hapoel Haifa",
    "מכבי נתניה": "Maccabi Netanya",
    "הפועל ב\"ש": "Hapoel Beer Sheva",
    "הפועל באר שבע": "Hapoel Beer Sheva",
    "מכבי פתח תקווה": "Maccabi Petah Tikva",
    "מכבי תל-אביב": "Maccabi Tel Aviv",
}

VENUES = {
    "סמי עופר": "Sami Ofer (Home)",
    "בלומפילד": "Bloomfield (Away)",
    "טדי": "Teddy (Away)",
    "טרנר": "Turner (Away)",
    "דוחא": "Doha (Away)",
}

COMPETITIONS = {
    "ליגת WINNER": "Winner League",
    "גביע המדינה": "State Cup",
    "ליגת האלופות": "Champions League",
    "ליגת אירופה": "Europa League",
}


def translate_team(text: str) -> str:
    """Translate a Hebrew team name to English. Returns original if not found."""
    text = text.strip()
    for heb, eng in TEAM_NAMES.items():
        if heb in text:
            return eng
    return text


def translate_venue(text: str) -> str:
    """Translate a Hebrew venue name to English."""
    for heb, eng in VENUES.items():
        if heb in text:
            return eng
    return text.strip()


def translate_competition(text: str) -> str:
    """Translate a Hebrew competition name to English."""
    for heb, eng in COMPETITIONS.items():
        if heb in text:
            return eng
    return text.strip()


def translate_date(day_num: str, day_name_heb: str, month_heb: str) -> str:
    """Build an English date string from Hebrew components."""
    day_eng = HEBREW_DAYS.get(day_name_heb, day_name_heb)
    month_eng = HEBREW_MONTHS.get(month_heb, month_heb)
    return f"{day_eng} {day_num} {month_eng}"


def get_maccabi_matches() -> dict:
    """
    Main entry point. Fetches and returns Maccabi Haifa match data.
    Tries multiple parsing strategies with graceful fallback.
    """
    try:
        # We fetch the homepage because it contains the matches widget
        # with the most recent and upcoming matches already embedded.
        url = "https://www.mhaifafc.com/?lang=en"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")

        soup = BeautifulSoup(html, "html.parser")

        # ── Strategy 1: Parse __NEXT_DATA__ JSON ──────────────────────────────
        # Next.js apps embed all their server-rendered data as a JSON blob
        # in a <script id="__NEXT_DATA__"> tag. This is the cleanest source
        # because it's already structured — no HTML interpretation needed.
        result = _try_nextjs_json(soup)
        if result:
            return result

        # ── Strategy 2: Targeted HTML parsing ────────────────────────────────
        # If the JSON approach didn't work, parse the HTML but be surgical —
        # only look inside the section that contains match data, not the
        # entire page (which also has navigation, footer, etc. that confuse
        # a broad text scanner).
        result = _try_targeted_html(soup)
        if result:
            return result

        # ── Strategy 3: Hardcoded fallback ───────────────────────────────────
        return _hardcoded_fallback()

    except Exception as e:
        # Even if the network call fails entirely, return useful data
        fallback = _hardcoded_fallback()
        fallback["fetch_error"] = str(e)
        return fallback


def _try_nextjs_json(soup: BeautifulSoup) -> dict | None:
    """
    Try to extract match data from the __NEXT_DATA__ JSON blob.
    Returns parsed match dict if successful, None if the structure
    doesn't contain what we need.
    """
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script:
        return None

    try:
        data = json.loads(script.string)
        page_props = data.get("props", {}).get("pageProps", {})

        # The site might store matches under various key names.
        # We search for any list that looks like match data.
        def find_matches(obj, depth=0):
            """Recursively search for a list that looks like match records."""
            if depth > 5:
                return None
            if isinstance(obj, list) and len(obj) > 0:
                first = obj[0]
                if isinstance(first, dict):
                    keys = set(first.keys())
                    # Match records typically have team-related keys
                    match_indicators = {'homeTeam', 'awayTeam', 'home', 'away',
                                       'homeScore', 'awayScore', 'matchDate', 'date'}
                    if keys & match_indicators:
                        return obj
            if isinstance(obj, dict):
                for key in ['matches', 'games', 'fixtures', 'schedule', 'upcomingMatches']:
                    if key in obj:
                        result = find_matches(obj[key], depth + 1)
                        if result:
                            return result
                for val in obj.values():
                    result = find_matches(val, depth + 1)
                    if result:
                        return result
            return None

        matches_raw = find_matches(page_props)
        if not matches_raw:
            return None

        upcoming = []
        past = []

        for m in matches_raw:
            # Extract fields using multiple possible key names
            home = translate_team(
                m.get("homeTeam", {}).get("name", "") if isinstance(m.get("homeTeam"), dict)
                else m.get("homeTeam", "") or m.get("home", "")
            )
            away = translate_team(
                m.get("awayTeam", {}).get("name", "") if isinstance(m.get("awayTeam"), dict)
                else m.get("awayTeam", "") or m.get("away", "")
            )
            date = m.get("date") or m.get("matchDate") or m.get("gameDate", "")
            time = m.get("time") or m.get("matchTime") or m.get("hour", "")
            venue = translate_venue(m.get("stadium", "") or m.get("venue", "") or m.get("location", ""))
            competition = translate_competition(m.get("competition", "") or m.get("league", "") or "")
            home_score = m.get("homeScore") or m.get("homeGoals")
            away_score = m.get("awayScore") or m.get("awayGoals")

            entry = {
                "date": date,
                "time": time,
                "home_team": home,
                "away_team": away,
                "venue": venue,
                "competition": competition,
            }

            if home_score is not None and away_score is not None:
                entry["result"] = f"{home} {home_score} - {away_score} {away}"
                past.append(entry)
            else:
                upcoming.append(entry)

        if not upcoming and not past:
            return None

        return {
            "next_match": upcoming[0] if upcoming else None,
            "upcoming": upcoming[:5],
            "last_result": past[-1] if past else None,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "mhaifafc.com (live)",
            "method": "nextjs_json",
        }

    except Exception:
        return None


def _try_targeted_html(soup: BeautifulSoup) -> dict | None:
    """
    Parse match data from the rendered HTML.

    The key insight is that we DON'T scan the entire page.
    Instead we look for the specific section that the homepage showed us —
    a repeating pattern of: day_number + day_name + month → competition →
    venue → team1 → score_or_time → team2.

    We identify match blocks by looking for elements that contain BOTH
    a Hebrew month name AND a known team name in close proximity,
    which filters out navigation and other page elements reliably.
    """
    try:
        upcoming = []
        past = []

        # Find all text nodes that contain Hebrew month names —
        # these anchor our search to actual date positions in the document
        full_text = soup.get_text(separator="|||")
        segments = full_text.split("|||")

        # We'll build a sliding window over segments, looking for the
        # specific pattern: digit (day) → Hebrew day name → Hebrew month
        i = 0
        current_match = {}

        while i < len(segments):
            seg = segments[i].strip()

            # Detect a day number (1-31) that anchors a match block
            if re.match(r"^\d{1,2}$", seg) and 1 <= int(seg) <= 31:
                day_num = seg
                day_name_heb = ""
                month_heb = ""

                # Look ahead for day name and month within the next 5 segments
                for j in range(i + 1, min(i + 6, len(segments))):
                    candidate = segments[j].strip()
                    if candidate in HEBREW_DAYS:
                        day_name_heb = candidate
                    if candidate in HEBREW_MONTHS:
                        month_heb = candidate
                    if day_name_heb and month_heb:
                        break

                # Only proceed if we found both a day name and month —
                # this filters out random numbers elsewhere on the page
                if day_name_heb and month_heb:
                    # Save previous match if we were building one
                    if current_match and "home_team" in current_match:
                        if "result" in current_match:
                            past.append(current_match)
                        else:
                            upcoming.append(current_match)

                    current_match = {
                        "date": translate_date(day_num, day_name_heb, month_heb)
                    }

            # Detect competition names
            elif any(comp in seg for comp in COMPETITIONS):
                current_match["competition"] = translate_competition(seg)

            # Detect venue names — venues appear BEFORE team names in the HTML
            elif any(venue in seg for venue in VENUES):
                current_match["venue"] = translate_venue(seg)

            # Detect time patterns like "18:30"
            elif re.match(r"^\d{2}:\d{2}$", seg):
                current_match["time"] = seg

            # Detect score patterns like "4 - 0" or "0 - 0"
            elif re.match(r"^\d+ - \d+$", seg):
                parts = seg.split(" - ")
                current_match["home_score"] = parts[0]
                current_match["away_score"] = parts[1]
                current_match["result"] = seg

            # Detect team names — must match exactly to avoid page title confusion
            # We use exact key matching, not "contains", to prevent false positives
            elif any(seg == heb or seg.strip() == heb for heb in TEAM_NAMES):
                if "home_team" not in current_match:
                    current_match["home_team"] = translate_team(seg)
                elif "away_team" not in current_match:
                    current_match["away_team"] = translate_team(seg)

            i += 1

        # Save the last match
        if current_match and "home_team" in current_match:
            if "result" in current_match:
                past.append(current_match)
            else:
                upcoming.append(current_match)

        # Only return if we found actual match data with team names
        valid_upcoming = [m for m in upcoming if "home_team" in m and "away_team" in m]
        valid_past = [m for m in past if "home_team" in m and "away_team" in m]

        if not valid_upcoming and not valid_past:
            return None

        return {
            "next_match": valid_upcoming[0] if valid_upcoming else None,
            "upcoming": valid_upcoming[:5],
            "last_result": valid_past[-1] if valid_past else None,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "mhaifafc.com (live)",
            "method": "html_parser",
        }

    except Exception:
        return None


def _hardcoded_fallback() -> dict:
    """
    Last resort: data we already confirmed from manually reading the site.
    Clearly marked as potentially stale so the AI tells the user to verify.
    """
    return {
        "next_match": {
            "date": "Monday 2 March 2026",
            "time": "18:30",
            "home_team": "Hapoel Tel Aviv",
            "away_team": "Maccabi Haifa",
            "venue": "Bloomfield (Away)",
            "competition": "Winner League",
        },
        "upcoming": [
            {
                "date": "Monday 2 March 2026",
                "time": "18:30",
                "home_team": "Hapoel Tel Aviv",
                "away_team": "Maccabi Haifa",
                "venue": "Bloomfield (Away)",
                "competition": "Winner League",
            },
            {
                "date": "Saturday 7 March 2026",
                "time": "18:00",
                "home_team": "Maccabi Haifa",
                "away_team": "Ironi Kiryat Shmona",
                "venue": "Sami Ofer (Home)",
                "competition": "Winner League",
            },
            {
                "date": "Wednesday 18 March 2026",
                "time": "17:00",
                "home_team": "Maccabi Haifa",
                "away_team": "Maccabi Tel Aviv",
                "venue": "Sami Ofer (Home)",
                "competition": "State Cup",
            },
        ],
        "last_result": {
            "date": "Saturday 21 February 2026",
            "home_team": "Maccabi Haifa",
            "away_team": "Hapoel Petah Tikva",
            "result": "Maccabi Haifa 0 - 0 Hapoel Petah Tikva",
            "competition": "Winner League",
        },
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "mhaifafc.com (cached — verify for latest)",
        "method": "hardcoded_fallback",
        "note": "Live parsing unavailable. Data was accurate as of 24 Feb 2026.",
    }
