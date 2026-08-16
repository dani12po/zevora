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
zevora intelligence # local model, skills, evolution, and privacy status
zevora open        # open browser
zevora background  # start + detach
zevora uninstall-local # preview managed package removal
zevora uninstall-local --approve # remove only the managed local package
```

`uninstall-local` never removes externally configured GGUF files. The command and
`POST /api/local-intelligence/uninstall` are dry-run by default and require explicit
approval for deletion.

## Configuration

All settings live in `.env`. Copy `.env.example` to get started.
API keys are **never** stored in the database, logs, or shown in the UI.

See [INSTALL.md](INSTALL.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Custom AI Providers

The Providers page can register user-controlled OpenAI-compatible,
Anthropic-compatible, generic HTTP REST, local OpenAI-compatible, and custom
runtime providers. Standard providers need a base URL, model, and optional
credential environment name. They enter the same registry, discovery, router,
quality, and fallback path as built-in providers.

Paste a Python, Node.js, TypeScript, shell, or cURL example into the provider
source editor and select **Analyze**. Static analysis extracts recognized URLs,
models, credential references, request options, headers, and protocol metadata
without executing the source. Dynamic authentication or custom SDK logic is
classified as a custom runtime instead of being silently executed.

Provider manifests store credential references, never credential values. Values
are resolved only when a request executes and public API responses and exports
contain configuration status plus a masked suffix. Custom headers may reference
only the manifest's declared credential using `${CREDENTIAL_NAME}`.

Custom runtime scripts execute in a temporary working directory and a separate
process with JSON-lines IPC, bounded time, output, temporary disk, and
concurrency. They do not receive the workspace path or inherited environment.
A one-time test requires explicit approval; normal routing requires the provider
to be explicitly trusted, and changing its source revokes that trust. This is
not an OS sandbox: approved code retains the host process user's filesystem and
network privileges, so only review and trust code from known sources.

Useful CLI operations include:

```powershell
zevora provider list
zevora provider add --id my-provider --name "My Provider" --protocol openai-compatible --base-url https://api.example.test/v1 --model example-model
zevora provider import provider.json
zevora provider test my-provider
zevora provider runtime-test my-runtime --approve
zevora provider export my-provider --output provider.export.json
```

The equivalent management API is available under `/api/provider-manifests`.
The dashboard's Analyze action handles source inspection, while runtime trust is
performed through the dashboard confirmation flow or the API trust endpoint.

## Local And Cloud Inference

`Zevora Local AI` is the product identity presented by ZEVORA around the
bundled GGUF. The underlying weights are not modified or falsely attributed to
ZEVORA. The model loads lazily on first local generation, and the Providers
page reports loaded state, process RSS, model size, context, and load delta.

AUTO routes lightweight work local-first and complex, architecture, migration,
vision, and long-context work cloud-first. Candidate eligibility also checks the
estimated context window, explicit required tools, installed package state,
verified health, compatibility, cost, and mature success/quality/latency history.
A failed or quality-rejected local response tries cloud next; a failed cloud
response tries local when capable.

## What "Local Intelligence" means

ZEVORA's local data layer remains:

- **Cache** — avoids calling the API for repeated questions
- **Memory** — stores useful patterns from past sessions
- **Experience** — improves provider selection based on what worked before
- **Knowledge Engine** — extracts reusable solution patterns from API responses to enrich future context
- **Project context** — indexes your codebase so only relevant files are sent

The local model and cloud providers share the same `AIProvider`, registry,
discovery, router, quality gate, and fallback execution path.

## Continuous Improvement And Privacy

The Skill Registry loads only bounded, trusted or verified skills on demand.
Evolution stores compact structured outcomes, requires repeated verified quality
before promotion, and creates future training candidates without modifying model
weights after user tasks. Collective learning is disabled by default, requires
per-type consent, sanitizes allowlisted payloads, and requires separate approval
before publishing. API keys, prompts, full conversations, and private paths are
not contribution data.

Updates use HTTPS or local files, SHA-256 verification, staging, atomic activation,
backups, compatibility checks, and rollback. GitHub or another registry is a
release/source location, never a raw user database.

## Offline Capabilities (No API Key)

Without a cloud key configured, ZEVORA can still:

- Index and browse projects
- Read and search the filesystem
- Show memory, cache, and usage history
- Display routing decisions (without executing them)

It will use the local model when the llama.cpp dependency and bundled GGUF are
available, and clearly report local runtime readiness when they are not.
