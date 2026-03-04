# 🧠 Second Brain Bot — Setup Guide

A personal Telegram bot that acts as a 24/7 AI assistant — thoughts, tasks, calendar, reminders, web search, voice, image analysis, and more. Routes messages between Gemini (fast/free) and Claude Sonnet (powerful/paid), with GPT-4o for vision and image generation.

---

## 📁 Project Structure

```
second-brain-bot/
├── main.py               ← Bot entry point (Telegram handlers)
├── agent.py              ← Multi-model routing + tool dispatch
├── router.py             ← Message classifier (Gemini / Claude / GPT)
├── scheduler.py          ← Reminder firing loop (60s tick)
├── web_dashboard.py      ← Flask dashboard (port 8080)
├── brainflow.py          ← Dev tool: real-time colored flow monitor
├── tools/
│   ├── thoughts.py       ← Capture & search thoughts
│   ├── tasks.py          ← To-do management
│   ├── notes.py          ← Categorized notes vault (passwords/keys/api/random)
│   ├── reminders.py      ← Set/list/cancel reminders
│   ├── search.py         ← Weather + web search
│   ├── maps.py           ← Google Maps deep links (no API key)
│   ├── google_services.py← Calendar / Gmail / Google Tasks (OAuth)
│   ├── image_analyzer.py ← GPT-4o vision (food/plant/general)
│   ├── image_generator.py← DALL-E 3 image generation
│   ├── video_generator.py← Google Veo 3 GIF generation
│   ├── tts.py            ← OpenAI TTS voice replies (nova voice)
│   └── transcribe.py     ← faster-whisper voice transcription (local)
├── data/                 ← Auto-created; stores JSON data files
├── .env                  ← Your secret keys (YOU create this)
├── .env.example          ← Template for .env
└── requirements.txt      ← Python dependencies
```

---

## ⚙️ Setup (One-time)

### Step 1 — Install Python 3.11+
```bash
python3 --version  # confirm 3.11+
```

### Step 2 — Clone and install dependencies
```bash
git clone <repo-url> second-brain-bot
cd second-brain-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3 — Create your `.env` file
```bash
cp .env.example .env
```

Fill in `.env`:
```
TELEGRAM_BOT_TOKEN=        # from @BotFather
ALLOWED_USER_ID=           # your Telegram user ID (from @userinfobot)
ANTHROPIC_API_KEY=         # Claude — https://console.anthropic.com
GEMINI_API_KEY=            # Google AI Studio — https://aistudio.google.com
OPENAI_API_KEY=            # OpenAI — https://platform.openai.com (vision + TTS + DALL-E)
BRAVE_SEARCH_API_KEY=      # Brave Search — https://api.search.brave.com
OPENWEATHER_API_KEY=       # OpenWeatherMap — https://openweathermap.org/api
DASHBOARD_PASSWORD=        # choose any password for the web dashboard
FLASK_SECRET_KEY=          # generate: python3 -c "import secrets; print(secrets.token_hex(32))"
HOME_ADDRESS=              # your home address (used by maps tool)
USER_CITY=                 # your city for default weather (e.g. London)
```

### Step 4 — Run the bot
```bash
python3 main.py
```

---

## 💬 How to Talk to Your Bot

Speak naturally. Examples:

| What you say | What happens |
|---|---|
| `Note this: I want to rethink my morning routine` | Saves a thought |
| `Add task: Review server logs, high priority, due tomorrow` | Creates a task |
| `Mark task 3 as done` | Updates task status |
| `Remind me in 2 hours to take a break` | Sets a reminder |
| `What's on my calendar today?` | Checks Google Calendar |
| `Schedule team meeting on Friday at 2pm` | Adds calendar event |
| `What's the weather?` | Current + tomorrow forecast |
| `Search for latest AI news` | Brave web search |
| `Save note: GitHub token is abc123` (category: api) | Saves to notes vault |
| `Navigate to Ben Gurion Airport` | Google Maps deep link |
| `Make a gif of a cat playing piano` | Veo 3 animated GIF |
| `Generate image of a sunset over the sea` | DALL-E 3 image |
| *(send a photo)* | GPT-4o analysis — food / plant / general |
| *(send a voice note)* | Transcribed + answered + read back aloud |
| `Read me my tasks` | Lists tasks + speaks reply aloud |

---

## 🔄 Commands

| Command | Action |
|---|---|
| `/start` | Welcome message + clear memory |
| `/clear` | Clear conversation history |
| `/tasks` | Pending & in-progress tasks |
| `/thoughts` | 10 most recent thoughts |
| `/reminders` | Pending reminders |
| `/weather` | Current weather |
| `/status` | Services + system health |
| `/restart` | Restart all three services |
| `/shutdown` | Stop all services |

---

## 🖼 Image Analysis (GPT-4o Vision)

Send any photo to the bot. Mode auto-detected from caption keywords:

| Caption keyword | Mode | Returns |
|---|---|---|
| food, eat, calories, meal, dish | `food` | Dish name, calories, macros, key ingredients |
| plant, flower, tree, leaf, herb | `plant` | EN + Hebrew name, edible/toxic, care guide |
| *(no keyword / describe)* | `general` | Factual description of objects, colors, any text |

---

## 📂 Your Data

All data lives in `data/`:
```
data/thoughts.json   data/tasks.json    data/reminders.json
data/notes.json      data/metrics.json  data/traces.json
data/bot.log         data/history/      data/videos/
```

---

## 🔧 Dev: Real-time Flow Monitor

```bash
brainflow   # tail bot.log with colored per-request flow view
```

Shows routing decisions, tool inputs/outputs, and model timing — one line per step.

---

## ❓ Troubleshooting

**"ModuleNotFoundError"** → `pip install -r requirements.txt`
**"TELEGRAM_BOT_TOKEN is not set"** → Check your `.env` file
**Bot doesn't respond** → Check `brainstatus` — all three services should be active
**Voice not working** → `pip install faster-whisper`
**TTS not working** → Check `OPENAI_API_KEY` in `.env`
**Image analysis fails** → Check `OPENAI_API_KEY` and that `Pillow` is installed
