# Install and Run ZEVORA

## Requirements

- Python 3.11, 3.12, or 3.13
- The bundled GGUF at `models/zevora-4b-thinking.gguf`
- `llama-cpp-python` for local inference
- Cloud API keys are optional and enable cloud-first complex work and fallback
- CPU inference works without Ollama; GPU offload is optional

## Quick Start (Windows)

```powershell
git clone <ZEVORA_GITHUB_REPOSITORY>
cd ZEVORA
python bootstrap.py
zevora
```

Choose `1` to start the gateway and `5` to open the Web UI at `http://127.0.0.1:7432`.
Use `4` to run in the background after the controller closes.
Use `2` for graceful shutdown.

If the `zevora` command is not available after bootstrap (PATH not refreshed), use:

```powershell
python launcher.py
```

## Local Runtime

The gateway does not load the GGUF during startup. The first eligible local
request loads it through llama.cpp and the Providers page reports loaded state,
process RSS, model size, context, and load delta. Local runtime selection is
provider-agnostic:

- `LOCAL_MODEL_RUNTIME=llamacpp` uses the bundled GGUF adapter.
- `LOCAL_MODEL_RUNTIME=ollama` uses the local Ollama `/api/chat` adapter.
- `LOCAL_MODEL_RUNTIME=openai-compatible` uses a local `/v1/chat/completions` endpoint.

Ollama and endpoint adapters do not require cloud API keys. The model registry
records only discovered metadata and explicit capability values; unknown
capabilities remain unknown.

On Windows, install the prebuilt CPU runtime inside the project virtual
environment. The extra index avoids requiring Visual C++ Build Tools:

```powershell
.venv\Scripts\python.exe -m pip install --prefer-binary "llama-cpp-python>=0.3.14,<0.4" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

For GPU acceleration, use the CUDA wheel documented by `llama-cpp-python` and
set `LOCAL_MODEL_GPU_LAYERS` for the hardware available. If no compatible wheel
exists, install Visual C++ Build Tools and follow the upstream Windows source
build instructions. The gateway can still start without the package, but local
status remains unavailable until it is installed.

## Configuration

Copy `.env.example` to `.env`. Local inference needs no API key. Add a cloud
key only when cloud capacity or cloud fallback is desired:

```dotenv
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
# or any other supported provider
```

Open `http://127.0.0.1:7432/providers` to configure keys via the dashboard.

API keys are stored only in `.env`. They are never written to the database,
logs, cache, or shown in the UI.

## Privacy, Evolution, And Updates

Collective learning is disabled by default. Enable it only after reviewing the
per-type consent settings (`COLLECTIVE_CONSENT_SKILLS`, `COLLECTIVE_CONSENT_KNOWLEDGE`,
`COLLECTIVE_CONSENT_ROUTING`, and `COLLECTIVE_CONSENT_EVALUATION`). Contributions
are sanitized and publication still requires explicit approval. API keys never
enter memory, cache, knowledge, experience, telemetry, contributions, or GitHub.

Verified updates require an HTTPS or local file manifest with component versions,
compatibility, sizes, and SHA-256 hashes. Components are staged, checked, atomically
activated, backed up, and rollback-capable. Downloaded artifacts are never executed.

Inspect runtime state with:

```powershell
zevora intelligence
```

Preview managed local-package removal with `zevora uninstall-local`; add
`--approve` only when the reported package path is correct. External model files
are preserved.

## First Run Without A Cloud Key

If no cloud API key is configured, the gateway starts normally and uses the local
model when its runtime and GGUF are ready. The dashboard shows local readiness
in Providers. Filesystem, memory, cache, and project features remain available
when neither local nor cloud inference is ready.

Project indexing, filesystem browsing, memory, cache, and local inference work
offline when the llama.cpp runtime and bundled GGUF are ready. Cloud providers
are used only when configured and selected by routing.
