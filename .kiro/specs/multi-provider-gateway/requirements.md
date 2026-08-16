# Requirements Document

## Introduction

ZEVORA's AI inference layer must be fully provider-agnostic. Given only API keys
in `.env`, the system discovers providers, discovers their models, detects
capabilities, scores candidates per-task, executes with fallback chains, and
improves routing from historical performance — with zero provider-specific code
in the Agent Core.

This document formalizes the correctness properties for the Multi-Provider AI
Gateway feature, based on the existing codebase at `E:\Storage AI\AI-Agent`
and the architectural intent described by the project owner.

## Current State vs Target

### Already implemented ✅
- `AIProvider` ABC with `complete()`, `health_check()`, `list_models()`
- `OpenAICompatibleProvider` (used by openai, xai, nvidia, deepseek)
- `AnthropicProvider`, `GeminiProvider`, `OllamaProvider`
- `ModelRegistry` (SQLite-backed, `upsert` / `list` / `replace_provider`)
- `ModelMetadata` dataclass with full field set
- Capability constants in `capabilities.py`
- `ProviderDiscovery` — startup health check + model list
- `AdaptiveHybridRouter` — local-first with cloud fallback
- `TaskClassifier` — keyword-based classification
- `ModelSelector` — capability-filtered candidate scoring
- `scoring.py` — `score_model()` with configurable dimensions
- `fallback.py` — `with_fallback()` iterates capability-filtered candidates
- Normalized error hierarchy in `errors.py`
- `LocalModelManager` — RAM/CPU monitoring via psutil

### Gaps to close 🔴
| Gap | Priority |
|-----|----------|
| `AnthropicProvider` missing `list_models()`, normalized errors, `complete_for_model()` | HIGH |
| `GeminiProvider` missing `list_models()`, normalized errors, `health_check()` that actually tests the API | HIGH |
| `OllamaProvider` capability profile is static (all models get same scores) | HIGH |
| `score_model()` not integrated into `AdaptiveHybridRouter._cloud()` — cloud selection is pure cost-sort | HIGH |
| No experience-based score adjustment from `routing_experiences` table | HIGH |
| `fallback.py` not wired into `main.py` task execution — errors raise directly | HIGH |
| `ModelSelector` not used by `AdaptiveHybridRouter` — duplicate logic | MEDIUM |
| `LocalModelManager.can_use_local()` compares total budget vs available RAM (wrong: should compare model size vs available) | MEDIUM |
| No `complete_for_model()` on `AnthropicProvider` or `GeminiProvider` | MEDIUM |
| `TaskClassifier` — two parallel classifiers exist (`router.py:ModelRouter` and `task_classifier.py:TaskClassifier`) | MEDIUM |
| No model alias resolution (FAST/SMART/CODING/REASONING/etc.) | LOW |
| No user override command (`/model openai:gpt-4o`) | LOW |
| No CLI commands: `agent providers`, `agent models`, `agent models refresh`, `agent route` | LOW |
| No rate-limit tracking / exponential backoff in providers | LOW |

---

## Requirements

### R1 — Provider Interface Contract

**R1.1** Every provider MUST implement `AIProvider` from `agent/providers/base.py`.

**R1.2** `AIProvider` interface MUST expose:
```
complete(prompt, system) → (str, usage_dict)
complete_for_model(prompt, system, model_id) → (str, usage_dict)
health_check() → bool
list_models() → list[dict]
configured() → bool
```
`stream()` and `count_tokens()` are optional; return `NotImplemented` if unsupported.

**R1.3** Every provider MUST raise only errors from `agent/providers/errors.py`.
Raw HTTP errors MUST NOT propagate to the Agent Core.

**R1.4** No provider adapter MAY log, store, or surface an API key value.
Error messages MUST reference the provider name, not the key.

**R1.5** `AnthropicProvider` MUST implement:
- `complete_for_model(prompt, system, model_id)` — use model_id, not hardcoded `settings.anthropic_model`
- `list_models()` — call `/v1/models` if available; return empty list on failure (do not raise)
- Normalized error mapping from HTTP status codes

**R1.6** `GeminiProvider` MUST implement:
- `complete_for_model(prompt, system, model_id)`
- `health_check()` that makes a real API call (not just `return self.configured()`)
- `list_models()` — call Google's model list endpoint; return empty list on failure
- Normalized error mapping

**R1.7** `OllamaProvider.list_models()` MUST enrich capability profile per model:
- Models whose name contains `code`, `coder`, `starcoder`, `codellama`, `qwen.*coder` → add `coding`, `coding_agent` capability
- Models whose name contains `deepseek-r1`, `qwq`, `o1`, `reasoning` → add `reasoning` capability
- Models whose name contains `llava`, `vision`, `bakllava` → add `vision` capability
- All Ollama models get `local`, `private` capabilities

---

### R2 — Model Registry

**R2.1** `ModelRegistry` MUST persist to `data/database/model_registry.db`.

**R2.2** Schema MUST store all `ModelMetadata` fields. Any field not provided by the API MUST be stored as `NULL` (not invented).

**R2.3** Each record MUST have a `last_verified` ISO timestamp. Records older than `MODEL_REGISTRY_TTL_HOURS` (default: 24) are stale and trigger a background refresh.

**R2.4** `ModelRegistry.list()` MUST support filtering by:
- `provider` (existing)
- `capability` — returns only models with that capability tag
- `availability` — filter by `'verified'` | `'unknown'`

**R2.5** Prices MUST only be stored when the provider API returns them.
Invented prices are forbidden.

---

### R3 — Provider & Model Discovery

**R3.1** On startup, `ProviderDiscovery.refresh()` MUST:
1. Iterate all providers returned by `configured_providers()`
2. Skip providers where `configured()` returns False
3. Call `health_check()` — timeout ≤ 5 s
4. If healthy, call `list_models()` — timeout ≤ 15 s
5. Upsert results into `ModelRegistry`
6. Record `last_verified` timestamp

**R3.2** Discovery MUST be non-blocking and bounded. A single slow provider
MUST NOT block startup for more than 15 s.

**R3.3** If `list_models()` returns an empty list, the provider's previously
discovered models MUST be retained in the registry (do not delete on empty).

**R3.4** `ProviderDiscovery` MUST expose `refresh(provider_name=None)` for
targeted single-provider refresh (already exists, verify it works).

---

### R4 — Task Classification

**R4.1** `TaskClassifier` (in `agent/routing/task_classifier.py`) is the
single authoritative classifier. `ModelRouter` in `router.py` is legacy and
MUST NOT be called for new routing decisions.

**R4.2** `TaskClassifier.classify()` MUST return a `ClassifiedTask` with:
- `labels: list[str]` — one or more from: `general_chat`, `coding`, `debugging`, `refactoring`, `research`, `reasoning`, `summarization`, `document_analysis`, `vision`, `tool_execution`, `agentic_task`, `data_analysis`, `fast_response`, `embedding`
- `required_capabilities: list[str]` — capability constants from `capabilities.py`
- `complexity_score: float` — 0.0–1.0
- `requires_tools: list[str]` — tool names needed

**R4.3** A task MAY have multiple labels. `"Fix TypeScript bug"` → `['coding', 'debugging', 'reasoning']`.

---

### R5 — Model Scoring & Selection

**R5.1** `score_model()` in `scoring.py` MUST be used by `AdaptiveHybridRouter`
for both local and cloud candidate selection.

**R5.2** Score components and their default weights:

| Component | Weight | Source |
|-----------|--------|--------|
| capability_match | 0.35 | fraction of required caps in model.capabilities |
| task_match | 0.20 | capability_profile scores (coding/reasoning/instruction) |
| cost_efficiency | 0.15 | 1/(1 + input_price) if known; 0.5 if unknown |
| latency | 0.10 | from historical avg latency in routing_experiences |
| historical_success | 0.20 | success rate from routing_experiences WHERE model=X |

**R5.3** When `routing_experiences` has fewer than 5 samples for a model,
`historical_success` contribution MUST be 0 (not enough data).

**R5.4** `AdaptiveHybridRouter._cloud()` MUST use `score_model()` instead of
pure cost-sort. Highest score wins.

**R5.5** `AdaptiveHybridRouter._local()` MUST use `score_model()` for candidate
ranking when multiple local models are available.

---

### R6 — Resource-Aware Local Selection

**R6.1** `LocalModelManager` MUST track:
- `ram_available_mb` — current free RAM
- `ram_total_mb` — total RAM
- `cpu_percent` — current CPU usage
- `local_budget_mb` — max RAM to allocate for local models (from `MAX_LOCAL_RAM_MB`)

**R6.2** `can_use_local()` MUST return `False` if `ram_available_mb < local_budget_mb`.
(Current implementation is correct; verify it remains so.)

**R6.3** When `OllamaProvider.list_models()` returns model size metadata,
`ModelMetadata` MUST store it in a `model_size_bytes` field.
`AdaptiveHybridRouter._local()` MUST skip models where `model_size_bytes > ram_available_mb * 1024 * 1024`.

**R6.4** `LocalModelManager` MUST NOT load or start any model. It only monitors
resources and gates selection.

---

### R7 — Fallback Chain

**R7.1** `fallback.with_fallback()` MUST be used in `main.py:task()` to wrap
provider execution. The current direct try/except in `main.py` MUST be replaced.

**R7.2** Fallback MUST select next candidate based on capability match, not
just next in a static list. If no remaining candidate supports the task's
required capabilities, raise `ModelCapabilityError`.

**R7.3** Fallback behavior per error type:

| Error | Action |
|-------|--------|
| `ProviderRateLimitError` | Skip provider, try next |
| `ProviderAuthenticationError` | Skip provider permanently for this session |
| `ProviderTimeoutError` | Skip provider, try next |
| `ProviderUnavailableError` | Skip provider, try next |
| `ContextLengthError` | Compress context, retry same provider/model once |
| `ModelNotFoundError` | Skip model, try next from same provider |

**R7.4** Maximum fallback attempts MUST be bounded by `max_repair_attempts`
from settings (default: 1 cloud fallback).

---

### R8 — Experience-Based Routing

**R8.1** After every successful or failed task execution, `store.add_routing_experience()`
MUST be called with: route, provider, model, task_type, success(bool),
quality_score, latency_ms, tool_usage.

**R8.2** `score_model()` MUST query `routing_experiences` for historical
success rate per (provider, model_id, task_type).

**R8.3** Minimum sample threshold: 5 completed tasks before historical data
influences score. Below threshold, `historical_success` weight = 0.

**R8.4** Historical scores MUST NOT change faster than one update per request.
No batch recomputation on every call.

---

### R9 — Cost Optimization Pipeline

**R9.1** `main.py:task()` MUST evaluate in this order before any provider call:
1. Exact cache (`store.get_cache(prompt)`)
2. *(Future)* Semantic cache — not implemented, placeholder only
3. Local AI availability check (`local_manager.can_use_local()`)
4. Score all available models
5. Select local model if score ≥ task complexity
6. Else select cloud model by score
7. Execute with fallback

**R9.2** If `routing_mode == 'LOCAL_ONLY'` and no local model is capable/available,
return an error — do NOT fall back to cloud.

**R9.3** If `routing_mode == 'CLOUD_ONLY'`, skip local model evaluation entirely.

---

### R10 — Security

**R10.1** API keys MUST only be read from environment variables via `settings`.
They MUST NOT appear in: database records, log files, error messages, response
bodies, `routing_experiences`, `memories`, or `exact_cache`.

**R10.2** `agent/security/redaction.py:redact()` MUST be applied to:
- All prompts before storage in `exact_cache`
- All prompts before storage in `memories`
- All prompts before storage in `experiences`

**R10.3** Error messages returned to the dashboard MUST NOT include stack traces
or internal paths. (FastAPI exception handlers already enforce this.)

---

### R11 — Offline Behavior

**R11.1** If all providers return `available=False` or `configured=False`,
`AdaptiveHybridRouter.decide()` MUST return `Route.UNAVAILABLE` with a clear
human-readable reason.

**R11.2** The gateway MUST NOT crash or raise an unhandled exception when all
providers are unavailable. `main.py` MUST return HTTP 503 with:
```json
{"code": "AI_EXECUTION_ERROR", "message": "No capable AI model is available..."}
```

**R11.3** If only Ollama is available but no model is installed, the message
MUST distinguish "Ollama running but no model installed" from "Ollama offline".

---

### R12 — Model Aliases

**R12.1** A model alias system MUST resolve logical names to the best available
model at query time (not hardcoded at startup).

**R12.2** Required aliases and their resolution criteria:

| Alias | Resolution |
|-------|------------|
| `FAST` | lowest latency local model, or cheapest cloud |
| `SMART` | highest overall score across all providers |
| `CODING` | highest score among models with `coding` or `coding_agent` capability |
| `REASONING` | highest score among models with `reasoning` capability |
| `VISION` | highest score among models with `vision` capability |
| `LOCAL_FAST` | fastest local model (lowest avg latency in experiences) |
| `LOCAL_CODING` | local model with `coding` capability and best score |
| `CHEAP` | cloud model with lowest `input_price` |
| `PREMIUM` | cloud model with highest overall score |

**R12.3** Aliases are resolved at task time using current `ModelRegistry` state.
They MUST NOT be cached to a specific model_id.

---

### R13 — CLI Commands

**R13.1** The following `zevora` subcommands MUST be available via `zevora/cli.py`:

```
zevora providers              # list all providers with health status
zevora models                 # list model registry (provider | model | capabilities | status)
zevora models refresh         # trigger ProviderDiscovery.refresh() for all providers
zevora models refresh openai  # refresh single provider
zevora models test openai gpt-4o-mini  # send a test prompt, show latency + response
zevora route "fix TypeScript error"    # show routing decision without executing
```

**R13.2** CLI output MUST be human-readable plain text, not raw JSON.

**R13.3** `zevora route` MUST display:
```
Task:      coding, debugging, reasoning
Complexity: 0.42
Selected:  openai / gpt-4o-mini
Reason:    capability match (coding+reasoning), cost efficient
Est. cost: $0.000120 / request
```

---

### R14 — No Provider Lock-In

**R14.1** Removing a provider's API key from `.env` MUST cause that provider
to be skipped entirely — no errors, no crashes, no stale data affecting routing.

**R14.2** Adding a new OpenAI-compatible provider requires only:
1. Adding `NEW_API_KEY` and `NEW_BASE_URL` to `.env`
2. Adding the provider to `provider_factories()` in `registry.py`
3. Zero changes to `main.py`, `hybrid_router.py`, or any other core file

**R14.3** The system MUST function with only a single provider configured
(local or cloud).

---

## Non-Requirements (Out of Scope)

- Streaming responses in the dashboard UI
- Automatic model download (`ollama pull`)
- Fine-tuning or training
- Multi-turn tool execution loops (agentic loop)
- Vector embeddings for semantic cache
- Rate limit tracking with Redis (SQLite-local only)

---

## Glossary

| Term | Definition |
|------|-----------|
| **Provider** | An AI service that offers model inference (OpenAI, Anthropic, Gemini, Ollama, etc.) |
| **Adapter** | Python class implementing `AIProvider` ABC for a specific provider |
| **Model Registry** | SQLite-backed store of discovered model metadata |
| **Capability** | A tag describing what a model can do (e.g. `coding`, `reasoning`, `vision`) |
| **Routing Decision** | The output of `AdaptiveHybridRouter.decide()` — which provider/model to use |
| **Experience** | A recorded past execution: provider, model, task_type, success, latency, cost |
| **Alias** | A logical model name (e.g. `CODING`) resolved at query time to the best available model |
| **TTL** | Time-to-live for model registry cache entries, controlled by `MODEL_REGISTRY_TTL_HOURS` |
| **Fallback Chain** | Ordered list of candidate models tried sequentially on provider failure |
| **Local model** | A model running via Ollama on the local machine, tagged with `local` capability |
| **Cloud model** | A model accessed via remote API (OpenAI, Anthropic, etc.) |
| **Score** | Weighted numeric value combining capability match, cost, latency, and history |
