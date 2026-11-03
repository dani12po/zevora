<div align="center">

<img src="https://img.shields.io/badge/ZEVORA-v0.2.0-brightgreen?style=for-the-badge" alt="ZEVORA v0.2.0"/>

# ZEVORA

### Zero-External Vendor Oriented Reasoning Agent

**A self-hosted AI coding workspace that runs on your machine, keeps your data local, and connects to cloud AI only when you want it to.**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](INSTALL.md)

</div>

---

ZEVORA is a full AI coding assistant you deploy on your own machine. It ships with a bundled **Lexi Llama 3 8B** local model (no API key, no internet needed), and optionally routes to **DeepSeek, OpenAI, Anthropic, Gemini, xAI, or NVIDIA** for complex or long-context work. Your code, conversations, and project context never leave your machine unless you explicitly configure a cloud provider.

| | |
|---|---|
| 🏠 **Local-first inference** | Bundled Llama 3 8B GGUF via llama.cpp — works fully offline |
| ☁️ **Cloud provider support** | DeepSeek · OpenAI · Anthropic · Gemini · xAI · NVIDIA NIM |
| 🧠 **Adaptive hybrid router** | Auto-picks the best model per task — local for simple, cloud for complex |
| 📁 **Project context engine** | Indexes your codebase so the AI understands your files |
| 🛠️ **MCP Tools** | File read/write · Terminal · Git — all approval-gated |
| 💾 **Local memory & cache** | Remembers useful patterns across sessions, avoids repeat API calls |
| 🔒 **Privacy-first** | API keys never stored in DB, logs, or visible in the UI |
| 🖥️ **Web UI** | Clean browser interface — chat, providers, memory, router, filesystem |
| 📅 **Scheduled Tasks** | Cron-like automations — run any prompt on a schedule |
| 📱 **Telegram Bot** | Chat with ZEVORA from your phone via Telegram |

---

## Quick Install

### Windows

```powershell
git clone https://github.com/dani12po/zevora.git
cd zevora
python bootstrap.py
```

### Linux / macOS

```bash
git clone https://github.com/dani12po/zevora.git
cd zevora
python3 bootstrap.py
```

### Docker (one-liner)

```bash
docker compose up -d
```

`bootstrap.py` creates a virtual environment, installs all dependencies, and registers the `zevora` CLI command.

### Start ZEVORA

```bash
zevora
```

> If `zevora` is not in PATH yet:
> ```bash
> python launcher.py
> ```

Open **[http://127.0.0.1:7432](http://127.0.0.1:7432)** in your browser. Done.

> ✅ No API key needed for local mode. ZEVORA works out of the box.

---

## Getting Started

```bash
zevora               # Start the gateway and open the Web UI
zevora start         # Start in background
zevora stop          # Graceful shutdown
zevora status        # Check if the gateway is running
zevora open          # Open the browser
zevora intelligence  # Show local model, skills, and privacy status
zevora background    # Start and detach (keeps running after terminal closes)
```

After starting, navigate to the Web UI:

1. **Chat** — Start asking questions immediately (uses local model by default)
2. **Open a project** — Click "Open folder" to let ZEVORA read and edit your files
3. **Add a cloud provider** — Go to **Providers** → paste your API key for cloud fallback
4. **Connect Telegram** — Go to **Telegram** → paste bot token → verify → done

---

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env   # Linux / macOS
copy .env.example .env  # Windows
```

### Minimal setup — cloud provider only

```dotenv
# Pick one (or more). ZEVORA auto-detects which are configured.

# DeepSeek — recommended, has a free tier
DEEPSEEK_API_KEY=sk-...
CLOUD_DEFAULT_PROVIDER=deepseek

# OpenAI
OPENAI_API_KEY=sk-...
CLOUD_DEFAULT_PROVIDER=openai

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
CLOUD_DEFAULT_PROVIDER=anthropic

# Google Gemini — has a free tier
GEMINI_API_KEY=AI...
CLOUD_DEFAULT_PROVIDER=gemini
```

> You can also configure keys directly in the browser at **Providers** without touching `.env`.

### Key settings reference

| Variable | Default | Description |
|---|---|---|
| `CLOUD_DEFAULT_PROVIDER` | `deepseek` | Primary cloud provider when multiple are configured |
| `ROUTING_MODE` | `AUTO` | `AUTO` / `LOCAL_ONLY` / `CLOUD_ONLY` |
| `LOCAL_MODEL_ENABLED` | `true` | Enable the bundled Lexi local model |
| `CLOUD_FALLBACK` | `true` | Fall back to cloud when local model fails |
| `MAX_TOTAL_STORAGE_GB` | `10` | Storage budget for cache, memory, and logs |
| `CONTEXT_MAX_TOKENS` | `12000` | Max tokens sent per request |
| `MEMORY_ENABLED` | `true` | Persist useful patterns across sessions |
| `CACHE_ENABLED` | `true` | Skip API calls for repeated questions |

---

## Installing the Local AI Model

The local model is **optional** but lets ZEVORA work fully offline with no API costs.

**Model:** Lexi Llama 3 8B Q4\_K\_M (~4.7 GB) · **RAM needed:** ~6 GB · **Disk:** ~4.7 GB

### Step 1 — Install llama-cpp-python

**Windows (CPU, no build tools needed):**

```powershell
.venv\Scripts\python.exe -m pip install --prefer-binary "llama-cpp-python>=0.3.14,<0.4" ^
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

**Linux / macOS:**

```bash
.venv/bin/pip install "llama-cpp-python>=0.3.14,<0.4"
```

**GPU acceleration (NVIDIA CUDA):**

Set `LOCAL_MODEL_GPU_LAYERS=35` in `.env`, then:

```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

### Step 2 — Download the model

From the Web UI: **Local Intelligence** → **Install Recommended Model** → wait ~4.7 GB download.

Or from CLI:

```bash
python scripts/download_lexi.py
```

---

## Supported Cloud Providers

| Provider | Free Tier | Default Model | Get API Key |
|---|---|---|---|
| **DeepSeek** | ✅ Yes | `deepseek-chat` | [platform.deepseek.com](https://platform.deepseek.com) |
| **Google Gemini** | ✅ Yes | `gemini-2.0-flash` | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| **NVIDIA NIM** | ✅ Limited | `z-ai/glm-5.2` | [build.nvidia.com](https://build.nvidia.com) |
| **OpenAI** | ❌ Paid | `gpt-4o-mini` | [platform.openai.com](https://platform.openai.com) |
| **Anthropic** | ❌ Paid | `claude-3-5-haiku-latest` | [console.anthropic.com](https://console.anthropic.com) |
| **xAI (Grok)** | ❌ Paid | `grok-3-mini` | [console.x.ai](https://console.x.ai) |

You can also add any **OpenAI-compatible** endpoint (Ollama, LM Studio, vLLM, etc.) via **Providers → Add new provider**.

---

## Scheduled Tasks

ZEVORA has a built-in cron-like scheduler — run any prompt automatically on a schedule while the gateway is running.

**From the Web UI:** go to **Scheduled Tasks** in the sidebar.

| Schedule type | Format | Example |
|---|---|---|
| `daily` | `HH:MM` (UTC) | `08:00` |
| `weekly` | `DDD:HH:MM` (UTC) | `mon:09:00` |
| `interval` | Every N minutes | `60` |
| `once` | ISO datetime | `2026-12-01T08:00:00+00:00` |

Example use cases:
- Daily standup summary: *"Summarize what I worked on today based on recent git commits"*
- Weekly code review: *"Review the open TODOs in the project and suggest priorities"*
- Hourly health check: *"Check if there are any critical errors in the last hour's logs"*

---

## Telegram Bot

Chat with ZEVORA from your phone via Telegram — no `.env` editing required.

### Setup (2 minutes)

1. Open Telegram → search **@BotFather** → send `/newbot` → copy the token
2. Open ZEVORA **Settings** (or the **Telegram** page in the sidebar)
3. Paste the bot token → click **Generate** for the gateway token → **Save & apply**
4. Click **Verify token** to confirm the bot is reachable
5. Start the gateway process:

```bash
python scripts/telegram_gateway.py
```

6. Send `/start` to your bot in Telegram — done!

### How it works

```
Your phone (Telegram)
      ↓  long-poll
scripts/telegram_gateway.py
      ↓  POST /api/chat
ZEVORA gateway (localhost:7432)
      ↓
AI response → back to Telegram
```

- All config (bot token, gateway token, allowed users) is saved to `config/telegram.json` — no `.env` needed
- Bot token is never exposed in the UI — only shown masked
- Allowed users list restricts who can message the bot
- The gateway process can run on the same machine or a remote server/VPS

---

## MCP Tools (Agent Actions)

When you open a project folder, ZEVORA's agent can act on your files. All mutations require your explicit approval.

| Tool | Permission | Description |
|---|---|---|
| `read_file` | Auto-allow | Read any file in the project |
| `list_directory` | Auto-allow | Browse the folder structure |
| `search_files` | Auto-allow | Search file contents |
| `create_file` | ⚠️ Approval | Create a new file |
| `write_file` | ⚠️ Approval | Overwrite a file |
| `edit_file` | ⚠️ Approval | Apply a patch to a file |
| `delete_file` | ⚠️ Approval | Delete a file |
| `execute_command` | Auto-allow | Run a terminal command |
| `git` | Auto-allow | Git status, diff, log inspection |

---

## How Routing Works

| Task type | Route |
|---|---|
| Quick Q&A, short code snippets | 🏠 Local model (fast, free) |
| Complex reasoning, architecture design | ☁️ Cloud (more capable) |
| Vision / image understanding | ☁️ Cloud (local doesn't support vision) |
| Long context > 8 000 tokens | ☁️ Cloud (exceeds local context window) |
| No internet / `LOCAL_ONLY` mode | 🏠 Local only |
| `CLOUD_ONLY` mode | ☁️ Cloud always |

---

## Project Structure

```
zevora/
├── main.py                   # FastAPI gateway entry point (slim — logic in api/)
├── launcher.py               # Standalone launcher (no PATH setup needed)
├── bootstrap.py              # First-run installer
├── Dockerfile                # Container image
├── docker-compose.yml        # One-command Docker deploy
├── .env.example              # All config options with documentation
│
├── api/                      # Modular API layer
│   ├── schemas.py            # Pydantic request models
│   ├── orchestrators.py      # Chat execution logic
│   ├── routing.py            # Hybrid router candidates
│   ├── progress.py           # Workflow progress & SSE events
│   ├── helpers.py            # Shared utilities
│   └── routers/              # FastAPI routers per domain
│       ├── chatflow.py       # POST /api/chat, /api/chat/stream
│       ├── chats.py          # Conversation CRUD
│       ├── providers.py      # Provider config & manifests
│       ├── workspace.py      # Project & filesystem
│       ├── health.py         # Health, stats, settings, storage
│       ├── schedules.py      # Scheduled tasks CRUD + run-now
│       ├── telegram.py       # Telegram config, verify, test-chat
│       └── planning.py       # Agent planning
│
├── agent/
│   ├── core/                 # Chat, planning, attachments, scheduler
│   ├── providers/            # DeepSeek, OpenAI, Anthropic, Gemini, local…
│   ├── routing/              # Adaptive hybrid router
│   ├── storage/              # Cache, memory, deduplication
│   ├── tools/                # MCP tool gateway and permissions
│   ├── evolution/            # Pattern learning, skill registry
│   └── models/               # Local model manager, downloader
│
├── static/                   # Frontend — vanilla JS, zero build step
│   ├── app.js                # SPA router
│   ├── chat.js               # Chat interface and streaming
│   ├── providers.js          # Provider management
│   ├── telegram.js           # Telegram connect page
│   ├── schedules.js          # Scheduled tasks page
│   ├── settings.js           # Settings + Telegram config
│   ├── onboarding.js         # First-run wizard
│   └── styles.css            # All styles
│
├── scripts/
│   ├── telegram_gateway.py   # Standalone Telegram bot gateway process
│   └── download_lexi.py      # Download local model from CLI
│
├── config/                   # Runtime config (providers.json, telegram.json…)
├── zevora/                   # CLI entry point (`zevora` command)
├── docs/                     # Extended documentation
└── tests/                    # Pytest test suite
```

---

## System Architecture

```
  Browser (http://127.0.0.1:7432)       Telegram App
         │                                    │
         ▼                                    ▼
  FastAPI Gateway (main.py)      telegram_gateway.py (standalone)
         │                                    │
         │◄───────── POST /api/chat ──────────┘
         │
         ├── Agent Core
         │    ├── Project Context Index
         │    ├── Exact Cache
         │    ├── Memory Store
         │    ├── Scheduled Task Scheduler
         │    └── Experience Log
         │
         ├── Adaptive Hybrid Router
         │    ├── 🏠 Zevora Local AI  (llama.cpp GGUF)
         │    └── ☁️  Cloud Providers (DeepSeek / OpenAI / Anthropic / Gemini…)
         │
         └── MCP Tool Gateway (approval-gated)
              ├── Filesystem · Terminal · Git
```

---

## Running Tests

```bash
pytest tests/

# Quick smoke test
pytest tests/test_gateway.py tests/test_core.py -v
```

---

## Troubleshooting

**`zevora` command not found:**
```bash
python launcher.py
```

**Local model not loading:**
- Check: `python -c "import llama_cpp; print('ok')"`
- Need ~6 GB RAM free
- Re-run model download from **Local Intelligence** in the UI

**Chat returns 400 / provider not configured:**
- Fill in the API key in `.env` or via the **Providers** page
- Restart the server after editing `.env`
- Status dot should be green ✅

**Telegram bot not responding:**
- Check the gateway process is running: `python scripts/telegram_gateway.py`
- Verify the token at **Telegram** page → **Verify token**
- Make sure you sent `/start` to the bot in Telegram first
- Check **Telegram** page → gateway status indicator

**Port already in use:**
```bash
zevora stop && zevora start
```

**Storage budget warning:**
```dotenv
MAX_TOTAL_STORAGE_GB=10
WARNING_STORAGE_GB=8
CRITICAL_STORAGE_GB=9
```

---

## Documentation

| Doc | Description |
|---|---|
| [INSTALL.md](INSTALL.md) | Full installation guide with GPU setup |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Detailed system design and component map |
| [docs/LEXI_LLAMA.md](docs/LEXI_LLAMA.md) | Local model setup — embedded and remote (Colab/Kaggle) |
| [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) | Full MCP tool reference and permission system |
| [docs/ADAPTIVE_ROUTING.md](docs/ADAPTIVE_ROUTING.md) | How the hybrid router scores and selects models |
| [docs/WORKSPACE.md](docs/WORKSPACE.md) | Project indexing, context, and agent workspace |
| [SECURITY.md](SECURITY.md) | Security policy and responsible disclosure |
| [PROMOTION.md](PROMOTION.md) | How to share and promote ZEVORA |

---

## Privacy & Security

- **API keys** — stored only in `.env`. Never in the database, logs, or UI
- **Telegram bot token** — saved to `config/telegram.json`, never returned by any API (only masked)
- **Conversations** — stored locally in SQLite at `data/database/agent.db`
- **Collective learning** — **disabled by default**, requires explicit opt-in
- **Tool execution** — file writes, terminal commands always require your approval click
- **Custom providers** — sandboxed subprocess, never auto-trusted

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feat/your-feature`
3. Make your changes and add tests
4. Run: `pytest tests/`
5. Open a pull request

---

## License

[MIT](LICENSE) — free to use, modify, and distribute.

---

<div align="center">

Built with [FastAPI](https://fastapi.tiangolo.com) · [llama.cpp](https://github.com/ggml-org/llama.cpp) · [SQLite](https://sqlite.org) · Vanilla JS

</div>
