#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  Second Brain Bot — Setup Script
#  Run this once on a fresh clone to install everything and configure .env.
#  Usage: bash setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'  # No Color

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
hdr()  { echo -e "\n${BOLD}${CYAN}── $1 ──${NC}"; }

echo -e "${BOLD}"
echo "╔═══════════════════════════════════════╗"
echo "║     Second Brain Bot — Setup          ║"
echo "╚═══════════════════════════════════════╝"
echo -e "${NC}"

# Safety check — must come before any steps that touch .env
ENV_EXISTS=false
if [ -f ".env" ]; then
    warn ".env already exists — skipping copy to avoid overwriting your config."
    ENV_EXISTS=true
fi


# ── 1. System dependencies ────────────────────────────────────────────────────
hdr "System dependencies"

if ! command -v python3 &>/dev/null; then
    err "python3 is not installed. Install it with: sudo apt install python3"
    exit 1
fi
ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"

# Read feature flags from .env.example to decide what system deps to install
_get_flag() {
    local key="$1"
    local default="${2:-true}"
    if [ -f .env ]; then
        local val; val=$(grep -E "^${key}=" .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')
        [ -n "$val" ] && echo "$val" || echo "$default"
    else
        echo "$default"
    fi
}

ENABLE_VOICE=$(_get_flag "ENABLE_VOICE")

if [ "$ENABLE_VOICE" = "true" ]; then
    if ! command -v ffmpeg &>/dev/null; then
        echo "  Installing ffmpeg..."
        sudo apt-get install -y ffmpeg
        ok "ffmpeg installed"
    else
        ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
    fi
else
    warn "ENABLE_VOICE=false — skipping ffmpeg install"
fi


# ── 2. Python virtual environment ─────────────────────────────────────────────
hdr "Python virtual environment"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    ok "venv created"
else
    ok "venv already exists"
fi

source venv/bin/activate
ok "venv activated: $(python --version)"

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Python dependencies installed"

if [ "$ENABLE_VOICE" = "true" ]; then
    echo "  Installing faster-whisper..."
    pip install --quiet faster-whisper
    ok "faster-whisper installed"
    echo "  Downloading Whisper base model (first run only, ~150 MB)..."
    python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" && ok "Whisper base model ready"
else
    warn "ENABLE_VOICE=false — skipping faster-whisper and Whisper model"
fi


# ── 3. Environment configuration ──────────────────────────────────────────────
hdr "Environment configuration"

if [ "$ENV_EXISTS" = "true" ]; then
    : # warning already shown at startup
else
    cp .env.example .env
    ok ".env.example → .env"
fi

echo ""
echo -e "${BOLD}Open .env and fill in your values. Here's what you need:${NC}"
echo ""
echo -e "${BOLD}REQUIRED — bot will not start without these:${NC}"
echo "  TELEGRAM_BOT_TOKEN   → @BotFather on Telegram"
echo "  ALLOWED_USER_ID      → message @userinfobot on Telegram to get your ID"
echo "  ANTHROPIC_API_KEY    → https://console.anthropic.com/"
echo "  GEMINI_API_KEY       → https://aistudio.google.com/app/apikey"
echo "  DASHBOARD_PASSWORD   → choose any password"
echo "  FLASK_SECRET_KEY     → run: python3 -c \"import secrets; print(secrets.token_hex(32))\""
echo "  SERVER_IP            → run: hostname -I | awk '{print \$1}'"
echo ""
echo -e "${BOLD}PERSONALISATION:${NC}"
echo "  TIMEZONE             → your timezone, e.g. America/New_York"
echo "  USER_CITY            → your city for /weather, e.g. New York"
echo "  HOME_ADDRESS         → your home address for Maps navigation"
echo ""

ENABLE_GOOGLE=$(_get_flag "ENABLE_GOOGLE")
ENABLE_MACCABI=$(_get_flag "ENABLE_MACCABI")
ENABLE_VIDEO=$(_get_flag "ENABLE_VIDEO")

echo -e "${BOLD}OPTIONAL (based on your feature flags):${NC}"
if [ "$ENABLE_GOOGLE" = "true" ]; then
    echo "  ENABLE_GOOGLE=true  → You need credentials.json from Google Cloud Console."
    echo "    • Go to https://console.cloud.google.com/"
    echo "    • APIs & Services → Enable: Calendar API, Gmail API, Tasks API"
    echo "    • Credentials → OAuth 2.0 Client ID → Desktop → Download JSON"
    echo "    • Save as credentials.json in this directory, then run:"
    echo "      python3 authorize_google.py"
else
    warn "ENABLE_GOOGLE=false — skipping Google OAuth setup"
fi

if [ "$ENABLE_VOICE" = "true" ]; then
    echo "  ENABLE_VOICE=true   → No extra API keys needed (faster-whisper is local)."
    echo "    • Optional fallback: OPENAI_API_KEY for cloud Whisper if local fails."
fi

if [ "$ENABLE_MACCABI" = "true" ]; then
    echo "  ENABLE_MACCABI=true → No API keys needed (scrapes mhaifafc.com directly)."
fi

if [ "$ENABLE_VIDEO" = "true" ]; then
    echo "  ENABLE_VIDEO=true   → Uses GEMINI_API_KEY (already listed above)."
    echo "                        Requires BRAVE_SEARCH_API_KEY and OPENWEATHER_API_KEY."
fi

echo ""
echo -e "${BOLD}  BRAVE_SEARCH_API_KEY  → https://brave.com/search/api/ (free tier available)${NC}"
echo -e "${BOLD}  OPENWEATHER_API_KEY   → https://openweathermap.org/api (free tier available)${NC}"


# ── 4. Data directory structure ───────────────────────────────────────────────
hdr "Data directory structure"

mkdir -p data/voice data/videos data/gifs data/history
ok "data/ subdirectories ready"


# ── 5. Health check ───────────────────────────────────────────────────────────
hdr "Health check"

echo "  Checking Python syntax of core files..."
if python3 -m py_compile main.py agent.py router.py scheduler.py web_dashboard.py 2>&1; then
    ok "All core files pass syntax check"
else
    err "Syntax errors found — check the files above before running."
    exit 1
fi

if [ ! -f ".env" ] || grep -q "^TELEGRAM_BOT_TOKEN=$" .env 2>/dev/null; then
    warn "TELEGRAM_BOT_TOKEN is not set — fill in .env before starting the bot."
fi


# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env and fill in all required values (see above)"
if [ "$ENABLE_GOOGLE" = "true" ]; then
    echo "  2. Place credentials.json in this directory"
    echo "  3. Run: source venv/bin/activate && python3 authorize_google.py"
    echo "  4. Run: source venv/bin/activate && python3 main.py"
else
    echo "  2. Run: source venv/bin/activate && python3 main.py"
fi
echo ""
echo "  For 24/7 operation, install systemd services (see README.md)."
echo ""
