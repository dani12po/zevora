# ZEVORA — FULL AUDIT + LEXI-LLAMA-3-8B-q4_k_m HYBRID INTEGRATION

## OBJECTIVE

Audit and update the EXISTING ZEVORA repository in-place.

Do NOT rewrite ZEVORA from scratch.

Do NOT remove the existing agent architecture, memory, evolution, MCP, filesystem, terminal, workspace, provider registry, model registry, adaptive routing, quality gate, or cloud providers.

The target local/open-weight model is:

Model repository:

`bartowski/Lexi-Llama-3-8B-Uncensored-GGUF`

Exact GGUF:

`Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf`

Model size:

approximately 5.73 GB.

Runtime target:

`llama.cpp`

The model must be usable in THREE deployment modes:

1. Embedded GGUF runtime
2. Remote GGUF runtime through an OpenAI-compatible endpoint
3. Hybrid routing between embedded, remote, and cloud providers

The remote deployment must support environments such as:

* Google Colab
* Kaggle
* another temporary/free GPU environment
* any OpenAI-compatible llama.cpp endpoint

The architecture must NOT depend specifically on Google Colab.

---

# PHASE 1 — AUDIT FIRST

Before modifying anything:

1. Inspect the entire repository.
2. Inspect all provider implementations.
3. Inspect model registry.
4. Inspect provider discovery.
5. Inspect adaptive routing.
6. Inspect task classification.
7. Inspect quality gate.
8. Inspect fallback.
9. Inspect local intelligence.
10. Inspect MCP gateway.
11. Inspect terminal execution.
12. Inspect frontend provider/model settings.
13. Inspect all tests.
14. Search the entire repository for old Qwen/local-model assumptions.

Search for:

* Qwen
* Qwen3
* qwen3.8
* UD-Q4_K_XL
* zevora-4b-thinking
* local_model_repository
* local_model_quant
* local_model_name
* local_model_display_name
* local_provider
* llamacpp
* llama_cpp
* local endpoint
* Ollama
* model registry
* provider registry
* routing priority
* tool_use
* supports_tools
* context_length

Create an internal audit report before changing code.

Do not blindly replace every occurrence of Qwen.

Determine whether each reference is:

* runtime configuration
* UI text
* documentation
* test fixture
* compatibility logic
* model identity
* routing assumption

Only change references that are actually tied to the previous default local model.

---

# PHASE 2 — PRESERVE EXISTING ARCHITECTURE

ZEVORA already has a mature architecture.

Preserve:

* AIProvider
* LocalIntelligenceProvider
* LocalProvider
* LocalEndpointProvider
* OpenAICompatibleProvider
* provider registry
* provider discovery
* model registry
* adaptive router
* quality gate
* fallback
* memory
* cache
* experience
* project indexing
* MCP gateway
* terminal sessions
* workspace permissions
* approval system
* evolution engine
* skill registry
* UI provider settings

Do not duplicate existing provider infrastructure.

Prefer extending existing abstractions.

---

# PHASE 3 — CREATE A GENERIC LOCAL MODEL PROFILE

Remove the assumption that ZEVORA's bundled model is always Qwen.

The local model configuration must become completely model-agnostic.

Introduce a model profile concept such as:

`LocalModelProfile`

with fields equivalent to:

* provider_id
* model_id
* display_name
* repository
* filename
* quantization
* runtime
* format
* context_length
* max_output_tokens
* temperature
* batch_size
* threads
* gpu_layers
* expected_size_bytes
* sha256
* capabilities
* source
* license
* deployment_mode

The default profile must be Lexi.

Default:

repository:

`bartowski/Lexi-Llama-3-8B-Uncensored-GGUF`

filename:

`Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf`

model_id:

`lexi-llama-3-8b-q4_k_m`

display_name:

`Lexi Llama 3 8B q4_k_m`

runtime:

`llamacpp`

format:

`gguf`

---

# PHASE 4 — LEXI EMBEDDED RUNTIME

Keep the existing llama.cpp runtime.

The model must load through the existing LocalProvider.

Do NOT create a second llama.cpp implementation.

The existing lifecycle must remain:

* lazy loading
* load
* unload
* restart
* health
* streaming
* memory statistics
* generation statistics
* SHA-256 verification

The runtime must load:

`Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf`

through configuration rather than hardcoded source code.

---

# PHASE 5 — MODEL DOWNLOAD / INSTALLATION

Add a proper model installer/downloader.

It must be able to download ONLY the selected GGUF file.

Do NOT clone/download the entire Hugging Face repository.

Support:

* Hugging Face repository
* exact filename
* resumable download if practical
* progress
* size verification
* SHA-256 verification
* atomic installation
* temporary download file
* rollback on failure

Target managed path:

`data/models/lexi-llama-3-8b-q4_k_m/`

Example:

`data/models/lexi-llama-3-8b-q4_k_m/Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf`

Never silently overwrite an existing model.

Use explicit replacement/versioning behavior.

---

# PHASE 6 — REMOTE OPENAI-COMPATIBLE LEXI BACKEND

Extend the existing LocalEndpointProvider rather than creating a duplicate provider.

It must support a remote endpoint such as:

`https://<temporary-host>/v1`

or:

`http://<host>:<port>/v1`

The endpoint must be configurable.

Configuration must include:

* enabled
* base_url
* api_key
* model_id
* timeout
* health_check_timeout
* streaming
* capabilities
* routing_priority

The remote endpoint must use:

`GET /models`

and:

`POST /chat/completions`

when supported.

Do not assume the endpoint is Ollama.

Do not hardcode port 11434 for the Lexi backend.

---

# PHASE 7 — REMOTE PROVIDER IDENTITY

Do NOT pretend that a Colab-hosted model is the same process as embedded local inference.

Introduce a clear deployment identity.

For example:

`local_embedded`

and:

`local_remote`

or another clean naming scheme.

Recommended conceptual structure:

LOCAL EMBEDDED

* Lexi GGUF loaded inside ZEVORA

LOCAL REMOTE

* Lexi GGUF running in an external llama.cpp server

CLOUD

* external commercial/API provider

The router must understand all three.

---

# PHASE 8 — COLAB IS ONLY A DEPLOYMENT TARGET

Do NOT implement ZEVORA specifically around Colab URLs.

Instead implement a generic remote OpenAI-compatible backend.

Then create optional helper tooling/documentation for:

`Colab + llama.cpp + Lexi`

The architecture must work with:

* Colab
* Kaggle
* self-hosted llama.cpp
* any compatible server

The only information ZEVORA should need is:

BASE_URL

MODEL_ID

OPTIONAL API KEY

---

# PHASE 9 — COLAB CONNECTOR / DEPLOYMENT HELPER

Add a deployment helper/documentation for Google Colab.

The notebook must:

1. Detect GPU.
2. Display GPU information.
3. Install/build llama.cpp or an appropriate GPU-enabled runtime.
4. Download ONLY:

`Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf`

5. Start an OpenAI-compatible llama.cpp server.
6. Expose `/v1/models`.
7. Expose `/v1/chat/completions`.
8. Provide a configurable temporary public tunnel.
9. Display the resulting BASE_URL.
10. Display MODEL_ID.
11. Display health status.
12. Provide a shutdown/restart procedure.

Do not require a paid service.

Do not hardcode one tunneling vendor.

The notebook must clearly explain that free notebook sessions are temporary and the endpoint can disappear.

---

# PHASE 10 — ROUTER CHANGES

Update the adaptive router.

The router must understand:

* embedded Lexi
* remote Lexi
* cloud providers

AUTO mode should consider:

* task type
* coding requirement
* reasoning requirement
* tool requirement
* context length
* model health
* model availability
* deployment mode
* latency
* resource availability
* routing priority
* quality history
* failure history
* cloud fallback
* remote endpoint availability

Example:

CODING + TOOLS + embedded Lexi healthy:

→ embedded Lexi first

CODING + TOOLS + embedded unavailable + remote Lexi healthy:

→ remote Lexi

REMOTE Lexi unavailable:

→ cloud provider

COMPLEX ARCHITECTURE:

→ prefer stronger configured cloud model when available

LOCAL_ONLY:

→ embedded/remote local only

REMOTE_LOCAL_ONLY:

→ remote Lexi only

CLOUD_ONLY:

→ cloud only

AUTO:

→ adaptive routing

---

# PHASE 11 — TOOL CALLING MUST BE EXPLICIT

Do NOT assume:

`model exists = supports_tools`

The router must distinguish:

* text generation
* JSON
* streaming
* tool use
* vision
* coding
* reasoning

MCP remains ZEVORA's tool execution boundary.

The model must NEVER directly receive unrestricted filesystem access.

Correct architecture:

USER
↓
ZEVORA AGENT
↓
MODEL
↓
TOOL INTENT
↓
MCP PERMISSION CHECK
↓
MCP TOOL
↓
OBSERVATION
↓
MODEL
↓
FINAL RESPONSE

Keep:

* workspace boundaries
* approval gates
* command policy
* path validation
* dangerous command blocking

---

# PHASE 12 — LEXI SYSTEM PROMPT

The model must use ZEVORA's existing persona.

Do NOT replace:

`ZEVORA_PERSONA`

Do NOT remove the existing local identity layer.

However, prevent the model from being told that it has performed actions that ZEVORA has not actually performed.

The model must distinguish:

* reasoning
* proposed action
* actual tool result
* final answer

Never fabricate tool execution.

Never fabricate filesystem changes.

Never fabricate command execution.

Never claim a file was created unless MCP returned a successful mutation receipt.

---

# PHASE 13 — CONTEXT HANDLING

Audit:

`messages_to_prompt`

and the Lexi prompt format.

The model is Llama 3 based.

Use the correct Llama 3 chat template.

Do not manually concatenate messages into an incompatible prompt format if the llama.cpp runtime can correctly apply the model's chat template.

Preserve:

* system message
* user message
* tool observations
* conversation context
* project context
* memory context

Avoid sending the entire project to the model.

Continue using ZEVORA project indexing and context economy.

---

# PHASE 14 — CONTEXT WINDOW

Do not blindly use:

`8192`

for every model.

Make context configurable per model profile.

The router must reject a model when:

estimated_context > model_context_window

before execution.

Expose the configured context window in:

* provider UI
* model registry
* health endpoint
* routing diagnostics

---

# PHASE 15 — RESOURCE-AWARE LOCAL MODEL SELECTION

Use the existing GPU/RAM detection.

Before loading the embedded Lexi model, report:

* RAM
* available RAM
* GPU
* VRAM
* GGUF size
* context size
* GPU layers
* batch size

Do not make simplistic assumptions such as:

`5.73 GB file = 5.73 GB RAM requirement`

The runtime needs additional memory.

If the model cannot safely fit:

return a structured failure:

`LOCAL_MODEL_RESOURCE_INSUFFICIENT`

instead of crashing the gateway.

---

# PHASE 16 — GPU CONFIGURATION

Make llama.cpp settings configurable:

`local_model_gpu_layers`

`local_model_threads`

`local_model_batch_size`

`local_model_context_length`

Provide an AUTO option where appropriate.

If GPU is available:

prefer GPU offload.

If GPU is unavailable:

allow CPU mode if sufficient resources exist.

Never force GPU-only execution.

---

# PHASE 17 — PROVIDER UI

Update the Providers page.

The local model card should show:

Name:
Lexi Llama 3 8B q4_k_m

Runtime:
llama.cpp

Deployment:
Embedded / Remote

Repository:
bartowski/Lexi-Llama-3-8B-Uncensored-GGUF

Quantization:
q4_k_m

GGUF:
5.73 GB approximately

Context:
configured value

GPU:
detected GPU

VRAM:
detected VRAM

Status:

* Not installed
* Available
* Loading
* Ready
* Busy
* Error
* Remote unavailable

For remote Lexi show:

Base URL

Model ID

Connection status

Latency

Last successful request

---

# PHASE 18 — ADD MODEL MANAGEMENT UI

Add a Local Models section.

It must support:

* installed models
* model metadata
* size
* runtime
* quantization
* health
* load
* unload
* restart
* remove managed model
* configure external GGUF
* configure remote endpoint

Never delete external GGUF files automatically.

Keep the existing uninstall safety semantics.

---

# PHASE 19 — CONFIGURATION

Replace the Qwen-specific defaults.

Use environment variables similar to:

ZEVORA_LOCAL_MODEL_ENABLED=true

ZEVORA_LOCAL_MODEL_RUNTIME=llamacpp

ZEVORA_LOCAL_MODEL_REPOSITORY=bartowski/Lexi-Llama-3-8B-Uncensored-GGUF

ZEVORA_LOCAL_MODEL_FILENAME=Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf

ZEVORA_LOCAL_MODEL_QUANT=q4_k_m

ZEVORA_LOCAL_MODEL_NAME=lexi-llama-3-8b-q4_k_m

ZEVORA_LOCAL_MODEL_DISPLAY_NAME=Lexi Llama 3 8B q4_k_m

ZEVORA_LOCAL_MODEL_PATH=data/models/lexi-llama-3-8b-q4_k_m/Lexi-Llama-3-8B-Uncensored-q4_k_m.gguf

ZEVORA_LOCAL_MODEL_CONTEXT_LENGTH=8192

ZEVORA_LOCAL_MODEL_MAX_TOKENS=2048

ZEVORA_LOCAL_MODEL_GPU_LAYERS=auto

ZEVORA_LOCAL_MODEL_BATCH_SIZE=512

ZEVORA_LOCAL_MODEL_TEMPERATURE=0.4

REMOTE LEXI:

ZEVORA_REMOTE_LOCAL_ENABLED=false

ZEVORA_REMOTE_LOCAL_BASE_URL=

ZEVORA_REMOTE_LOCAL_API_KEY=

ZEVORA_REMOTE_LOCAL_MODEL=

ZEVORA_REMOTE_LOCAL_TIMEOUT_SECONDS=120

Do not break existing environment variable compatibility.

If older variable names exist, migrate them safely.

---

# PHASE 20 — PROVIDERS.JSON

Update the provider registry.

Do not hardcode Qwen.

Create explicit profiles for:

1. embedded Lexi
2. remote Lexi
3. existing cloud providers

Example conceptual configuration:

local_embedded:

runtime = llamacpp

model = lex...q4_k_m

local_remote:

protocol = openai-compatible

runtime = llamacpp

model = configurable

Do not hardcode a temporary Colab URL into the repository.

---

# PHASE 21 — MODEL REGISTRY

Ensure the model registry stores:

* provider
* deployment mode
* model ID
* display name
* runtime
* quantization
* capabilities
* context window
* availability
* health
* installed state
* source
* size
* hash
* compatibility

The model registry must not confuse:

same model

with:

same deployment.

Embedded Lexi and remote Lexi are separate runtime instances.

---

# PHASE 22 — HEALTH CHECKS

Embedded health:

* model file exists
* llama_cpp available
* model loadable
* integrity valid

Remote health:

* endpoint reachable
* `/models` responds
* requested model exists
* `/chat/completions` is reachable
* optional lightweight generation test

Do not perform expensive model generation during every health check.

Cache health state.

---

# PHASE 23 — STREAMING

Preserve existing ZEVORA streaming.

Embedded:

llama.cpp streaming.

Remote:

OpenAI-compatible SSE streaming when available.

Fallback:

buffered response if streaming is unsupported.

The frontend must not need to know whether the response came from embedded or remote Lexi.

---

# PHASE 24 — MCP INTEGRATION

Do not redesign MCP.

The existing MCP gateway is already the correct security boundary.

Ensure the Lexi agent can work with:

* list_directory
* read_file
* search_files
* file_exists
* get_file_info
* create_file
* write_file
* edit_file
* delete_file
* move_file
* copy_file
* execute_command
* git
* create_project
* package_manager

Respect existing:

* ALLOW
* APPROVAL
* DENY

rules.

Do not weaken command restrictions to make Lexi work.

---

# PHASE 25 — TERMINAL / CODING AGENT

Verify that Lexi can participate in the same coding workflow as other models.

Test:

User:

"Create a Python hello world project."

Expected flow:

1. classify task
2. select Lexi
3. inspect workspace
4. plan
5. call MCP
6. create files
7. run safe verification
8. inspect output
9. repair if necessary
10. return final result

The model itself must not execute commands.

ZEVORA executes commands through its existing execution/MCP layer.

---

# PHASE 26 — FALLBACK

Implement:

Embedded Lexi
→ Remote Lexi
→ Cloud

when configured.

But do not always use cloud fallback.

Respect:

`LOCAL_ONLY`

`REMOTE_LOCAL_ONLY`

`CLOUD_ONLY`

`AUTO`

and:

`cloud_fallback`

configuration.

Record fallback reason.

Examples:

`LOCAL_MODEL_MISSING`

`LOCAL_MODEL_RESOURCE_INSUFFICIENT`

`LOCAL_MODEL_RUNTIME_ERROR`

`REMOTE_ENDPOINT_UNAVAILABLE`

`REMOTE_MODEL_NOT_FOUND`

`QUALITY_GATE_REJECTED`

---

# PHASE 27 — OBSERVABILITY

Add provider telemetry without storing private prompts.

Record:

* provider
* deployment
* model
* request ID
* latency
* input token count
* output token count
* success/failure
* fallback reason
* quality result
* resource state

Never log:

* API keys
* credentials
* complete private prompts
* complete source code
* private filesystem contents

Preserve the existing redaction system.

---

# PHASE 28 — SECURITY

Audit all new remote URL handling.

Use existing SSRF protections.

Do not allow arbitrary remote endpoints to bypass provider security.

For user-configured remote endpoints:

* validate URL
* prevent unsafe protocols
* prevent localhost/private-network SSRF where appropriate for externally triggered requests
* do not leak credentials
* do not log Authorization headers

For Colab/temporary tunnels, allow explicit user configuration.

Do not silently connect to arbitrary URLs.

---

# PHASE 29 — TESTS

Add tests for:

1. Lexi default configuration
2. Lexi model profile
3. Qwen migration compatibility
4. GGUF filename
5. model download configuration
6. SHA-256 verification
7. embedded Lexi provider
8. remote Lexi provider
9. remote `/models`
10. remote `/chat/completions`
11. streaming
12. timeout
13. remote failure
14. fallback
15. LOCAL_ONLY
16. REMOTE_LOCAL_ONLY
17. CLOUD_ONLY
18. AUTO
19. tool capability filtering
20. context-window filtering
21. GPU resource filtering
22. model registry
23. provider health
24. MCP tool execution
25. filesystem security
26. terminal security
27. provider UI API
28. configuration migration

Mock inference.

Do NOT require the 5.73 GB model to be downloaded during normal unit tests.

Integration tests must be opt-in.

---

# PHASE 30 — REGRESSION TEST

Run the entire existing suite.

The existing project currently has a large test suite.

Do not accept the implementation if existing tests regress.

Run:

`pytest -q`

Then run additional Lexi integration tests separately.

Expected:

all existing tests pass.

---

# PHASE 31 — DOCUMENTATION

Update:

README.md

ARCHITECTURE.md

INSTALL.md

docs/ADAPTIVE_ROUTING.md

docs/MCP_TOOLS.md

local model documentation

Add:

`docs/LEXI_LLAMA.md`

It must explain:

* what Lexi is
* GGUF
* q4_k_m
* llama.cpp
* embedded mode
* remote mode
* Colab deployment
* Kaggle deployment concept
* configuration
* model installation
* troubleshooting
* resource requirements
* fallback behavior
* MCP relationship

Do not claim that the model is permanently free or that Colab provides permanent hosting.

---

# PHASE 32 — REMOVE QWEN ASSUMPTIONS

After implementation, search again for:

Qwen

qwen

UD-Q4_K_XL

zevora-4b-thinking

The only remaining references should be:

* migration documentation
* historical changelog
* compatibility tests
* explicit optional legacy configuration

No active default path should depend on Qwen.

---

# PHASE 33 — DO NOT BREAK CLOUD PROVIDERS

Existing providers must continue working:

* OpenAI
* Anthropic
* xAI
* DeepSeek
* NVIDIA
* Gemini

Do not remove any.

Do not change credentials behavior unnecessarily.

---

# PHASE 34 — FINAL ARCHITECTURE

Target architecture:

```
                ZEVORA UI
                     |
                     v
              FastAPI Gateway
                     |
                     v
               Agent Core
                     |
          +----------+----------+
          |                     |
          v                     v
     Context Engine         MCP Gateway
          |                     |
          v                     v
   Adaptive Router       Filesystem/Git/Terminal
          |
   +------+------+------+
   |             |      |
   v             v      v
```

Embedded Lexi   Remote Lexi  Cloud
llama.cpp       llama.cpp    providers
GGUF            OpenAI API   APIs
|             |
v             v
Local GGUF       Colab/Kaggle/
external GPU

The model backend must be replaceable.

ZEVORA should not be hardcoded around Lexi.

Lexi should simply become the default open-weight local model.

---

# PHASE 35 — IMPORTANT IMPLEMENTATION RULE

Do not create fake functionality.

If a remote server does not support:

* tool calling
* streaming
* JSON
* vision

mark the capability as unsupported.

Do not advertise unsupported capabilities in the UI.

Do not make the model appear healthier than it is.

Do not bypass MCP permissions.

Do not bypass quality gates.

Do not bypass provider security.

---

# PHASE 36 — DELIVERABLES

When finished, provide:

1. Complete audit summary.
2. Files changed.
3. Files added.
4. Files removed, if any.
5. Configuration migration details.
6. Lexi installation instructions.
7. Embedded mode instructions.
8. Remote mode instructions.
9. Colab deployment instructions.
10. MCP integration explanation.
11. Routing behavior explanation.
12. Security changes.
13. Test results.
14. Any remaining limitations.

Do not merely say "implemented".

Show concrete evidence.

Run the test suite before declaring completion.

The final implementation must be production-oriented, backward-compatible where practical, and must preserve the existing ZEVORA architecture.
