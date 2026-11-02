"""Download the Lexi Q5_K_M GGUF for embedded local inference.

Usage (from repo root):
    .venv\\Scripts\\python.exe scripts/download_lexi.py [--replace]

Downloads ONLY the single selected GGUF file (~5.73 GB) with resume,
size/SHA-256 verification, and atomic install. Never silently overwrites.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import settings
from agent.models.manager import LocalIntelligenceManager

_started = time.monotonic()
_last_print = 0.0


def progress(done: int, total: int) -> None:
    global _last_print
    now = time.monotonic()
    if now - _last_print < 5 and done != total:
        return
    _last_print = now
    elapsed = max(now - _started, 0.1)
    speed = done / elapsed / 1024 / 1024
    if total:
        pct = done / total * 100
        print(
            f'[{elapsed:7.0f}s] {done / 1024 / 1024:8.1f} / {total / 1024 / 1024:8.1f} MiB '
            f'({pct:5.1f}%) @ {speed:5.1f} MiB/s',
            flush=True,
        )
    else:
        print(f'[{elapsed:7.0f}s] {done / 1024 / 1024:8.1f} MiB @ {speed:5.1f} MiB/s', flush=True)


def main() -> int:
    replace = '--replace' in sys.argv[1:]
    profile = settings.active_local_model_profile
    print(f'repository : {profile.repository}', flush=True)
    print(f'filename   : {profile.filename}', flush=True)
    print(f'dest       : {settings.local_model_file}', flush=True)
    print(f'replace    : {replace}', flush=True)
    try:
        result = LocalIntelligenceManager().install_model(
            replace=replace, progress_cb=progress, timeout_seconds=600,
        )
    except Exception as error:
        print(f'DOWNLOAD FAILED: {type(error).__name__}: {error}', flush=True)
        return 1
    print(f'DOWNLOAD OK: {result["bytes"] / 1024 / 1024:.1f} MiB -> {result["path"]}', flush=True)
    print(f'sha256: {result["sha256"]}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
