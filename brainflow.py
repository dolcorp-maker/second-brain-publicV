#!/usr/bin/env python3
"""
brainflow.py — Real-time per-request flow monitor for Second Brain Bot.

Reads bot.log lines from stdin, shows only the flow-relevant lines with
ANSI colors. Skips everything else (HTTP noise, polling, etc.).

Usage:
    tail -f data/bot.log | python3 brainflow.py
    # Or via the alias:  brainflow
"""

import re
import sys

# ── ANSI codes ────────────────────────────────────────────────────────────────
R  = "\033[0m"      # reset
B  = "\033[1m"      # bold
DIM= "\033[2m"
W  = "\033[97m"     # bright white
C  = "\033[36m"     # cyan
Y  = "\033[33m"     # yellow
G  = "\033[32m"     # green
GR = "\033[90m"     # dark grey
RD = "\033[31m"     # red
MG = "\033[35m"     # magenta
BL = "\033[34m"     # blue
CY = "\033[96m"     # bright cyan

# ── Pattern → (color, icon, label) ───────────────────────────────────────────
# Each tuple: (regex, color, bold_icon, transform_fn_or_None)
# transform receives the re.Match and returns the display string

def _user(m):
    src  = m.group(1)   # text / voice
    text = m.group(2)
    icon = "🎙" if src == "voice" else "💬"
    return f"{icon}  {B}{W}{text}{R}"

def _photo(m):
    return f"📷  {B}{W}Photo received{R}"

def _route(m):
    decision = m.group(1)
    if "gpt" in decision:   col = CY
    elif "claude" in decision: col = MG
    elif "gemini" in decision: col = BL
    else:                       col = C
    return f"↪  {col}{B}{decision}{R}"

def _tool_in(m):
    return f"⚙  {Y}{B}{m.group(1)}{R}  {DIM}←{m.group(2)}{R}"

def _tool_ok(m):
    return f"✓  {G}{B}{m.group(1)}{R}  {DIM}{m.group(2)}{R}"

def _tool_err(m):
    return f"✗  {RD}{B}{m.group(1)}{R}  {RD}{m.group(2)}{R}"

def _claude(m):
    return f"🤖  {MG}{B}Claude{R}  {m.group(1)}"

def _gemini(m):
    return f"✦  {BL}{B}Gemini{R}  {m.group(1)}"

def _gpt(m):
    return f"🎨  {CY}{B}GPT{R}  {m.group(1)}"

def _img_a(m):
    return f"🔍  {G}image_analyzer{R}  {m.group(1)}"

def _img_g(m):
    return f"🖼  {G}image_generator{R}  {m.group(1)}"

def _tts(m):
    return f"🔊  {C}TTS{R}  {m.group(1)}"

RULES = [
    # (regex_pattern,  handler_fn)
    (r"User \d+ \[(\w+)\]: (.+)",               _user),
    (r"handle_photo.*user (\d+)",               _photo),
    (r"\[ROUTE\] (.+)",                         _route),
    (r"\[TOOL→\] (\S+) \| (.+)",               _tool_in),
    (r"\[TOOL←\] (\S+) OK \| (.+)",            _tool_ok),
    (r"\[TOOL←\] (\S+) ERROR \| (.+)",         _tool_err),
    (r"\[TOOL ERROR\] (.+)",                    lambda m: f"✗  {RD}{B}{m.group(1)}{R}"),
    (r"\[CLAUDE\] (.+)",                        _claude),
    (r"\[GEMINI\] (.+)",                        _gemini),
    (r"\[GPT\] (.+)",                           _gpt),
    (r"\[IMAGE_ANALYZER\] (.+)",               _img_a),
    (r"\[IMAGE_GEN\] (.+)",                     _img_g),
    (r"\[TTS\] (.+)",                           _tts),
]

# Pre-compile all patterns
COMPILED = [(re.compile(pat), fn) for pat, fn in RULES]

# ── Timestamp extractor ───────────────────────────────────────────────────────
TS_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})")

_last_user = False   # track if last line printed was a USER line (for blank separator)


def process_line(line: str):
    global _last_user
    line = line.rstrip()

    ts_m  = TS_RE.match(line)
    ts    = f"{DIM}{ts_m.group(1)}{R}  " if ts_m else "          "

    for pattern, handler in COMPILED:
        m = pattern.search(line)
        if m:
            # Print blank separator before each new request (USER line)
            is_user = handler is _user or handler is _photo
            if is_user and not _last_user:
                print()
            _last_user = is_user

            body = handler(m)
            print(f"{ts}{body}", flush=True)
            return

    # Skip — not a flow line


if __name__ == "__main__":
    try:
        for raw in sys.stdin:
            process_line(raw)
    except KeyboardInterrupt:
        print(f"\n{DIM}brainflow stopped{R}")
