# ZEVORA Hybrid Architecture Blueprint

## Objective

ZEVORA is a hybrid local and cloud AI coding workspace. Extend the existing provider, discovery, model registry, router, quality gate, fallback, memory, and MCP abstractions. Do not create a separate local execution path.

## Inference Providers

### Zevora Local AI

- Runtime: llama.cpp through `llama-cpp-python`.
- Model file: `models/zevora-4b-thinking.gguf`.
- Product display name: `Zevora Local AI`.
- The display identity does not imply that ZEVORA modified or trained the underlying weights.
- Loading is lazy on the first local generation request.
- Local inference requires no API key or internet connection.
- Local model metadata advertises text, coding, reasoning, JSON, and tool capabilities, but not vision.

### Cloud Providers

OpenAI, Anthropic, DeepSeek, xAI, NVIDIA, Gemini, and configured OpenAI-compatible endpoints remain normal `AIProvider` implementations. Cloud providers are optional when local inference is available.

## End-to-End Agent Flow

```text
Start ZEVORA
  -> select workspace
  -> workspace policy + project discovery
  -> Agent Core
       -> local intelligence: exact cache, knowledge, memory
       -> project context: framework, language, manifests, files
       -> MCP: filesystem, terminal, Git
  -> context decision
       -> exact match: CACHE_SUFFICIENT -> final response
       -> retrieved references: RETRIEVAL_ENRICHED -> hybrid router
       -> no references: ROUTER_REQUIRED -> hybrid router
  -> local/cloud AI reasoning
  -> strict structured action plan
  -> approval boundary
  -> scoped MCP execution + observations
  -> verification
       -> pass: final response
       -> fail: record failure and request a new approved repair action
  -> knowledge extraction, bounded compression, and deduplication
  -> cache, memory, usage, and routing experience
```

Workspace discovery and access checks occur before project actions. Discovery
returns frameworks, languages, package manager, manifests, and a bounded file
tree. Relevant project files, local knowledge, memory, attachments, and approved
tool observations form the bounded context sent to a selected provider.

AUTO mode uses local-first ordering for lightweight text work. Complex,
architecture, migration, multi-file, long-context, and vision work is
cloud-first. `LOCAL_ONLY` excludes cloud candidates. `CLOUD_ONLY` excludes local
candidates.

Task responses retain the legacy contract and add:

- `project_discovery`: authoritative local project metadata, or `null` without a workspace.
- `context_status`: `CACHE_SUFFICIENT`, `RETRIEVAL_ENRICHED`, or `ROUTER_REQUIRED`.
- `flow`: workspace, discovery, context, route, action, verification, and knowledge states.

Retrieved knowledge enriches novel inference; only an exact cache match answers
without a provider. This distinction prevents stale or partial knowledge from
being presented as a fully verified answer.

## Fallback Rules

- Local exception or quality rejection: try the next capable cloud candidate.
- Cloud exception or network failure: try the next capable local candidate.
- Vision requests never use the text-only local model.
- Fallback attempts are bounded by the candidate list and recorded in `fallback_trace`.
- Exact-cache hits return before any provider is called.

## Runtime And Resource Safety

- Keep one process-wide llama.cpp model instance.
- Protect initialization and generation with separate locks.
- Run blocking inference outside the asyncio event loop.
- Report configured, runtime-available, loaded, model-size, process-RSS, load-delta, and load-time status.
- Do not load model weights during provider discovery or gateway startup.

## Workspace, Permission, And Repair Safety

Filesystem, Git, and terminal operations remain scoped to the selected
workspace. The permission policy supports one-time and session grants plus an
explicit deny preference. Mutations and restricted commands require approval.
A path outside the selected workspace remains blocked even when the request says
it is approved; the user must select the intended workspace.

Model output never bypasses the policy or directly becomes executable. The plan
parser accepts one strict JSON action document and rejects unknown or disabled
tools. The executor records `UNDERSTAND`, `PLAN`, `INSPECT`, `RETRIEVE`,
`REASON`, `ACT`, `OBSERVE`, and `VERIFY` stages.

A verification failure does not authorize ZEVORA to edit code automatically.
The trace records `FIX=not_executed` and `VERIFY_AGAIN=skipped`; a subsequent
repair plan must return through the same explicit approval boundary. This gives
the product a reason, fix, verify-again loop without weakening workspace safety.

## Knowledge Lifecycle

Successful provider answers and authoritative MCP mutation receipts are reduced
to bounded problem and solution-pattern records. The knowledge engine normalizes
prompt text and hashes task, project, and problem identity so duplicates update
one record instead of growing unbounded copies. Retrieval records reuse through
hit counts. Pruning removes expired low-value, unused knowledge while preserving
important or reused records.

## Acceptance Criteria

1. Gateway starts without cloud API keys.
2. Local model discovery does not load weights.
3. Workspace selection produces bounded project discovery before actions or inference.
4. Exact cache, enriched retrieval, and router-required branches expose distinct states.
5. Lightweight tasks route local-first in AUTO.
6. Complex and vision-capable tasks route cloud-first in AUTO.
7. Local failure or quality rejection falls back to cloud.
8. Cloud failure falls back to local when capable.
9. Structured MCP actions cannot execute mutations before explicit approval.
10. Paths outside the workspace stay blocked after approval.
11. Verification failures require a new approved repair action.
12. Provider answers and mutation receipts produce deduplicated knowledge records.
13. Flow metadata persists with completed chat exchanges.
14. Identity prompts return `Zevora Local AI` without false weight attribution.
15. Health, Providers API, and Providers UI expose local runtime status and measured memory.
16. Existing provider, router, MCP, project, and gateway contracts remain green.
