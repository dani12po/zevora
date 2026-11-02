<div align="center">

# ZEVORA

**Zero-External Vendor Oriented Reasoning Agent**

A self-hosted AI coding workspace that runs locally, stays private, and connects to cloud providers only when you choose to.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.2.0-orange)](pyproject.toml)

</div>

---

## What is ZEVORA?

ZEVORA is an AI coding assistant that you run on your own machine. It comes with a built-in local AI model (no API key needed), and optionally connects to cloud providers like DeepSeek, OpenAI, Anthropic, or Gemini for more complex tasks.

**Everything stays local by default** — your code, chat history, memory, and project context never leave your machine unless you explicitly configure a cloud provider.

### Key Features

- 🏠 **Local-first** — runs a bundled Llama 3 8B model via llama.cpp, no internet required
- ☁️ **Cloud-ready** — optional DeepSeek, OpenAI, Anthropic, Gemini, xAI, NVIDIA support
- 🧠 **Smart routing** — automatically picks the best model for each task (local for simple, cloud for complex)
- 📁 **Project-aware** — indexes your codebase so the AI understands your project context
- 🔒 **Privacy-first** — API keys never stored in DB, logs, or shown in UI
- 🛠️ **MCP Tools** — file read/write, terminal, git — all approval-gated
- 💾 **Memory & cache** — remembers useful patterns across sessions, avoids repeat API calls

---

## Quick Start

### Requirements

- Python **3.11, 3.12, or 3.13**
- Windows / Linux / macOS
- ~500 MB disk for the app (+ ~4.7 GB if you want the local AI model)

### 1. Clone and install

```bash
git clone https://github.com/dani12po/zevora.git
cd zevora
python bootstrap.py
```

The bootstrap script creates a virtual environment, installs dependencies, and sets up the launcher.

### 2. Start the server

```bash
zevora
```

Or if the `zevora` command is not in PATH yet:

```bash
python launcher.py
```

### 3. Open the UI

Visit **[http://127.0.0.1:7432](http://127.0.0.1:7432)** in your browser.

> ✅ That's it. ZEVORA works out of the box — no API key required for local mode.

---

## Configuration

Copy `.env.example` to `.env` and fill in only what you need:

```bash
cp .env.example .env
```

### Add a cloud provider (optional)

Open `.env` and fill in at least one API key:

```dotenv
# DeepSeek (recommended — has a free tier)
DEEPSEEK_API_KEY=sk-...
CLOUD_DEFAULT_PROVIDER=deepseek

# Or OpenAI
OPENAI_API_KEY=sk-...
CLOUD_DEFAULT_PROVIDER=openai

# Or Anthropic
ANTHROPIC_API_KEY=sk-ant-...
CLOUD_DEFAULT_PROVIDER=anthropic
```

You can also configure keys directly in the browser at **Settings → Providers**.

### Important `.env` settings

| Variable | Default | Description |
|---|---|---|
| `CLOUD_DEFAULT_PROVIDER` | `deepseek` | Which cloud provider to use by default |
| `ROUTING_MODE` | `AUTO` | `AUTO`, `LOCAL_ONLY`, or `CLOUD_ONLY` |
| `LOCAL_MODEL_ENABLED` | `true` | Enable/disable the bundled local model |
| `MAX_TOTAL_STORAGE_GB` | `10` | Storage budget for cache/memory/logs |
| `CONTEXT_MAX_TOKENS` | `12000` | Max tokens sent to the model per request |

---

## Installing the Local AI Model

The local model is optional but lets ZEVORA work fully offline.

**From the UI:**
1. Go to **Local Intelligence** in the sidebar
2. Click **Install Recommended Model**
3. Wait for the ~4.7 GB download to complete

**Requirements for local model:**
- `llama-cpp-python` (install separately — see below)
- ~4.7 GB free disk space
- ~6 GB RAM recommended

**Install llama-cpp-python on Windows (CPU):**

```powershell
.venv\Scripts\python.exe -m pip install --prefer-binary "llama-cpp-python>=0.3.14,<0.4" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

**GPU acceleration (NVIDIA CUDA):**

Set `LOCAL_MODEL_GPU_LAYERS=35` (or higher) in `.env` and install the CUDA wheel from the [llama-cpp-python releases](https://github.com/abetlen/llama-cpp-python/releases).

---

## Gateway CLI Commands

```bash
zevora start          # Start gateway in background
zevora stop           # Graceful shutdown
zevora status         # Check if running
zevora open           # Open browser
zevora intelligence   # Show local model, skills, and privacy status
zevora background     # Start and detach (runs after terminal closes)
```

---

## Supported Cloud Providers

| Provider | Free Tier | Model |
|---|---|---|
| [DeepSeek](https://platform.deepseek.com) | ✅ Yes | `deepseek-chat` |
| [Google Gemini](https://aistudio.google.com) | ✅ Yes | `gemini-2.0-flash` |
| [OpenAI](https://platform.openai.com) | ❌ No | `gpt-4o-mini` |
| [Anthropic](https://console.anthropic.com) | ❌ No | `claude-3-5-haiku-latest` |
| [xAI (Grok)](https://console.x.ai) | ❌ No | `grok-3-mini` |
| [NVIDIA NIM](https://build.nvidia.com) | ✅ Limited | `z-ai/glm-5.2` |

---

## Project Structure

```
zevora/
├── main.py                  # FastAPI gateway — all API routes
├── launcher.py              # Standalone launcher (no PATH needed)
├── bootstrap.py             # First-run setup script
├── agent/
│   ├── core/                # Chat, planning, attachments, workspace
│   ├── providers/           # DeepSeek, OpenAI, Anthropic, Gemini, etc.
│   ├── routing/             # Adaptive hybrid router
│   ├── storage/             # Cache, memory, deduplication
│   ├── tools/               # MCP tools (filesystem, terminal, git)
│   ├── evolution/           # Pattern learning and skill registry
│   └── models/              # Local model manager and registry
├── static/                  # Frontend (vanilla JS, no build step)
│   ├── app.js               # SPA router
│   ├── providers.js         # Providers page
│   ├── chat.js              # Chat interface
│   └── styles.css           # All styles
├── zevora/                  # CLI entry point and launcher
├── config/                  # Default settings (providers.json, etc.)
├── docs/                    # Extended documentation
└── tests/                   # Test suite (pytest)
```

---

## Architecture

```
Browser UI  ──→  FastAPI Gateway (main.py)
                      │
                 Agent Core
                 ├── Project Context Index
                 ├── Exact Cache (skip repeat API calls)
                 ├── Memory Store
                 └── Experience Log
                      │
            Adaptive Hybrid Router
            ├── Score by: capability · cost · latency · history
            ├── Zevora Local AI  (llama.cpp GGUF, lazy-loaded)
            └── Cloud Provider   (DeepSeek / OpenAI / Anthropic / ...)
                      │
               MCP Tools (optional, approval-gated)
               ├── Filesystem  (read / write / search)
               ├── Terminal    (execute commands)
               └── Git         (status / diff / log)
```

---

## How Routing Works

ZEVORA automatically decides which model to use for each message:

| Task type | Route |
|---|---|
| Simple Q&A, short code | 🏠 Local model first |
| Complex reasoning, architecture | ☁️ Cloud first |
| Vision / image input | ☁️ Cloud (if local doesn't support) |
| Long context (>8k tokens) | ☁️ Cloud |
| No internet / offline | 🏠 Local only |

Set `ROUTING_MODE=LOCAL_ONLY` to never call cloud, or `CLOUD_ONLY` to always use cloud.

---

## Privacy & Security

- **API keys** — stored only in `.env`, never in the database, logs, cache, or UI
- **Conversations** — stored locally in SQLite (`data/database/agent.db`)
- **Collective learning** — **disabled by default**, requires explicit opt-in per data type
- **Tool execution** — file writes, terminal commands, and git mutations require your approval
- **Custom providers** — runtime scripts are sandboxed in a subprocess, never auto-trusted

---

## Running Tests

```bash
pytest tests/
```

Or for a quick smoke test without the full suite:

```bash
python -m pytest tests/test_gateway.py tests/test_core.py -v
```

---

## Troubleshooting

**`zevora` command not found after bootstrap:**
```bash
python launcher.py
```

**Local model not loading:**
- Check `llama-cpp-python` is installed: `python -c "import llama_cpp; print('ok')"`
- Check RAM: needs ~6 GB free for the 8B model
- Go to **Local Intelligence** in the UI for detailed status

**Cloud provider returns 400 / not configured:**
- Make sure the API key is set in `.env` or via the Providers page
- Restart the server after editing `.env` (settings load at startup)
- Check **Providers** page — the status dot should be green

**Port already in use:**
```bash
zevora stop
zevora start
```

---

## Documentation

| Document | Description |
|---|---|
| [INSTALL.md](INSTALL.md) | Detailed installation guide |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and component overview |
| [docs/LEXI_LLAMA.md](docs/LEXI_LLAMA.md) | Local model setup (embedded + remote Colab) |
| [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) | Filesystem, terminal, and git tool reference |
| [docs/ADAPTIVE_ROUTING.md](docs/ADAPTIVE_ROUTING.md) | How the hybrid router selects models |
| [SECURITY.md](SECURITY.md) | Security policy and responsible disclosure |

---

## License

[MIT](LICENSE) — free to use, modify, and distribute.

---

<div align="center">
Built with FastAPI · llama.cpp · SQLite · vanilla JS
</div>
