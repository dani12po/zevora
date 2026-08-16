# ZEVORA

**Zero-External Vendor Oriented Reasoning Agent** — a hybrid AI coding workspace
with a private local GGUF model and optional cloud providers. Memory, cache,
experience, and project context remain local.

The bundled `Zevora Local AI` runtime uses llama.cpp and needs no API key or
internet connection. Cloud providers extend capacity for complex, multimodal,
and long-context work.

## Quick Start

```powershell
git clone <ZEVORA_GITHUB_REPOSITORY>
cd ZEVORA
python bootstrap.py
zevora
```

Open `http://127.0.0.1:7432` in your browser. The bundled local model is
available without a key; add a cloud API key in **Providers** for cloud-first
complex tasks and fallback capacity.

## Architecture

```
User
 ↓
ZEVORA Web UI  (http://127.0.0.1:7432)
 ↓
Gateway (FastAPI)
 ↓
Agent Core
 ├── Local Intelligence Layer
 │   ├── Exact Cache         ← avoids repeat API calls
 │   ├── Memory              ← conversation + project knowledge
 │   ├── Experience          ← routing improvement over time
 │   ├── Knowledge Engine    ← extracts reusable solution patterns
 │   └── Project Context     ← indexed workspace metadata
 ↓
Adaptive Hybrid Router  ← capability · cost · history · task complexity
  ├── Zevora Local AI  ← bundled GGUF via llama.cpp, lazy-loaded
  └── Cloud AI Provider  ← OpenAI · Anthropic · xAI · DeepSeek · NVIDIA · Gemini
 ↓
MCP Tools (optional)  ← Filesystem · Git · Terminal (approval-gated)
```

## Gateway Controller

```
zevora start       # start gateway in background
zevora stop        # graceful shutdown
zevora status      # check if running
zevora open        # open browser
zevora background  # start + detach
```

## Configuration

All settings live in `.env`. Copy `.env.example` to get started.
API keys are **never** stored in the database, logs, or shown in the UI.

See [INSTALL.md](INSTALL.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Local And Cloud Inference

`Zevora Local AI` is the product identity presented by ZEVORA around the
bundled GGUF. The underlying weights are not modified or falsely attributed to
ZEVORA. The model loads lazily on first local generation, and the Providers
page reports loaded state, process RSS, model size, context, and load delta.

AUTO routes lightweight work local-first and complex, architecture, migration,
vision, and long-context work cloud-first. A failed or quality-rejected local
response tries cloud next; a failed cloud response tries local when capable.

## What "Local Intelligence" means

ZEVORA's local data layer remains:

- **Cache** — avoids calling the API for repeated questions
- **Memory** — stores useful patterns from past sessions
- **Experience** — improves provider selection based on what worked before
- **Knowledge Engine** — extracts reusable solution patterns from API responses to enrich future context
- **Project context** — indexes your codebase so only relevant files are sent

The local model and cloud providers share the same `AIProvider`, registry,
discovery, router, quality gate, and fallback execution path.

## Offline Capabilities (No API Key)

Without a cloud key configured, ZEVORA can still:

- Index and browse projects
- Read and search the filesystem
- Show memory, cache, and usage history
- Display routing decisions (without executing them)

It will use the local model when the llama.cpp dependency and bundled GGUF are
available, and clearly report local runtime readiness when they are not.
