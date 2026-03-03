# CHANGELOG — Second Brain Bot

Newest entry at the top. One section per session. Bullets only.

---

## 2026-03-03 — Bug fixes: routing, voice UX, reminders dependency, GIF collision

**`router.py` — Bug 1 (reminder routing regression):**
- Moved `list reminders`, `show reminders`, `cancel reminder`, `delete reminder` from `SIMPLE_KEYWORDS` → `FORCE_CLAUDE` — Gemini was silently failing these.
- Added missing phrases to `FORCE_CLAUDE`: `reminder in`, `add a reminder`, `new reminder`, `my reminders`.
- Removed the now-empty reminders comment line from `SIMPLE_KEYWORDS`.

**`router.py` — Bug 4 (animate not caught by early GIF check):**
- Added `animate` to the verb group in the early first-10-words GIF check.
- Before: `"animate a cat..."` matched the video keyword group but NOT the verb group → fell through to Gemini.
- After: `animate` satisfies both groups simultaneously → routes to Claude.

**`main.py` — Bug 2 (transcribing status message leaked):**
- Stored the initial "🎙️ Got your voice note, transcribing..." message as `transcribe_status`.
- All voice handler outcomes now edit `transcribe_status` in-place instead of sending new messages.
  - 10 MB guard early return → edits to "⚠️ Voice note too large..."
  - Transcription success → edits to "📝 I heard: ..."
  - Exception handler → edits to "⚠️ Trouble processing..."
- Previously: 3 separate messages appeared for every voice input; the "transcribing" message was never removed.

**`tools/reminders.py` — Bug 3 (hidden google_services dependency):**
- Inlined `_parse_date()` and `_parse_time()` directly above `parse_reminder_due()`.
- Removed `from tools.google_services import _parse_date, _parse_time` from inside `parse_reminder_due()`.
- Fix: reminder setting no longer silently breaks if `ENABLE_GOOGLE=false` or google packages aren't installed.

**`tools/video_generator.py` — Bug 5 (GIF filename collision):**
- Added `ts = int(time.time())` to filename: `{safe_name}_{ts}.gif` / `{safe_name}_{ts}.mp4`.
- Previously: same prompt (first 30 chars) overwrote the previous GIF silently.

**`tools/gif_generator.py` — Bug 6 (dead code removed):**
- Deleted `tools/gif_generator.py` — Imagen-based frame-stitching approach, superseded by `video_generator.py` (Veo 3 pipeline). Was already listed in MEMORY.md under "Removed tools — do NOT re-add".

---

## 2026-03-03 — Startup notification + log cleanup

**`main.py`:**
- Added `_send_startup_notification()` async function — on every bot boot sends `🤖 Second Brain is online — HH:MM` to the owner via `post_init` hook on `ApplicationBuilder`.
- Added `warnings.filterwarnings("ignore", FutureWarning, module="google")` at top of file — suppresses `google.api_core` Python 3.10 EOL warning (cosmetic, everything still works).
- Note: Python 3.10 loses google.api_core support 2026-10-04. Upgrade to 3.11 via deadsnakes PPA by Sep 4, 2026.

**`tools/transcribe.py`:**
- Added `os.environ.setdefault("HF_HUB_OFFLINE", "1")` before WhisperModel load — stops HuggingFace Hub from trying to write commit hash to read-only cache path, eliminating the `[Errno 30] Read-only file system` warning at startup.

---

## 2026-03-03 — GIF pipeline fixes + router hardening

**`agent.py` — GIF generation logic:**
- System prompt: replaced "NEVER call immediately / propose 2 options first" with conditional rule —
  SHORT request (<30 words) → propose A and B options first; DETAILED request (≥30 words) → call `generate_video_gif` directly. Eliminates the old flat restriction that caused Claude to stall on rich prompts.
- Added module-level `_pending_gif_path` variable + `consume_pending_gif_path()` function.
  `run_tool()` now saves the GIF path when `generate_video_gif` succeeds. Fixes the Gemini path-loss bug: Gemini tool results never enter `conversation_history`, so `_extract_gif_path()` in main.py previously found nothing and never sent the animation.

**`router.py` — GIF routing hardening:**
- Added early first-10-words check at top of `classify_message()`: any message starting with a request verb + gif/video/animation keyword → `claude-forced`, before the word-count fallback fires.
- Added patterns to `FORCE_CLAUDE`: `prepare.*gif`, `prepare.*video`, `want.*gif`, `give me.*gif`, `get me.*gif`.
- Added `r"^\s*[ab]\s*$"` and `r"^\s*[12]\s*$"` to `FORCE_CLAUDE` — single A/B/1/2 replies now route to Claude so option selection goes back to the model that proposed the options.

**`main.py` — delivery + timeout:**
- `consume_pending_gif_path()` imported from `agent` and used as fallback after `_extract_gif_path()` — catches Gemini-generated GIFs whose paths were never in history.
- Video timeout raised from 60 s → 120 s (Veo generation observed at ~54 s; 60 s was dangerously close).
- `is_video` detection: added `prepare a gif`, `prepare gif`, `want a gif`, `give me a gif`, `get me a gif` to keyword list. Any single A/B/1/2 reply unconditionally sets `is_video = True` (history scanning was unreliable — Claude's option-proposal text doesn't always mention "gif"/"video").

## 2026-03-02 — Critical bug fixes + comm_trace monitoring (Phase 1 & 2)

**Phase 1 — Critical bug fixes in `main.py`:**
- **Bug #1 — AI timeout:** wrapped `process_message` call in `asyncio.wait_for(..., timeout=60.0)`. Previously a hung Claude/Gemini API call would block the handler forever. Now times out cleanly with `⏰ Took too long, please try again.`
- **Bug #2 — Blocking transcription:** `transcribe_voice()` now runs in `asyncio.to_thread()`. Previously, faster-whisper inference (5-15s on long notes) blocked the entire event loop, freezing all Telegram updates during that window.
- **Bug #3 — Long reply crash:** added `split_long_reply()` helper. Replies exceeding Telegram's 4096-char limit now split into multiple chunks instead of raising an unhandled exception.
- **Bug #5 — Traceback logging:** all `logger.error()` calls in message and voice handlers now include `exc_info=True` — full stack traces appear in `data/bot.log` instead of just `str(e)`.
- **Bug #13 — Voice size guard:** `handle_voice()` rejects files >10 MB before downloading, protecting against oversized uploads filling disk/RAM.
- **Status message pattern:** `handle_text_input()` now sends `⏳ Processing...` (or `🎬 Generating...` for video) immediately, then edits that message with the AI reply. Eliminates the race where the user sees nothing for 10-60 seconds. All outcomes (reply, timeout, error) edit the same message — no overlapping messages.

**Phase 2 — `tools/comm_trace.py` + `/api/traces` endpoint:**
- New `tools/comm_trace.py` — lightweight per-request trace recorder. Each incoming message gets a 6-char hex `trace_id`. Records per-stage timings (`model`, `send`, `total`), request source (text/voice), message preview, and final status (`ok`/`error`/`timeout`). Persists last 100 traces to `data/traces.json` using atomic writes.
- `main.py` — wired `new_trace()`, `mark_stage()`, `finish_trace()` into `handle_text_input()`. Voice handler logs transcription duration to `bot.log`.
- `web_dashboard.py` — added `GET /api/traces` (internal only, `@login_required`) returning `data/traces.json` as JSON.

**Querying traces from the server:**
```bash
curl http://192.168.1.204:8080/api/traces | python3 -m json.tool
# See last N traces: | python3 -c "import sys,json; [print(t) for t in json.load(sys.stdin)['traces'][-5:]]"
# Filter errors:     | python3 -c "import sys,json; [print(t) for t in json.load(sys.stdin)['traces'] if t['status']!='ok']"
```

---

## 2026-02-28 — Maps address fix: dropped Nominatim, Claude builds full address

- Removed Nominatim geocoding from `tools/maps.py` — it failed on Israeli street names, Hebrew transliterations, and any address Nominatim didn't know (produced false negatives on valid addresses Google Maps handles fine)
- `tools/maps.py` is now lean: builds Google Maps deep link directly from whatever destination string Claude passes. Google Maps itself resolves typos, partial addresses, Hebrew/English natively.
- `agent.py` — rewrote `navigate_maps` tool description to instruct Claude to always build a complete address (street + city + country) before calling the tool. If parts arrive in separate messages, Claude must combine them. Defaults to Israel if country is missing. Explicitly instructs Claude to infer rather than ask.

---

## 2026-02-28 — Maps tool: added + typo fix (Nominatim geocoding)

- Added `tools/maps.py` — `navigate_maps` tool builds a Google Maps deep link for driving directions. No API key required (uses `maps.google.com/dir/` URL scheme). Defaults origin to `HOME_ADDRESS` from `.env`. Supports `arrival_time` and `departure_time` as informational fields in the reply.
- Added `HOME_ADDRESS` to `.env` — used as default navigation origin.
- `router.py` — 14 English + 10 Hebrew navigation triggers added to `FORCE_CLAUDE` list (e.g. `trip to`, `navigate to`, `directions to`, `נסיעה ל`, `ניווט ל`, `צריך להיות ב`).
- `agent.py` — `navigate_maps` tool registered in `CLAUDE_TOOLS`, `GEMINI_TOOLS`, `run_tool()` dispatch.
- **Typo fix:** `tools/maps.py` updated with `_geocode()` helper — calls Nominatim (OpenStreetMap, free, no API key, 5s timeout) to resolve destination before building URL.
  - 1 result → confident, use canonical `display_name`
  - Multiple results, top importance ≥ 2× second → confident, use top
  - Ambiguous → return top 2 options as `needs_confirmation` dict; Claude asks user to reply 1 or 2
  - No results → fall back to raw text (same as before)
- `agent.py` — updated `navigate_maps` description to instruct Claude to normalize spelling before passing destination (e.g. `"Hayfa"` → `"Haifa, Israel"`).

---

## 2026-02-28 — Dual dashboard + rate limit + reminder routing

- **Dual dashboard** — `web_dashboard.py` now serves two distinct views:
  - Internal (LAN `192.168.1.x` / `127.0.0.1`): full dashboard, no login, all panels
  - External (`secondbrainz.duckdns.org`): lite dashboard, login required, max 4 concurrent sessions, capacity page on 5th visitor
- New templates: `dashboard_external.html` (lite view), `capacity.html` (session cap page)
- New decorator `external_login_required` in `web_dashboard.py`
- **Global rate limit removed** — flask-limiter's 200/day global cap was exhausted in ~105s by kiosk polling (~115 req/min). Login endpoint still 3/min.
- **router.py** — all reminder operations moved from `SIMPLE_KEYWORDS` → `FORCE_CLAUDE` (Gemini was silently dropping complex reminder phrases)

---

## 2026-02-27 — Logging, QA & notes routing fix

- Notes retrieval ops (`my notes`, `get notes`, `show notes`, `list notes`, `my passwords`, `show passwords`, `my keys`, `my api keys`, `search notes`, `find note`) moved from `SIMPLE_KEYWORDS` → `FORCE_CLAUDE` in `router.py` — Gemini was failing to call `get_notes` and replying from thin air
- Added `RotatingFileHandler` to `main.py` — writes `data/bot.log` (5MB × 3 backups = 15MB max); silenced noisy third-party loggers (httpx, httpcore, telegram.ext, urllib3)
- Replaced all `print()` debug calls in `agent.py` with `logger.info/debug`; added structured per-request line: `[CLAUDE/GEMINI] tool=X | Nms | in=N out=N tok | Nchars`; added `[TOOL ERROR]` warning when any tool returns `{"error": ...}`
- Replaced all `print()` in `router.py` with `logger.info("[ROUTE] ...")` structured lines
- `web_dashboard.py`: `/api/log` now reads `data/bot.log` instead of running `journalctl`; added `/api/health` endpoint (checks data files readable, disk > 1GB free, log file exists)
- `templates/dashboard.html`: brightened log line colors (base `#2a4a2a` → `#4a7a5a`, ok `#3a6a4a` → `#6dba88`); terminal header updated to "BOT LOG · DATA/BOT.LOG"
- Added `qa_check.sh` — syntax-checks all 21 project `.py` files using venv Python before any deploy

---

## 2026-02-27 — Security hardening

- Locked sensitive files: `chmod 600 .env token.json credentials.json` (owner-only read)
- Fixed `/clear` command — missing `is_authorized()` check; was open to any Telegram user
- Added `flask-limiter` — login endpoint rate-limited to 5 attempts/minute (brute-force protection)
- Installed fail2ban with three jails:
  - `sshd` — blocks repeated failed SSH logins (10min ban)
  - `nginx-http-auth` — 5 failed dashboard logins → 1 hour ban
  - `nginx-botsearch` — 2 bot scan hits → 24 hour ban
- Hardened all three systemd services: added `PrivateTmp=true`, `ProtectSystem=strict`, `ProtectHome=read-only`, `ReadWritePaths=/home/master/second-brain-bot/data`, `NoNewPrivileges=true`
- Added sudoers rule: `master ALL=(ALL) NOPASSWD: /bin/systemctl restart secondbrain*, /bin/systemctl stop secondbrain*`
- Verified GitHub backup repo (`second-brain-data`) is set to private
- Added management shell aliases to `~/.bash_aliases`: `brainstatus`, `brainrestart`, `brainstop`, `brainlogs`, `braintest`, `brainban`, `brainip`, `brainbackup`, `brainenv`, `braincd`

**Security audit results:**

| Component | Status |
|-----------|--------|
| `/shutdown`, `/restart`, `/clear`, `/tasks` commands | ✅ Protected |
| `handle_message`, `handle_voice` | ✅ Protected |
| Sensitive file permissions | ✅ chmod 600 |
| Flask login brute-force | ✅ flask-limiter |
| SSH brute-force | ✅ fail2ban |
| Nginx brute-force | ✅ fail2ban |
| Systemd isolation | ✅ Hardened |
| GitHub backup repo | ✅ Private |

**Future security (optional):**
- Cloudflare Tunnel — hides home IP completely
- Encrypt JSON data at rest
- Dedicated `secondbrain` OS user (not `master`)
- 2FA on dashboard login

---

## 2026-02-27 — Bug fixes

- Fixed `web_dashboard.py` broken import block — `flask_limiter` was inside `from flask import (...)` parens, causing SyntaxError on startup → dashboard crash-loop → kiosk never opened
- Switched `/tasks`, `/thoughts`, `/reminders` commands from MarkdownV2 → Markdown v1 — `.`, `(`, `)` in user content caused `BadRequest: Can't parse entities`
- Added empty-reply guard to Claude path in `agent.py` — prevented "Message text is empty" Telegram error
- Wrapped all `tools/notes.py` functions in `try/except`; guarded `_load()` against `json.load()` returning `None`
- Tightened voice triggers in `tools/tts.py` — removed broad matches (`"tell me"`, `"say "`, `"voice"`, `"audio"`); voice reply now only on explicit phrases: "speak", "read me", "read it", "out loud", "answer with voice", "reply with voice", "voice reply"
- Fixed GIF re-attach bug in `main.py` — removed filesystem fallback in `_extract_gif_path` that attached any GIF created in last 5min to every reply; now only scans messages from the current exchange

---

## 2026-02-27 — Notes vault added

- Added `tools/notes.py` — categorized important notes store with 5 categories: passwords, keys, api, random, headlines
- 5 new tools: `save_note`, `get_notes`, `search_notes`, `update_note`, `delete_note`
- Data stored in `data/notes.json` with atomic writes
- Wired into `agent.py`: import, `CLAUDE_TOOLS`/`GEMINI_TOOLS` definitions, `run_tool()` dispatch, system prompt capabilities

---

## 2026-02-27 — Dashboard fixes

- Fixed silent JS crash in `fetchData()`: `getElementById('log-entries')` returned null (element was renamed to `terminal-log` in an earlier update) — TypeError swallowed by `catch(e) {}` blocked service, weather, and Maccabi panel updates; fixed with null guard
- Moved `bottom-panels` div outside `.layout` — was the 4th child of a 3-row CSS grid, creating an implicit row that stole height from `1fr`, clipping the STATUS panel at 100% browser zoom
- Changed `.panel-body` from `overflow: hidden` → `overflow-y: auto` with `min-height: 0` and thin scrollbar styles
- Rewrote mobile media query (`max-width: 900px`): `display: block` on `.layout` bypasses 1fr=0 issue; compact 50px header, vertical footer, top-right page-switcher, hidden heartbeat canvas, 160px terminal cap, single-column panels

---

## 2026-02 — Migration & feature sprint

- Migrated server from Raspberry Pi 3B+ (192.168.1.203) → MacBook Pro 2017 Ubuntu 22.04 (192.168.1.204)
- Added `faster-whisper` for local offline voice transcription (replaced cloud OpenAI Whisper)
- Added `tools/video_generator.py` — Google Veo 3 → MP4 → GIF pipeline, exposed as `generate_video_gif` tool
- Added reminders system: `set_reminder`, `list_reminders`, `cancel_reminder`, `scheduler.py` (60s tick, raw Telegram API)
- Added Google Calendar, Gmail, Google Tasks integration (`tools/google_services.py`, OAuth)
- Added voice output via gTTS (`tools/tts.py`)
- Built Flask dashboard with live metrics, cost analytics, architecture diagram (`web_dashboard.py`)
- Added HTTPS via Let's Encrypt + DuckDNS (`secondbrainz.duckdns.org`)
- Added password-protected login for external dashboard access
- Added GitHub auto-backup (daily 3am cron → private `second-brain-data` repo)
- Removed local `events.py` tool — all calendar operations now route through Google Calendar
- Fixed `tasks.py`: ID collision bug, atomic writes, added `delete_task`, fixed `title` field in `update_task`
- Fixed `web_dashboard.py`: removed hardcoded IP, now reads `SERVER_IP` from `.env`
- Fixed `scheduler.py`: tasks data now handles plain list format correctly
- Fixed `main.py`: GIF re-send scoped to current exchange only via `_extract_gif_path()`

---

## Earlier — Initial development

See `MEMORY.md` for full project history and architecture.

## 2026-02-27 — Reminder routing fix + dashboard polling reduction

- **router.py** — All reminder operations moved from `SIMPLE_KEYWORDS` → `FORCE_CLAUDE`:
  `remind me`, `set a reminder`, `set reminder`, `reminder for`, `reminder in`,
  `add a reminder`, `create a reminder`, `new reminder`, `list reminders`,
  `show reminders`, `my reminders`, `cancel reminder`, `delete reminder`, `remove reminder`
  — Gemini was silently dropping complex reminder phrases (e.g. "Set Reminder for tomorrow morning 11am Go to Radera" → tool="" → reminder never saved)
- **templates/dashboard.html** — Polling intervals slashed from ~115 req/min → ~13 req/min:
  | Endpoint | Before | After |
  |---|---|---|
  | `/api/system` | 2s | 10s |
  | `/api/data` | 3s | 15s |
  | `/api/brain` | 10s | 30s |
  | `/api/log` | 5s | 10s |
  | `/api/services` | 15s | 60s |
- **templates/dashboard.html** — Added ⟳ REFRESH button in header — triggers all fetches instantly on demand
- Root cause of dashboard self-throttling: flask-limiter's 200/day global limit was exhausted in ~105s by the kiosk's own polling. Polling reduction mitigates this; full fix is removing the global limit (see security hardening session)
