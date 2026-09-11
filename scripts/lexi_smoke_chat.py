"""Smoke-test embedded Lexi: resource preflight -> load -> short chat.

Usage (from repo root):
    .venv\\Scripts\\python.exe scripts/lexi_smoke_chat.py ["prompt here"]

Loads the GGUF through the existing LocalProvider (llama.cpp), runs one
short generation, and prints status + timing. CPU inference on 8B is slow
(single-digit tok/s); the prompt is kept short on purpose.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import settings
from agent.providers.local_provider import (
    LocalProvider,
    check_local_resources,
    local_runtime_status,
)


async def main() -> int:
    prompt = ' '.join(sys.argv[1:]) or 'Reply with exactly: Lexi local OK'
    profile = settings.active_local_model_profile
    print(f'model    : {profile.model_id} ({profile.filename})', flush=True)
    print(f'path     : {settings.local_model_file}', flush=True)
    print(f'exists   : {settings.local_model_file.is_file()}', flush=True)

    try:
        resources = check_local_resources(settings.local_model_file)
    except Exception as error:
        print(f'PREFLIGHT  : BLOCKED {type(error).__name__}: {error}', flush=True)
        print('TIP: free RAM (close heavy apps) or lower LOCAL_MODEL_CONTEXT_LENGTH, then retry.', flush=True)
        return 2
    print(
        f'preflight: model={resources["model_bytes"] // 1024 // 1024}MiB '
        f'required~{resources["required_bytes"] // 1024 // 1024}MiB '
        f'avail={resources["available_bytes"] // 1024 // 1024}MiB '
        f'gpu_layers={resources["gpu_layers"]}',
        flush=True,
    )

    provider = LocalProvider()
    started = time.monotonic()
    try:
        text, usage = await provider.complete(prompt)
    except Exception as error:
        print(f'GENERATE : FAILED {type(error).__name__}: {str(error)[:300]}', flush=True)
        return 1
    elapsed = time.monotonic() - started
    print(f'answer   : {text[:500]}', flush=True)
    print(f'usage    : {usage}', flush=True)
    print(f'elapsed  : {elapsed:.1f}s (includes one-time model load)', flush=True)
    status = local_runtime_status()
    print(
        f'status   : state={status["state"]} loaded={status["loaded"]} '
        f'load_seconds={status["load_seconds"]} rss_delta_mb={status["load_delta_mb"]}',
        flush=True,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
