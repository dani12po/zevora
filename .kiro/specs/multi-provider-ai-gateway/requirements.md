# Requirements Document

## Introduction

The Multi-Provider AI Gateway is an enhancement to the existing Hybrid AI Agent (ZEVORA) that makes the system fully dynamic and provider-agnostic. Instead of hard-coded model selection and static provider configuration, the gateway auto-discovers every available provider and model from API keys in `.env`, classifies each task, scores all candidate models using a weighted multi-dimensional scoring function, selects the best model, executes with a structured fallback chain, and continuously learns from historical performance data — all without the user writing any provider-specific code.

The existing codebase already contains the structural skeleton for providers, models, routing, security, and memory. These requirements formalize the intended behaviour, identify gaps (e.g., missing `stream()`, `generate()`, resource manager, cost pipeline ordering), and define verifiable acceptance criteria including round-trip and property-based correctness properties.

---

## Glossary

- **Gateway**: The FastAPI application (`main.py`) that is the single entry point for all AI inference requests.
- **Provider**: An external or local AI inference service (OpenAI, xAI, NVIDIA NIM, DeepSeek, Anthropic, Google Gemini, Ollama).
- **Adapter**: The Python class in `agent/providers/` that wraps one provider's HTTP API, conforming to the `AIProvider` ABC.
- **Model_Registry**: The SQLite-backed store at `data/database/model_registry.db` that persists metadata for every discovered model.
- **Capability**: A string token (e.g., `coding`, `vision`, `reasoning`) that describes what a model can do. Defined in `agent/models/capabilities.py`.
- **Task**: A single inference request from the user, classified into one or more task labels by the Task_Classifier.
- **Task_Classifier**: The component in `agent/routing/task_classifier.py` that maps a raw prompt to task labels, required capabilities, complexity score, and required tools.
- **Hybrid_Router**: The orchestration component (`agent/routing/hybrid_router.py`) that decides the route (LOCAL, CLOUD, CACHE, LOCAL_MCP, UNAVAILABLE) for each task.
- **Model_Selector**: The component (`agent/routing/model_selector.py`) that ranks candidate models using the Scorer and returns the top selection.
- **Scorer**: The scoring function in `agent/routing/scoring.py` that produces a numeric score per model for a given task.
- **Fallback_Chain**: An ordered sequence of candidate models tried in succession when earlier candidates fail.
- **Provider_Discovery**: The startup and on-demand refresh component (`agent/providers/discovery.py`) that queries each configured provider for its live model list.
- **Resource_Manager**: The component in `agent/resource_manager/` that monitors host RAM, CPU, GPU/VRAM and gates local model use accordingly.
- **Experience_Store**: The `routing_experiences` and `experiences` SQLite tables in `agent/memory/store.py` that record per-execution outcomes.
- **Redaction_Filter**: The component in `agent/security/redaction.py` that removes credential patterns from any string before it is persisted or returned.
- **Cost_Pipeline**: The ordered sequence of resolution strategies — Exact_Cache → Semantic_Cache → Persistent_Memory → Local_AI → Provider_Selection → Model_Selection → Cloud_Execution — applied to every task request.
- **RoutingDecision**: The frozen dataclass returned by the Hybrid_Router describing the chosen route, provider, model, reason, and estimated cost.
- **ModelMetadata**: The dataclass in `agent/models/metadata.py` that represents all known facts about a single model.
- **Settings**: The pydantic-settings object (`agent/config.py`) that reads every configuration value from `.env`.

---

## Requirements

### Requirement 1: Provider Adapter Contract

**User Story:** As a developer, I want every provider adapter to conform to a single abstract interface, so that the rest of the gateway can call any provider without branching on provider type.

#### Acceptance Criteria

1. THE `AIProvider` ABC SHALL define the following abstract methods: `complete(prompt, system)`, `chat(messages)`, `stream(prompt, system)`, `generate(prompt, system)`, `count_tokens(text)`, `health_check()`, `list_models()`, `get_model_info(model_id)`.
2. THE `AIProvider` ABC SHALL define a `configured()` method that returns `True` only when all required credentials for that provider are present in the environment.
3. WHEN a concrete adapter is instantiated without the required API key, THE Adapter SHALL return `False` from `configured()` without raising an exception.
4. WHEN `health_check()` is called on an unconfigured adapter, THE Adapter SHALL return `False` without making any network call.
5. THE `OpenAICompatibleProvider` SHALL implement all `AIProvider` methods and SHALL be reusable as the adapter for OpenAI, xAI, NVIDIA NIM, and DeepSeek by passing different `name`, `api_key`, and `base_url` constructor arguments.
6. THE `AnthropicProvider` SHALL implement all `AIProvider` methods using the Anthropic Messages API format (`/v1/messages` with `x-api-key` header).
7. THE `GeminiProvider` SHALL implement all `AIProvider` methods using the Google Generative Language REST API.
8. THE `OllamaProvider` SHALL implement all `AIProvider` methods using the Ollama local REST API (`/api/generate`, `/api/chat`, `/api/tags`).
9. IF an adapter receives an HTTP 401 or 403 response, THEN THE Adapter SHALL raise `ProviderAuthenticationError`.
10. IF an adapter receives an HTTP 429 response, THEN THE Adapter SHALL raise `ProviderRateLimitError`.
11. IF an adapter HTTP request exceeds the configured `provider_timeout_seconds`, THEN THE Adapter SHALL raise `ProviderTimeoutError`.
12. IF an adapter receives an HTTP 5xx response, THEN THE Adapter SHALL raise `ProviderUnavailableError`.
13. IF an adapter receives an HTTP 404 response for a model endpoint, THEN THE Adapter SHALL raise `ModelNotFoundError`.
14. THE `errors` module SHALL define the following normalized error types: `ProviderError`, `ProviderAuthenticationError`, `ProviderRateLimitError`, `ProviderTimeoutError`, `ProviderUnavailableError`, `ModelNotFoundError`, `ModelCapabilityError`, `ContextLengthError`, `TokenLimitError`, `InvalidRequestError`.
15. FOR ALL concrete adapter implementations, calling `chat(messages)` with a single user message SHALL produce the same result as calling `complete(prompt, system)` with equivalent content (round-trip equivalence property).

---

### Requirement 2: Provider Registry and Auto-Discovery

**User Story:** As a user, I want the gateway to automatically find every provider and model that my API keys support, so that I never have to manually register models.

#### Acceptance Criteria

1. THE `Provider_Registry` SHALL maintain a factory entry for each supported provider: `openai`, `xai`, `nvidia`, `deepseek`, `anthropic`, `gemini`, `ollama`.
2. WHEN `configured_providers()` is called, THE `Provider_Registry` SHALL return a list where each entry includes the provider name and a boolean `configured` field reflecting whether the required API key is present in `Settings`.
3. THE `Provider_Discovery` component SHALL accept a `ModelRegistry` instance and SHALL call `provider.list_models()` for every configured, healthy provider during a `refresh()` call.
4. WHEN `refresh()` completes for a provider, THE `Provider_Discovery` SHALL call `Model_Registry.replace_provider()` to atomically replace all stored models for that provider.
5. WHEN a provider's `health_check()` returns `False` during `refresh()`, THE `Provider_Discovery` SHALL skip `list_models()` for that provider and record `health_status='unavailable'` in the output.
6. THE Gateway SHALL invoke `Provider_Discovery.refresh()` once during application startup (`@app.on_event('startup')`), bounded by a timeout that does not block the first request indefinitely.
7. THE `POST /api/models/refresh` endpoint SHALL accept an optional `provider` query parameter and SHALL trigger `Provider_Discovery.refresh(provider)` for only that provider when supplied.
8. WHEN `Provider_Discovery.refresh()` is called with no argument, THE `Provider_Discovery` SHALL refresh all configured providers concurrently or sequentially without raising an unhandled exception if any individual provider fails.
9. FOR ALL providers that return a non-empty model list, every model returned by `list_models()` SHALL appear in `Model_Registry.list(provider)` immediately after a successful `replace_provider()` call (persistence round-trip property).

---

### Requirement 3: Model Registry

**User Story:** As the routing system, I need a persistent, queryable store of all discovered models with their full metadata, so that routing decisions can be made without live API calls.

#### Acceptance Criteria

1. THE `Model_Registry` SHALL store the following fields for each model: `provider`, `model_id`, `display_name`, `capabilities`, `capability_profile`, `context_window`, `max_output_tokens`, `supports_streaming`, `supports_tools`, `supports_vision`, `supports_reasoning`, `supports_code`, `supports_json`, `supports_embeddings`, `input_price`, `output_price`, `availability`, `health_status`, `last_verified`.
2. THE `Model_Registry` SHALL use SQLite at the path `data/database/model_registry.db` and SHALL create the schema on first use without requiring a migration script.
3. WHEN `Model_Registry.upsert(model)` is called, THE `Model_Registry` SHALL persist the model data such that a subsequent `list()` call returns a dict containing all fields of that model (round-trip property).
4. WHEN `Model_Registry.list(provider)` is called with a provider name, THE `Model_Registry` SHALL return only models whose `provider` field matches that name.
5. WHEN `Model_Registry.replace_provider(provider, models)` is called, THE `Model_Registry` SHALL atomically delete all existing rows for that provider and insert the new models, such that no intermediate state with a mix of old and new models is observable.
6. WHEN `Model_Registry.list()` is called with no argument, THE `Model_Registry` SHALL return all stored models across all providers.
7. THE `ModelMetadata` dataclass SHALL include a `to_dict()` method whose output can be passed back to `ModelMetadata(**data)` to reconstruct an equivalent object (serialization round-trip property).

---

### Requirement 4: Capability System

**User Story:** As the routing system, I want every model tagged with a consistent set of capability tokens, so that I can match models to tasks precisely.

#### Acceptance Criteria

1. THE `capabilities` module SHALL define the following capability constants as string tokens: `GENERAL`, `CODING`, `CODING_AGENT`, `REASONING`, `FAST_RESPONSE`, `LONG_CONTEXT`, `VISION`, `TOOL_USE`, `FUNCTION_CALLING`, `JSON`, `STRUCTURED_OUTPUT`, `RESEARCH`, `EMBEDDING`, `LOCAL`, `PRIVATE`.
2. THE `metadata` module SHALL define the following model alias constants that map to lists of required capabilities: `FAST`, `SMART`, `CODING`, `REASONING`, `VISION`, `LOCAL_FAST`, `LOCAL_CODING`, `CHEAP`, `PREMIUM`.
3. WHEN a model is stored with capability `LOCAL`, THE `Model_Selector` SHALL exclude that model from selection when `local_allowed=False`.
4. WHEN a task's `required_capabilities` is a subset of a model's `capabilities` set, THE `Model_Selector` SHALL consider that model a valid candidate.
5. WHEN a task's `required_capabilities` is NOT a subset of a model's `capabilities` set, THE `Model_Selector` SHALL exclude that model from the candidate list without raising an exception.

---

### Requirement 5: Task Classification

**User Story:** As the routing system, I want each incoming prompt classified into task labels, required capabilities, complexity score, and required tools, so that model selection can be task-aware.

#### Acceptance Criteria

1. THE `Task_Classifier` SHALL classify every prompt into at least one task label from the set: `CHAT`, `CODING`, `DEBUGGING`, `REFACTORING`, `RESEARCH`, `REASONING`, `SUMMARIZATION`, `DOCUMENT_ANALYSIS`, `VISION`, `TOOL_EXECUTION`, `AGENTIC_TASK`, `DATA_ANALYSIS`, `FAST_RESPONSE`, `EMBEDDING`, `general_chat`.
2. THE `Task_Classifier` SHALL return a `ClassifiedTask` with fields: `labels` (list of strings), `required_capabilities` (list of capability tokens), `complexity_score` (float in `[0.0, 1.0]`), `requires_tools` (list of tool names).
3. WHEN a prompt contains code-related keywords (e.g., `code`, `python`, `typescript`, `refactor`), THE `Task_Classifier` SHALL include `CODING` in `required_capabilities`.
4. WHEN a prompt contains debugging keywords (e.g., `debug`, `error`, `bug`), THE `Task_Classifier` SHALL include both `CODING` and `REASONING` in `required_capabilities`.
5. WHEN a prompt contains vision-related keywords (e.g., `image`, `vision`, `screenshot`), THE `Task_Classifier` SHALL include `VISION` in `required_capabilities`.
6. THE `Task_Classifier` SHALL produce a `complexity_score` that is always within the closed interval `[0.0, 1.0]` for any input prompt regardless of length (invariant property).
7. WHEN the same prompt is classified twice without any state change, THE `Task_Classifier` SHALL return identical `ClassifiedTask` values both times (idempotence property).
8. WHEN a prompt contains multiple task type indicators, THE `Task_Classifier` SHALL include all matching labels in the `labels` list and SHALL increase the `complexity_score` relative to a single-label prompt (metamorphic property).

---

### Requirement 6: Model Scoring

**User Story:** As the routing system, I want each candidate model scored across multiple weighted dimensions, so that the best model for the current task is selected consistently.

#### Acceptance Criteria

1. THE `Scorer` SHALL compute a model score as a weighted sum of the following dimensions: `capability_match`, `task_match`, `context_capacity`, `tool_support`, `reliability`, `latency`, `cost_efficiency`, `historical_success`.
2. THE `Scorer` SHALL treat unknown dimension values as neutral (not penalizing a model for missing optional metadata).
3. WHEN all dimension values are at their maximum for two models, THE `Scorer` SHALL return equal scores for both (symmetry property).
4. WHEN model A has a higher `capability_match` than model B and all other dimensions are equal, THE `Scorer` SHALL return a higher score for model A (monotonicity property).
5. WHEN a model's `latency` parameter decreases (faster), THE `Scorer` SHALL return a higher score, all else equal (monotonicity property).
6. WHEN a model's `cost` parameter decreases (cheaper), THE `Scorer` SHALL return a higher score, all else equal (monotonicity property).
7. THE `Scorer` SHALL return a non-negative score for any combination of valid non-negative input dimensions (invariant property).
8. THE `Scorer` SHALL accept `reliability`, `latency_ms`, `cost`, and `historical_success` as optional parameters, defaulting to neutral contribution when `None`.

---

### Requirement 7: Model Selection and Routing

**User Story:** As the gateway, I want the routing system to select the single best model for each task using scored candidates and a defined preference order, so that every request uses the most appropriate model available.

#### Acceptance Criteria

1. THE `Model_Selector` SHALL accept a list of `ModelMetadata` dicts, a list of required capabilities, and a `local_allowed` boolean, then return a `Selection` with fields `provider`, `model_id`, `score`, and `reason`.
2. WHEN no candidate model satisfies the required capabilities, THE `Model_Selector` SHALL return `None` rather than raising an exception.
3. THE `Hybrid_Router` SHALL implement the priority order: LOCAL (Ollama) before CLOUD, but only when `Settings.local_first=True` and `Settings.routing_mode` is not `CLOUD_ONLY`.
4. WHEN `Settings.routing_mode` is `LOCAL_ONLY` and no local model satisfies the task, THE `Hybrid_Router` SHALL return `Route.UNAVAILABLE`.
5. WHEN `Settings.routing_mode` is `CLOUD_ONLY`, THE `Hybrid_Router` SHALL skip all local model candidates and route directly to CLOUD.
6. WHEN `Settings.routing_mode` is `AUTO`, THE `Hybrid_Router` SHALL select LOCAL if a capable local model exists and resources are sufficient, otherwise fall back to CLOUD.
7. WHEN a task's `requires_tools` list is non-empty and a local model is selected, THE `Hybrid_Router` SHALL return `Route.LOCAL_MCP` instead of `Route.LOCAL`.
8. WHEN the same prompt, model list, and resource state are provided, THE `Hybrid_Router.decide()` SHALL return the same `RoutingDecision` every time (determinism / idempotence property).
9. THE `RoutingDecision.to_dict()` method SHALL produce a dict that contains the same semantic information as the `RoutingDecision` dataclass, with `route` serialized as its string value (serialization property).

---

### Requirement 8: Fallback Chain Execution

**User Story:** As the gateway, I want failed inference attempts to automatically fall back through a capability-filtered chain of alternatives, so that a transient provider failure never produces an error if alternatives exist.

#### Acceptance Criteria

1. THE `Fallback_Chain` SHALL accept a list of pre-filtered candidate models and an async `execute` callable, then try each candidate in order until one succeeds.
2. WHEN a candidate raises any subclass of `ProviderError`, THE `Fallback_Chain` SHALL record the error and try the next candidate.
3. WHEN all candidates are exhausted without success, THE `Fallback_Chain` SHALL raise `ProviderError` with a message indicating that no capable provider completed the task.
4. WHEN a `ProviderRateLimitError` is raised by the primary model, THE `Hybrid_Router` fallback path SHALL select the next best cloud model that is not the same provider.
5. WHEN a local model fails after `Settings.max_local_retries` attempts and `Settings.cloud_fallback=True`, THE Gateway SHALL re-route to the best available cloud model and complete the request.
6. WHEN a local model fails and `Settings.cloud_fallback=False`, THE Gateway SHALL return HTTP 503 with error code `AI_EXECUTION_ERROR`.
7. WHEN all configured cloud providers are unavailable and at least one local Ollama model is healthy, THE Gateway SHALL route to the local model regardless of `Settings.local_first` (offline behaviour).
8. WHEN both cloud providers and local Ollama are unavailable, THE Gateway SHALL return HTTP 503 with a clear, user-readable message and SHALL NOT crash the gateway process.

---

### Requirement 9: Resource Manager

**User Story:** As the gateway, I want local model selection gated by real-time RAM and CPU availability, so that loading a large local model never causes an out-of-memory crash.

#### Acceptance Criteria

1. THE `Resource_Manager` SHALL expose a `resource_state()` method returning: `ram_available_mb`, `ram_percent`, `cpu_percent`, `local_budget_mb`, and optionally `gpu_vram_available_mb`.
2. THE `Resource_Manager` SHALL expose a `can_use_local()` method that returns `True` only when `ram_available_mb >= Settings.max_local_ram_mb`.
3. WHEN `can_use_local()` returns `False`, THE `Hybrid_Router` SHALL treat the local route as unavailable for that request.
4. THE `Resource_Manager` SHALL use `psutil` to read RAM and CPU metrics without requiring elevated privileges.
5. WHILE GPU hardware is present, THE `Resource_Manager` SHALL attempt to report `gpu_vram_available_mb` and SHALL silently omit the field if no GPU library is available.
6. THE `Resource_Manager.resource_state()` output SHALL always include `ram_available_mb`, `ram_percent`, `cpu_percent`, and `local_budget_mb` regardless of whether GPU metrics are available (invariant property).

---

### Requirement 10: Security — API Key Isolation

**User Story:** As a security-conscious operator, I want API keys to exist only in `.env` and never appear in the database, cache, logs, API responses, or prompts, so that credentials are never accidentally exposed.

#### Acceptance Criteria

1. THE `Settings` object SHALL read all API keys exclusively from environment variables or the `.env` file via `pydantic-settings` and SHALL NOT store key values in any database table, JSON file, or log entry.
2. THE `GET /api/providers/config` endpoint SHALL return API keys only in masked form (last 4 characters visible, remainder replaced with `••••••••`).
3. THE `POST /api/providers/config` endpoint SHALL write updated API keys to `.env` only and SHALL NOT echo the raw key value in any HTTP response body or log statement.
4. THE `Redaction_Filter` SHALL remove all strings matching the following patterns before any text is persisted or returned: `api_key=<value>`, `token=<value>`, `password=<value>`, `secret=<value>`, `sk-<16+ chars>`, `Bearer <token>`, PEM private key blocks.
5. WHEN the `Redaction_Filter` is applied to a string that contains no credential patterns, THE `Redaction_Filter` SHALL return the string unchanged (idempotence property).
6. WHEN the `Redaction_Filter` is applied twice to the same string, THE `Redaction_Filter` SHALL return the same result as applying it once (idempotence property).
7. THE Gateway SHALL apply `Redaction_Filter.redact()` to every user prompt and every AI response before persisting either to the database.
8. IF a log or error message would contain a raw API key pattern, THEN THE logging layer SHALL apply the `Redaction_Filter` before writing the entry.

---

### Requirement 11: Experience-Based Routing Learning

**User Story:** As the routing system, I want successful and failed inference outcomes recorded and weighted into future routing decisions, so that the gateway improves model selection over time.

#### Acceptance Criteria

1. THE `Experience_Store` SHALL record the following fields for every completed inference request: `task`, `provider`, `model`, `outcome` (`success` or `failure`), `execution_ms`, `metadata_json`, `created_at`.
2. THE `routing_experiences` table SHALL record: `route`, `provider`, `model`, `task_type`, `success` (integer 0/1), `quality_score`, `latency_ms`, `tool_usage`, `created_at`.
3. WHEN computing the `historical_success` score dimension in the `Scorer`, THE `Scorer` SHALL query the `routing_experiences` table to calculate the success rate for the given `(provider, model)` pair.
4. WHEN fewer than a configurable minimum sample count of experiences exist for a `(provider, model)` pair, THE `Scorer` SHALL treat `historical_success` as neutral (equivalent to `None`), avoiding premature routing changes.
5. THE `historical_success` score SHALL equal `successful_requests / total_requests` for the given model, constrained to `[0.0, 1.0]` (invariant property).
6. WHEN a new routing experience is inserted, THE experience data SHALL be retrievable from the `routing_experiences` table in a subsequent query (persistence round-trip property).
7. THE Gateway SHALL call `Store.add_routing_experience()` after every non-cached inference request, including both successful completions and handled failures.

---

### Requirement 12: Cost Optimization Pipeline

**User Story:** As a cost-conscious user, I want every task resolved at the cheapest acceptable tier before escalating to more expensive options, so that cloud costs are minimized while quality is preserved.

#### Acceptance Criteria

1. THE `Gateway` SHALL attempt task resolution in the following strict order: (1) Exact Cache lookup, (2) Semantic Cache lookup, (3) Persistent Memory retrieval, (4) Local AI inference, (5) Cloud Provider selection, (6) Cloud Model selection, (7) Cloud execution.
2. WHEN the Exact Cache contains a valid, non-expired entry for the prompt, THE `Gateway` SHALL return the cached response without calling any provider.
3. WHEN `Settings.cost_optimization=True` and a local model is capable and resources allow, THE `Hybrid_Router` SHALL prefer the local model over any cloud model for the same task.
4. WHEN selecting between multiple cloud models, THE `Scorer` SHALL use `input_price` and `output_price` from `ModelMetadata` to favour the lower-cost option when capability scores are equal.
5. THE exact cache key SHALL be a deterministic hash of the prompt and context hash such that the same inputs always produce the same key (determinism property).
6. WHEN a cached response is returned, THE `usage_events` record for that request SHALL have `cache_hit=1`.

---

### Requirement 13: Offline Behaviour

**User Story:** As a user with intermittent connectivity, I want the gateway to continue serving requests using local models when all cloud providers are unreachable, so that I am not left with a broken tool.

#### Acceptance Criteria

1. WHEN all cloud provider `health_check()` calls return `False` and at least one Ollama model is healthy, THE `Hybrid_Router` SHALL route the request to the local model regardless of `Settings.routing_mode`.
2. WHEN Ollama is also unavailable (all providers down), THE `Gateway` SHALL return HTTP 503 with a user-readable message that names the cause (e.g., "No AI model is available. Start Ollama or configure a cloud provider.") and SHALL NOT raise an unhandled exception.
3. WHEN the gateway starts with no configured cloud providers and Ollama is not running, THE `Gateway` startup event SHALL complete without crashing and SHALL log a warning.
4. WHEN Ollama becomes available after startup (hot-plug), THE next `POST /api/models/refresh` call SHALL discover the Ollama models and make them available for routing.

---

### Requirement 14: Gateway API Contracts

**User Story:** As a frontend or integration consumer, I want the gateway API to return consistent, machine-readable responses for all routes, so that I can build reliable integrations.

#### Acceptance Criteria

1. THE `POST /api/task` endpoint SHALL return a JSON object with at minimum the fields: `response`, `provider`, `model`, `task_type`, `route`, `reason`, `tools`, `estimated_cost`, `quality_score`, `cache_hit`, `execution_ms`.
2. THE `GET /api/providers` endpoint SHALL return a list where each entry includes `provider`, `configured`, and `health_status`.
3. THE `GET /api/models` endpoint SHALL return a list of model metadata dicts with at minimum the fields `provider`, `model_id`, `display_name`, `capabilities`, `availability`, `health_status`.
4. THE `GET /api/route` endpoint SHALL return the JSON serialization of a `RoutingDecision` for the given `prompt` query parameter, with `route` as its string value.
5. WHEN any API endpoint receives a request with an invalid or missing required field, THE `Gateway` SHALL return HTTP 400 with a JSON body containing `ok=False` and an `error` object with `code` and `message` fields.
6. WHEN an internal error occurs in any endpoint, THE `Gateway` SHALL return HTTP 500 with `ok=False` and `code='INTERNAL_ERROR'`, and SHALL NOT expose raw stack traces or exception messages containing credentials.
7. THE `POST /api/providers/config` endpoint SHALL return `ok=True` and `provider` and `key_updated` fields on success, and SHALL NOT include the API key in the response.
8. ALL `GET` endpoints on the `/api/` prefix SHALL return HTTP 200 with a valid JSON body when the gateway is healthy (smoke test property).

---

### Requirement 15: Streaming Support

**User Story:** As a user interacting with the chat UI, I want long responses streamed token-by-token rather than waiting for the full response, so that the interface feels responsive.

#### Acceptance Criteria

1. THE `AIProvider` ABC SHALL define a `stream(prompt, system)` abstract method that returns an async generator yielding string chunks.
2. THE `OpenAICompatibleProvider` SHALL implement `stream()` using the OpenAI Chat Completions streaming format (`stream=True`, `text/event-stream`).
3. THE `OllamaProvider` SHALL implement `stream()` using the Ollama streaming generate API (`stream=True`).
4. THE `AnthropicProvider` SHALL implement `stream()` using the Anthropic streaming messages API.
5. THE `GeminiProvider` SHALL implement `stream()` using the Gemini streaming generate API.
6. WHEN streaming is active, THE `Redaction_Filter` SHALL be applied to each chunk before it is yielded to the consumer.
7. WHEN a streaming request is interrupted mid-stream, THE Adapter SHALL raise `ProviderTimeoutError` rather than silently returning a partial response without error.
