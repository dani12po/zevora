# Lexi Llama 3 8B Q5_K_M in ZEVORA

Default open-weight local model for ZEVORA's hybrid agent.

## What Lexi is

- **Model**: Llama 3 8B instruction-tuned variant ("Lexi", uncensored).
- **GGUF**: `Lexi-Llama-3-8B-Uncensored-Q5_K_M.gguf` (~5.73 GB), quantization
  `Q5_K_M` — a balanced size/quality point for 8B models on consumer hardware.
- **Repository**: `bartowski/Lexi-Llama-3-8B-Uncensored-GGUF` (Hugging Face).
- **Runtime**: `llama.cpp` (embedded via `llama-cpp-python`, or an external
  `llama-server` for remote mode).
- **Chat template**: Llama 3. Embedded generation calls llama.cpp's
  `create_chat_completion`, so the model's own chat template is applied by the
  runtime — ZEVORA does not hand-roll prompt concatenation for inference.
- **Product identity**: `Zevora Local AI`. The weights are not modified or
  re-attributed; the display name is only the product interface.

## Deployment modes

| Mode | Provider id | Description |
|---|---|---|
| Embedded | `local` | GGUF loaded inside ZEVORA via llama.cpp (lazy load/unload/restart). |
| Remote | `local_remote` | Lexi on an external llama.cpp server over OpenAI-compatible `/v1`. |
| Cloud | `openai`, `anthropic`, … | Commercial APIs for complex/vision/long-context work. |

AUTO routing order: embedded Lexi → remote Lexi → cloud. `LOCAL_ONLY` allows
embedded + remote; `REMOTE_LOCAL_ONLY` allows only the remote server;
`CLOUD_ONLY` disables local inference. Every failed attempt records a stable
reason (`LOCAL_MODEL_MISSING`, `LOCAL_MODEL_RESOURCE_INSUFFICIENT`,
`LOCAL_MODEL_RUNTIME_ERROR`, `REMOTE_ENDPOINT_UNAVAILABLE`,
`REMOTE_MODEL_NOT_FOUND`, `QUALITY_GATE_REJECTED`).

## Configuration

All values live in `.env` (see `.env.example`); each also accepts a
`ZEVORA_`-prefixed alias (e.g. `ZEVORA_LOCAL_MODEL_REPOSITORY`):

```ini
LOCAL_MODEL_REPOSITORY=bartowski/Lexi-Llama-3-8B-Uncensored-GGUF
LOCAL_MODEL_FILENAME=Lexi-Llama-3-8B-Uncensored-Q5_K_M.gguf
LOCAL_MODEL_QUANT=Q5_K_M
LOCAL_MODEL_NAME=lexi-llama-3-8b-q4_k_m
LOCAL_MODEL_DISPLAY_NAME=Lexi Llama 3 8B Q5_K_M
LOCAL_MODEL_PATH=models/Lexi-Llama-3-8B-Uncensored-Q5_K_M.gguf
LOCAL_MODEL_CONTEXT_LENGTH=8192
LOCAL_MODEL_MAX_TOKENS=2048
LOCAL_MODEL_GPU_LAYERS=0
LOCAL_MODEL_BATCH_SIZE=512
LOCAL_MODEL_TEMPERATURE=0.4
```

`LOCAL_MODEL_GPU_LAYERS=0` (or `auto`) means AUTO: prefer GPU offload when an
NVIDIA GPU is detected, otherwise CPU. Explicit values pass through (`-1` =
offload all layers). GPU-only execution is never forced.

Remote mode:

```ini
REMOTE_LOCAL_ENABLED=true
REMOTE_LOCAL_BASE_URL=https://<temporary-host>/v1
REMOTE_LOCAL_API_KEY=
REMOTE_LOCAL_MODEL=lexi-llama-3-8b-q4_k_m
REMOTE_LOCAL_TIMEOUT_SECONDS=120
```

Only `REMOTE_LOCAL_BASE_URL` + model id are required. Never commit a temporary
tunnel URL to the repository.

## Model installation (embedded)

ZEVORA downloads ONLY the selected GGUF file — never the whole repository:

- Gateway: `POST /api/local-model/install` with `{"approved": true}` (add
  `"replace": true` to explicitly replace an existing file).
- The download is resumable (`.part` file), verifies size + SHA-256, writes a
  `.sha256` sidecar, installs atomically, and rolls back on verification
  failure. An existing model is never silently overwritten.
- The Local AI page offers Unload/Restart; removal of managed files always
  requires explicit approval and never touches external GGUF files.

## Remote deployment (Colab / Kaggle / self-hosted)

Use `colab/lexi_llamacpp_server.ipynb`: it checks the GPU, installs
`llama-server`, downloads only the Q5_K_M GGUF, starts an OpenAI-compatible
server exposing `/v1/models` and `/v1/chat/completions`, and prints the
temporary `BASE_URL` + `MODEL_ID` to paste into ZEVORA's remote settings (or
Providers page → Remote Lexi). Any OpenAI-compatible llama.cpp server works —
Colab is only one deployment target, and free sessions are temporary: the
endpoint can disappear at any time.

## Resource requirements

Before loading, ZEVORA preflights RAM vs file size + context overhead and
returns `LOCAL_MODEL_RESOURCE_INSUFFICIENT` instead of crashing when the model
cannot safely fit. Rule of thumb: ~5.73 GB weights plus KV-cache/scratch —
8 GB+ free RAM for CPU inference at 8192 context; a GPU with 8 GB+ VRAM is
comfortable for offloaded inference. The Providers page shows live RSS and
load delta.

## Fallback behavior

Embedded missing/insufficient → remote Lexi (when configured and healthy) →
cloud providers (when `cloud_fallback` is enabled and the mode allows).
`LOCAL_ONLY` never calls cloud; `CLOUD_ONLY` never loads local.

## MCP relationship

Lexi never touches the filesystem, terminal, or Git directly. It emits tool
intent; ZEVORA's MCP gateway enforces workspace boundaries, ALLOW/APPROVAL/DENY
rules, and dangerous-command blocking, then returns observations to the model.
The system prompt additionally forbids fabricating tool execution or file
changes.

## Troubleshooting

- `LOCAL_MODEL_MISSING`: install the GGUF (`POST /api/local-model/install`
  with approval) or point `LOCAL_MODEL_PATH` at an existing file.
- `LOCAL_MODEL_RESOURCE_INSUFFICIENT`: free RAM, lower
  `LOCAL_MODEL_CONTEXT_LENGTH`, or use remote/cloud.
- `LOCAL_MODEL_RUNTIME_ERROR`: check `llama-cpp-python` installation and the
  gateway logs; the Providers page shows the loading error.
- `REMOTE_ENDPOINT_UNAVAILABLE`: the tunnel/session expired — restart the
  notebook server and update `REMOTE_LOCAL_BASE_URL`.
- `REMOTE_MODEL_NOT_FOUND`: the server's `/v1/models` list does not contain
  `REMOTE_LOCAL_MODEL`; check the server's `-m` model id.
