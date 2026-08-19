# Arsitektur ZEVORA

```text
User request + selected workspace
    ├── Workspace access policy
    └── Project discovery (frameworks, languages, manifests, files)
             ↓
Redaction → exact cache ─── HIT → final response
             ↓ MISS
Local context retrieval (knowledge + memory + project index)
             ↓
Task classification + capability detection
             ↓
Adaptive Hybrid Router (complexity × capability × cost × history)
    ├── LocalProvider: Zevora Local AI
    │     └── llama.cpp → models/zevora-4b-thinking.gguf (lazy-loaded)
    └── Cloud providers: OpenAI / Anthropic / xAI / DeepSeek / NVIDIA / Gemini
             ↓
Structured action plan → approval boundary → scoped MCP execution
             ↓
Verification → failed work requires a new approved repair action
             ↓
Quality gate → reject or retry with the next capable route
             ↓
Final response → knowledge extraction + compression + deduplication
             ↓
Cache + memory + usage + routing experience
```

## Live Workflow Contract

Chat workflow telemetry is request-scoped and canonical. The journal is shared by
SSE and incremental polling, so reconnecting with the same request ID never starts
a second execution. Events carry a monotonic sequence, UTC timestamp, request ID,
stage, normalized event type, status, bounded title, redacted message, and bounded
operational data.

The public event vocabulary covers lifecycle stages, analysis and planning,
tool/file/command activity, verification, debugging and repair, provider routing,
memory/cache/context signals, final preparation, and terminal workflow outcomes.
Telemetry is evidence of progress, not model reasoning: private chain-of-thought,
full source contents, credentials, and secret-like values are excluded or redacted.

`GET /api/chat/progress/{request_id}?after=<sequence>` returns only events after the
requested sequence while retaining the complete bounded snapshot. `/api/chat/stream`
sends the same workflow events as SSE plus structured heartbeats during idle periods.
A disconnected SSE subscriber can be cancelled without cancelling the shared task;
polling and a later SSE connection continue from the journal. Cancellation uses
`POST /api/chat/cancel/{request_id}` and records a terminal `cancelled` state.

The final assistant response is separate from Agent activity. Persisted assistant
metadata includes the final workflow snapshot, provider attribution, grounded file
receipts, and verification results for historical inspection.

## Coding Workspace Terminal

The coding workspace terminal supports multiple independent frontend tabs backed by
bounded `TerminalSessionManager` sessions. Each tab owns its command, event cursor,
output buffer, running state, and kill/clear controls so concurrent output is never
mixed between tabs.

Problems, Debug Console, and Ports panels are future work. They require real
language diagnostics, debugger integration, and port discovery/forwarding
subsystems respectively; placeholder panels are intentionally not exposed.

## Agent Flow Contract

`POST /api/task` preserves the existing response fields and adds `project_discovery`,
`context_status`, and `flow`. The context states are:

| State | Meaning |
|-------|---------|
| `CACHE_SUFFICIENT` | An exact prompt and project fingerprint match answered without inference |
| `RETRIEVAL_ENRICHED` | Local knowledge, memory, project discovery, attachments, or approved tool observations enriched the request |
| `ROUTER_REQUIRED` | No reusable local context was found, so novel inference is required |

The `flow` object reports workspace, discovery, context, route, action,
verification, and knowledge stages. A selected workspace is indexed before
planning or inference. Frameworks, languages, package manager, manifests, and a
bounded file tree are returned as `project_discovery` and included in provider
context.

For workspace requests, the gateway parses only strict structured plans. Model
prose is never executable. Approved actions run through the workspace-scoped MCP
gateway. Failed verification is recorded as `FAILED`; ZEVORA marks `FIX` as
`not_executed` and requires a new explicitly approved repair action before code
can change or verification can run again.

## Local Intelligence

ZEVORA includes a provider-agnostic local intelligence contract. The bundled
**Zevora Local AI** adapter runs GGUF through `llama-cpp-python` and llama.cpp;
Ollama and OpenAI-compatible local endpoints are separate adapters selected by
`LOCAL_MODEL_RUNTIME`. Local packages have versioned manifests, runtime/format,
compatibility, size, and SHA-256 metadata. Hardware diagnostics discover CPU,
RAM, disk, GPU/VRAM when available, and existing external models without copying
them. ZEVORA does not modify, train, or take ownership of model weights.

| Component | Purpose |
|-----------|---------|
| **Zevora Local AI** | Private on-device text generation through the bundled GGUF |
| **Exact Cache** | Return previous responses to identical prompts without inference |
| **Memory** | Conversation, project, and experience records in SQLite |
| **Experience** | Per-provider routing history; improves model selection over time |
| **Knowledge Engine** | Extracts reusable solution patterns from responses to enrich future context |
| **Project Context** | Indexed project metadata for scoped workspace operations |
| **MCP Tools** | Filesystem, Git, and terminal access scoped to the active project |

Local inference is preferred for lightweight text and coding work. Complex,
architectural, migration, multi-file, long-context, and vision tasks prefer cloud
models when available. The `LOCAL_ONLY` and `CLOUD_ONLY` modes constrain routing
explicitly. A quality rejection or provider failure advances to the next capable
candidate, allowing local-to-cloud and cloud-to-local recovery.

## Multi-provider gateway

`agent/providers/discovery.py` discovers configured providers on startup and
caches verified model metadata in `data/database/model_registry.db`. Discovery
runs once at startup; manual refresh is available via `POST /api/models/refresh`.

Provider adapters normalise health checks and errors. Built-in OpenAI-compatible adapters
cover OpenAI, xAI, NVIDIA, and DeepSeek. Anthropic and Gemini have dedicated
adapters because their APIs differ. Unknown capabilities and pricing are stored
as `unknown`, not inferred.

Adding a new custom OpenAI-compatible provider is fully supported through configuration:
Simply add it to `config/providers.json` under `custom_providers`. It will be automatically
discovered, scored, and routed without requiring code changes.

## Routing

`AdaptiveHybridRouter` keeps local and cloud candidate pools while preserving the
provider registry and model metadata contracts. In `AUTO` mode it orders local
models first for routine work and cloud models first for complex or vision work.
`LOCAL_ONLY` and `CLOUD_ONLY` restrict the candidate pool but do not change
ZEVORA's intrinsic hybrid architecture. A model is eligible only when health,
availability, explicit capabilities, required tool support, context window,
local installation state, and package compatibility allow it. Ranking combines
capability quality, estimated input/output cost, mature success/quality/latency
history, provider priority, and configured defaults.

The gateway quality-checks each response. A rejected response or provider error
is recorded in the fallback trace and advances to the next capable candidate.
`CLOUD_FALLBACK` controls whether additional candidates are attempted after the
first route.

## MCP tool gateway

`agent/tools/mcp_gateway.py` is the constrained boundary for local project
actions. It scopes filesystem, terminal, and Git operations to the selected
project. Read-only operations follow workspace preferences; mutations and risky
commands require explicit approval. Approval may be granted once or for the
current session, while denial remains authoritative. Paths outside the selected
workspace are blocked even when an action carries `approved=true`; they must be
handled by selecting another workspace rather than bypassing the boundary. See
[MCP_TOOLS.md](docs/MCP_TOOLS.md).

Successful actions produce authoritative observations and, for mutations, a
local receipt without calling an inference provider. Final provider responses and
mutation receipts are compressed into bounded knowledge records. Normalized
problem hashes merge duplicates and reuse increases hit counts, while retention
removes only expired low-value records.

## Skills, Evolution, And Updates

The bounded OpenClaw source remains read-only and allowlisted. The versioned
Skill Registry stores normalized metadata and bounded instructions in SQLite,
loads relevant skills on demand, and excludes untrusted/rejected skills. Skill
tool requirements are declarations only; all execution remains under MCP
permissions and approval gates.

The Evolution Engine consumes compact structured experiences, not raw prompts.
Promotion requires successful, verified, repeated observations and explicit
approval for evolved skills. Model evolution is limited to privacy-reviewed
training candidates for optional future LoRA/QLoRA/fine-tuning; live weights are
never changed per task.

Collective contributions require global enablement, type-specific consent,
allowlist sanitization, and explicit publication approval. The queue stores
sanitized payloads and hashes only.

The verified updater accepts HTTPS or local file components, checks compatibility,
size, SHA-256, and traversal-free destinations, then stages and atomically
activates with backups and rollback. It never executes downloaded artifacts.

`GET /api/evolution/status`, `zevora intelligence`, and the Local Intelligence
page expose bounded model, skill, evolution, collective, and update status.

## Implementation status

| Phase | Status |
|-------|--------|
| Gateway, local/cloud providers, cache, memory, experience, project discovery | Implemented |
| Provider-agnostic local adapters, packages, registry, and hardware diagnostics | Implemented |
| Adaptive hybrid routing with context/tools/cost/quality/history gates | Implemented |
| Approval-gated planning, MCP execution, observations, and verification | Implemented |
| Flow telemetry, context economy, and chat metadata persistence | Implemented |
| Knowledge extraction, bounded compression, deduplication, and pruning | Implemented |
| Dynamic skills, validated evolution, consented contributions, and training candidates | Implemented |
| Verified staged updates, rollback, CLI/API/UI status, and managed uninstall | Implemented |
| Semantic cache, automatic approval-safe repair planning, advanced policy routing | Planned |
| Optional future RAG, evaluation expansion, and fine-tuning workflows | Contract only |
