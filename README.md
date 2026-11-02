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
| 🛠️ **MCP Tools** | File read/write · Terminal · Git — all approval-gated, never runs without you |
| 💾 **Local memory & cache** | Remembers useful patterns across sessions, avoids repeat API calls |
| 🔒 **Privacy-first** | API keys never stored in DB, logs, or visible in the UI |
| 🖥️ **Web UI** | Clean browser interface — chat, providers, memory, router, filesystem |

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

`bootstrap.py` creates a virtual environment, installs all dependencies, and registers the `zevora` CLI command.

### Start ZEVORA

```bash
zevora
```

> If `zevora` is not in PATH yet (common on Windows before restarting the terminal):
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

After starting, navigate to the Web UI and:

1. **Chat** — Start asking questions immediately (uses local model by default)
2. **Open a project** — Click "Open folder" to let ZEVORA read and edit your files
3. **Add a cloud provider** — Go to **Providers** → paste your API key for cloud fallback

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

**Model:** Lexi Llama 3 8B Q4\_K\_M (~4.7 GB)
**RAM needed:** ~6 GB free
**Disk needed:** ~4.7 GB

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

Set `LOCAL_MODEL_GPU_LAYERS=35` in `.env`, then install the CUDA wheel:

```bash
# Replace cu121 with your CUDA version (cu118, cu121, cu122, cu123...)
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

### Step 2 — Download the model

**From the Web UI:**
1. Open **Local Intelligence** in the sidebar
2. Click **Install Recommended Model**
3. Wait for the ~4.7 GB download to finish

**From the CLI:**

```bash
python scripts/download_lexi.py
```

### Step 3 — Verify it's loaded

Go to **Providers** in the UI — the Zevora Local AI card should show **loaded** with a green dot.

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

## How Routing Works

ZEVORA's adaptive hybrid router automatically selects the best model for each request:

| Task type | Route |
|---|---|
| Quick Q&A, short code snippets | 🏠 Local model (fast, free) |
| Complex reasoning, architecture design | ☁️ Cloud (more capable) |
| Vision / image understanding | ☁️ Cloud (local doesn't support vision) |
| Long context > 8 000 tokens | ☁️ Cloud (exceeds local context window) |
| No internet / `LOCAL_ONLY` mode | 🏠 Local only |
| `CLOUD_ONLY` mode | ☁️ Cloud always |

The router also considers: provider health history, cost, latency, task complexity score, and whether the request needs specific tools.

---

## MCP Tools (Agent Actions)

When you open a project folder, ZEVORA's agent can act on your files. All mutations require your explicit approval before they execute.

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

Change permissions in the **MCP Tools** page in the UI.

---

## Project Structure

```
zevora/
├── main.py                   # FastAPI gateway — all API routes live here
├── launcher.py               # Standalone launcher (no PATH setup needed)
├── bootstrap.py              # First-run installer
├── .env.example              # All config options with documentation
│
├── agent/
│   ├── core/                 # Chat execution, planning, attachments, workspace
│   ├── providers/            # DeepSeek, OpenAI, Anthropic, Gemini, local, etc.
│   ├── routing/              # Adaptive hybrid router and model selector
│   ├── storage/              # Cache, memory, deduplication, compression
│   ├── tools/                # MCP tool gateway and permissions
│   ├── evolution/            # Pattern learning, skill registry, knowledge engine
│   └── models/               # Local model manager, downloader, registry
│
├── static/                   # Frontend — vanilla JS, zero build step required
│   ├── app.js                # SPA router and page loader
│   ├── chat.js               # Chat interface and streaming
│   ├── providers.js          # Provider management UI
│   ├── local-ai.js           # Local model install and status
│   └── styles.css            # All styles (single file)
│
├── zevora/                   # CLI entry point (`zevora` command)
├── config/                   # Default provider config and UI settings
├── docs/                     # Extended documentation
├── scripts/                  # Utility scripts (model download, version bump)
└── tests/                    # Pytest test suite
```

---

## System Architecture

```
  Browser (http://127.0.0.1:7432)
        │
        ▼
  FastAPI Gateway (main.py)
        │
        ├─── Agent Core
        │     ├── Project Context Index  (indexes codebase for retrieval)
        │     ├── Exact Cache            (skips API calls for repeated questions)
        │     ├── Memory Store           (persists patterns across sessions)
        │     └── Experience Log         (tracks routing performance over time)
        │
        ├─── Adaptive Hybrid Router
        │     ├── Scores by: capability · cost · latency · task complexity
        │     ├── 🏠 Zevora Local AI     (llama.cpp GGUF, lazy-loaded on first use)
        │     └── ☁️  Cloud Providers    (DeepSeek / OpenAI / Anthropic / Gemini / ...)
        │
        └─── MCP Tool Gateway (approval-gated)
              ├── Filesystem  (read / write / search / delete)
              ├── Terminal    (execute shell commands)
              └── Git         (status / diff / log)
```

---

## Custom Providers

Connect any OpenAI-compatible endpoint (local or cloud) via **Providers → Add new provider**:

1. Enter a short **ID** (e.g. `my-ollama`)
2. Set **Protocol** to `openai-compatible`
3. Enter the **Base URL** (e.g. `http://localhost:11434/v1`)
4. Enter the **Default Model** (e.g. `llama3`)
5. Click **Save provider** then **Test connection**

The provider enters the same routing pool as built-in providers — ZEVORA will use it automatically.

**CLI equivalent:**

```bash
zevora provider add \
  --id my-provider \
  --name "My Provider" \
  --protocol openai-compatible \
  --base-url https://api.example.com/v1 \
  --model my-model
```

---

## Running Tests

```bash
# Full test suite
pytest tests/

# Quick smoke test
pytest tests/test_gateway.py tests/test_core.py -v

# Skip tests that require a live model
pytest tests/ -k "not local_model"
```

---

## Troubleshooting

**`zevora` command not found after bootstrap:**
```bash
python launcher.py
# or restart the terminal and try again
```

**Local model not loading — stays `NOT_INSTALLED`:**
- Verify `llama-cpp-python` is installed: `python -c "import llama_cpp; print('ok')"`
- Check you have ~6 GB RAM free
- Re-run the model download from **Local Intelligence** in the UI

**Chat returns 400 / provider not configured:**
- Make sure the API key is filled in `.env` (not just the example file)
- **Restart the server** after editing `.env` — settings are read at startup
- Check the Providers page — the status dot should be green ✅

**Port 7432 already in use:**
```bash
zevora stop
zevora start
```

**RAM is too full to load the local model:**

Set `ROUTING_MODE=CLOUD_ONLY` in `.env` to skip local model entirely and use only cloud providers.

**`storage budget > disk space` warning:**

Lower `MAX_TOTAL_STORAGE_GB` in `.env` to match your available disk:
```dotenv
MAX_TOTAL_STORAGE_GB=10
WARNING_STORAGE_GB=8
CRITICAL_STORAGE_GB=9
```

---

## Privacy & Security

- **API keys** — stored only in `.env`. Never written to the database, logs, cache, or shown anywhere in the UI.
- **Conversations** — stored locally in SQLite at `data/database/agent.db`. Never sent anywhere.
- **Collective learning** — **disabled by default**. Requires explicit opt-in per data type in `.env`.
- **Tool execution** — file writes, terminal commands, and mutations always require your approval click before running.
- **Custom runtime providers** — execute in a sandboxed subprocess. Auto-trust is never granted; you must explicitly trust after reviewing the source.

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
| [docs/STORAGE_POLICY.md](docs/STORAGE_POLICY.md) | Cache, memory, retention, and storage budget |
| [SECURITY.md](SECURITY.md) | Security policy and responsible disclosure |

---

## Contributing

Contributions are welcome. Open an issue first for significant changes so we can discuss direction before you build.

1. Fork the repo
2. Create a branch: `git checkout -b feat/your-feature`
3. Make your changes and add tests
4. Run the test suite: `pytest tests/`
5. Open a pull request

---

## License

[MIT](LICENSE) — free to use, modify, and distribute.

---

<div align="center">

Built with [FastAPI](https://fastapi.tiangolo.com) · [llama.cpp](https://github.com/ggml-org/llama.cpp) · [SQLite](https://sqlite.org) · Vanilla JS

</div>
