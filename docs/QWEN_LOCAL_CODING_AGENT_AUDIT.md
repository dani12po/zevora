# ZEVORA — Qwen Local Coding Agent Audit (HISTORICAL — superseded by Lexi)

> Historical record. The bundled local model migrated from Qwen3.8-Flash-Next
> (`unsloth/Qwen3.8-Flash-Next-GGUF`, `UD-Q4_K_XL`) to Lexi Llama 3 8B Q5_K_M
> (`bartowski/Lexi-Llama-3-8B-Uncensored-GGUF`). See `docs/LEXI_LLAMA.md` for
> the current integration. This document is kept for migration archaeology only;
> no active default path depends on Qwen.

Target upgrade: make **Qwen3.8-Flash-Next GGUF** the first-class local reasoning engine
provided through llama.cpp, while preserving ZEVORA's existing architecture.

Status: **PHASE 0 — audit complete.** No production code changed during this audit.

Implementation status: **Phases 1, 2, 5, 6, 7, and most of Phase 8 are done.**
- Phase 1: Qwen provider identity/capabilities/config (default `qwen3.8-flash-next`, quant `UD-Q4_K_XL`, repo `unsloth/Qwen3.8-Flash-Next-GGUF`, temp `.4`, max tokens `2048`).
- Phase 2: llama.cpp lifecycle (load/unload/restart/interface pointer), health, real streaming, model quant/loaded surfaced in `list_models`.
- Phase 5: model/quant-aware cache signature (`model_cache_signature`), `context_compression_enabled` honored.
- Phase 6: coding/debugging/tool tasks stay local-first below a raised complexity gate (`CODING_LOCAL_FIRST_COMPLEXITY`).
- Phase 7: `zevora local` CLI status report, `.env.example` updated.
- Phase 8: SHA-256 local-model verification (already present in the load path); cloud provider base-URL SSRF guard (`agent/providers/ssrf.py`); SECURITY.md expanded.
- Phase 10: tests added/updated (cache signature invalidation, coding local-first routing, SSRF, CLI local) — full suite green (298 passed, 1 skipped).

---

## A. Current architecture (runtime, from code)

ZEVORA is a FastAPI gateway (`main.py`, ~2300 lines) with an SSR dashboard / SPA
(`static/`) and a CLI (`zevora/cli.py`). The real runtime flow is:

```
POST /api/chat/stream (SSE)  ── /api/chat ── /api/task
        └─ _chat_request → _complete_chat_turn → task()
task():
  1. validate mode (auto|local|provider|model) + workspace
  2. project discovery + index (core/project_index.py) → context_hash fingerprint
  3. if workspace agent intent → plan_agent_actions() loop (main.py:1693)
  4. ProjectAgentExecutor.execute() applies structured AgentActions
       (UNDERSTAND→PLAN→INSPECT→RETRIEVE→REASON→ACT→OBSERVE→VERIFY)
  5. if mutations ran → authoritative _action_receipt, skip LLM
  6. exact cache lookup (Store.get_cache by sha256(prompt+context_hash))
  7. TaskClassifier + skill injection + context economy
  8. AdaptiveHybridRouter.candidates() → ordered candidate routes
  9. generation (fallback loop over candidates) → quality gate
 10. knowledge extraction, experience, evolution.observe, cache write
```

MCP tool execution is scoped by `LocalMCPGateway` rooted at the selected project
(`agent/tools/mcp_gateway.py`); permissions and approval gate mutations.

## B. Existing local AI implementation

Adapter: `agent/providers/local_provider.py` (`LocalProvider`, 285 lines) backing a
process-wide lazy singleton `_LocalRuntime`.

- **GGUF handling / llama.cpp**: `llama_cpp` imported lazily via `importlib`; loaded
  only on first `complete()` call. Loader kwargs: `model_path, n_ctx, n_gpu_layers,
  verbose`, plus `n_threads` if >0.
- **Lazy loading**: yes — first call loads; remains loaded for process lifetime.
- **Process lifecycle**: single in-process llama-cpp-python `Llama` instance, never
  unloaded (`keep_warm` always True once loaded). No `unload()`, no idle eviction.
- **Health checks**: `health_check()` only verifies `enabled && model_exists &&
  runtime==llamacpp && runtime_available` — it does NOT actually load/verify the model.
- **Model metadata**: `status()` reports model_id/path/size/context/loaded/RSS/load
  delta/load seconds. `list_models()` returns hard-coded capabilities & scores.
- **Context handling**: `n_ctx = settings.local_model_context_length` (8192 default).
- **Streaming**: `stream()` is the base-class buffered yield; **no real token
  streaming** despite `supports_streaming: True`.
- **Error handling**: `_local_failure_reason` maps exceptions to
  model_file_missing / out_of_memory / timeout / runtime_unavailable / runtime_error.
- **Unload behavior**: none (only `_RUNTIME.reset()` for tests).

Config is in `agent/config.py` (`LOCAL_MODEL_*` env). Runtime dispatch by
`LOCAL_MODEL_RUNTIME` happens in `agent/providers/registry.py` `provider_factories()`
(llamacpp → LocalProvider, ollama → OllamaLocalProvider,
openai-compatible → LocalEndpointProvider).

## C. Existing provider system

- **Registry**: `agent/models/registry.py` (SQLite `model_registry.db`), keyed
  (provider, model_id). `agent/providers/registry.py` maps factories incl. custom
  vendor manifests (`custom_providers` in providers.json).
- **Discovery**: `agent/providers/discovery.py` — runs at startup + `POST /api/models/refresh`;
  normalizes `list_models()` into `ModelMetadata` → `registry.replace_provider`.
- **Adapters**: `base.AIProvider` contract; OpenAI-compatible (OpenAI/xAI/NVIDIA/DeepSeek),
  Anthropic, Gemini, local (llamacpp/ollama/openai-compatible).
- **Capability detection**: hard-coded per model in each adapter's `list_models()`.
- **Routing**: `AdaptiveHybridRouter` (`agent/routing/hybrid_router.py`) — merges local +
  cloud pools; AUTO orders local-first below complexity .50 (or non-vision), cloud-first
  otherwise; LOCAL_ONLY / CLOUD_ONLY restrict pools. Scoring:
  `confidence*.50 + capability*.30 + priority*.20`, cost as tie-break, cold-start
  exploration (min 3 samples), default-model hard preference.
- **Quality gate**: `agent/routing/quality_gate.py`.
- **Fallback**: inline in `main.py` (fallback_trace); `CLOUD_FALLBACK` + `routing_max_attempts`.
- **Local/cloud priority**: local-first for routine coding in AUTO. Cloud-first for
  complex (.50+), vision.

Capability constants (`agent/models/capabilities.py`) flow into scoring.
`ModelMetadata` carries `version/quantization/sha256/installed` but neither router nor
cache reads them.

## D. Existing agent / tool system

- **MCP gateway** (`agent/tools/mcp_gateway.py`): tools = list_directory, read_file,
  search_files, file_exists, get_file_info (ALLOW/read); create/write/edit/delete/move/
  copy_file, create_project (APPROVAL/mutation); execute_command (risk-gated); git
  (read-only status/diff/log); package_manager (disabled).
- **Filesystem**: safe-scoped `_path()` with `.resolve()` containment (blocks traversal
  + symlink escape); search_files over rglob capped at 500.
- **Terminal**: `execute_command` allowlist only (SAFE/RESTRICTED/DANGEROUS); rejects
  shell chaining `&& || ; | > >> <`; no `shell=True` anywhere in repo; bounded output/timeout.
- **Git**: read-only only (status/diff/log); mutations need approval.
- **Approval**: `agent/tools/permissions.py` + `workspace_permissions.py` — modes
  ask/deny/session/always; DANGEROUS blocked; RESTRICTED needs approval. In-workspace
  file mutations are auto-approved on workspace selection (`workspace_filesystem`),
  outside-workspace requires approval; paths outside workspace blocked even with approval.
- **Workspace scoping**: `agent/core/workspace.py` — SQLite WAL + busy timeout + safe path
  resolution; `allowed_root` containment.
- **Mutation receipts**: `_action_receipt()` in main.py builds a factual markdown summary
  only from successful MCP observations (not model output).
- **Verification**: `execution.py` aggregates exit codes of VERIFY_TOOLS; `trace.verified =
  all(ok)`. **Repair is NOT a loop** — `MAX_REPAIR_ATTEMPTS` only records a `not_executed`
  FIX stage; repair is manual/delegated to the planner.

## E. Existing coding capability (verified from code)

| Capability | Status |
|-----------|--------|
| Inspect repositories | Yes — `project_index.py` bounded index, `inspect_project` via tools |
| Understand project structure | Yes — `discover_project` (frameworks/languages/manifests) |
| Search source code | Yes — `search_files`, token-ranked `project_context` |
| Edit files | Yes — write/edit/create/move/copy (approval-gated or workspace-auto) |
| Execute commands | Yes — allowlist only, approval for restricted |
| Run tests / builds | Partial — `npm test`, `npm run build`, `pytest` in allowlist; arbitrary commands need config |
| Inspect errors | Yes — command output / observations feed planner |
| Repair code | **No automated loop** — single-pass verify; repair requires a new approved plan |
| Verify changes | Yes, by exit code only |
| Maintain context across ops | Yes — observations accumulate into planner prompt (bounded) |

The coding loop skeleton exists (`plan_agent_actions` + `ProjectAgentExecutor`); the
model-driven autonomous repair loop and structured tool-call schema are the main gaps.

## F. Weaknesses (categorized)

### CRITICAL
1. **Cache key has no model/version dimension** (`agent/memory/store.py:102-104`).
   Swapping zevora → Qwen replays stale cached answers for an identical prompt + project
   fingerprint. Violates the "cache must not bypass model/version changes" requirement.
2. **Local provider is single hard-coded model with Zevora-4B scores**
   (`local_provider.py:218-246`): coding .68 / reasoning .72 bound the router so a modern
   Qwen gets under-prioritized; capabilities (tool_use/json) are claimed without evidence.

### HIGH
3. **`context_window` not auto-detected** — router trusts
   `settings.local_model_context_length` (8192); long-context routing to cloud even when
   Qwen supports more. No auto context from GGUF metadata.
4. **`max_output_tokens=1024`** caps structured plan / tool-call JSON output and will
   truncate verbose Qwen output.
5. **No real token streaming** despite `supports_streaming=True` (buffered `stream()`).
6. **No `unload()` / lifecycle states** — process-lifetime only; model swap needs restart;
   no stale-process/duplicate-process guard for llama-server mode.
7. **`installed_local_packages()` always empty** for the built-in GGUF — `list_models()`
   never sets `installed`, so UI/CLI report 0 even when loaded.
8. **No SHA-256 / manifest verification wired into the load path**
   (`package.verify_file` exists but is never called against the configured GGUF).

### MEDIUM
9. **Repair is not a loop** — `MAX_REPAIR_ATTEMPTS` records `not_executed` only.
10. **`context_compression_enabled` is dead config** (never read; compression always runs).
11. **Hardcoded absolute skills path** `E:\SUPERAGENT-...\openclaw\skills` (`config.py:72`).
12. **SSRF**: custom-provider base_url has no private-IP blocklist
    (`manifest_provider.py`, `openai_compatible.py`).
13. **`SECURITY.md` is a boilerplate stub** (no real policy).
14. **SPA catch-all** `/{full_path:path}` swallows invalid `/api/*` into dashboard.
15. **Task-type taxonomy mismatch** — memory/experiences use legacy `ModelRouter` labels;
    routing uses `TaskClassifier` labels.

### LOW
16. Legacy `.env` vars ignored (`LOCAL_FIRST`, `MAX_LOCAL_RETRIES`).
17. `AIProvider.get_model_info` unused; `LocalIntelligenceProvider` protocol never
    `isinstance`-checked; `fallback.py`/`scoring.py` un-referenced.
18. Token estimate is whitespace word count (`context_economy.py:13`).

## G. Qwen3.8-Flash-Next integration gaps

1. **Configurable model reference** — add `LOCAL_MODEL_REPOSITORY` / `LOCAL_MODEL_QUANT` /
   runtime/base_url/context/gpu/threads/batch/temperature; do not hardcode quant.
2. **Provider identity** — model_id should reflect Qwen (`qwen3.8-flash-next`), display
   name "Qwen3.8-Flash-Next", not "Zevora Local AI".
3. **Capability profile** — raise coding/reasoning/instruction scores for a modern
   instruct model; derive from config, don't hardcode Zevora-4B numbers.
4. **Context/lifecycle** — allow larger context; add unload/restart/health that actually
   loads; expose loaded/unloaded states, size, memory, latency, generation stats.
5. **Streaming** — implement real llama.cpp token streaming.
6. **Hardware-aware recommendation** — quant/context/GPU offload/VRAM estimate from
   `LocalIntelligenceManager.resource_state()`.
7. **Cache versioning** — include model/quant/version in cache identity.
8. **Package install** — select exactly one quant (default UD-Q4_K_XL), SHA-256 verified,
   into the managed package dir; wire `verify_file` into the load path.
9. **UI/CLI status** — surface quant, context, VRAM/RAM, loaded state, mode.

## H. Recommended implementation plan (phased)

**Phase 1 — Qwen provider integration (config + identity + capabilities).**
Add `LOCAL_MODEL_REPOSITORY`, `LOCAL_MODEL_QUANT`, `LOCAL_MODEL_BASE_URL`,
`LOCAL_MODEL_BATCH_SIZE`, `LOCAL_MODEL_*`. Make local model reference configurable.
Update display name/model_id/capability profile. Safe defaults; future quants without
provider rewrite.

**Phase 2 — llama.cpp lifecycle + health.**
Add explicit lifecycle states & `unload()`/`restart()`; health() that loads; expose
quant/context/size/memory/latency/generation stats; lock against duplicate processes.

**Phase 3 — structured tool calling + coding loop.**
Strict `{type, tool, arguments}` / `{type:plan}` / `{type:final}` contract, validated
before execution; never execute raw prose. Strengthen plan parsing.

**Phase 4 — verification + repair.**
Turn `MAX_REPAIR_ATTEMPTS` into a bounded repair loop: collect error → locate source →
repair plan → approval → apply → re-verify; respect `MAX_REPAIR_ATTEMPTS`.

**Phase 5 — context/cache.**
Model/version-aware cache key; honor `context_compression_enabled`; auto context window.

**Phase 6 — routing.**
Local-first priority for coding/explain/debug/refactor/tests/CSS/frontend/scripts/repo
inspection; cloud for large migrations/vision/hard architecture; keep AUTO/LOCAL_ONLY/
CLOUD_ONLY; record provider_selected/fallback_reason.

**Phase 7 — UI/CLI local intelligence controls.**
Local model status card (Qwen, GGUF, llama.cpp, READY/LOADING/ERROR, quant, context,
VRAM/RAM, mode); CLI `zevora local status/start/stop/restart/health/model/install`.

**Phase 8 — security hardening.**
Wire SHA-256/manifest check into load+install; SSRF private-IP blocklist; replace
SECURITY.md stub; strict prompt-injection hierarchy; keep prompt-injection defenses.

**Phase 9 — tests + docs.**
Unit/integration: provider init/health/streaming/timeout/unload/restart; tool call
valid/malformed/unknown/unauthorized/workspace-violation; coding loop plan→approve→edit→
verify→repair→max-repair; router local-first/local-only/cloud-only/fallback/capability/
context mismatch; security path-traversal/symlink/command-injection/redaction/prompt-
injection. Update README/INSTALL/ARCHITECTURE/SECURITY/.env.example.

---

## Cross-cutting rules for implementation
- Preserve existing abstractions (`AIProvider`, `AdaptiveHybridRouter`, MCP gateway,
  approval, SQLite store, workflow journal). Reuse; do not fork.
- No `shell=True`; model prose is never executed; structured output is validated.
- Workspace boundary remains authoritative; approval never bypasses workspace.
- Do not silently download whole HF repos — select exactly one quant.
- Telemetry stays redacted (no chain-of-thought, no secrets).
- Run the full test suite after each phase; fix regressions before continuing.
