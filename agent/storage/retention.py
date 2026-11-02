from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

EPHEMERAL_CACHE = "ephemeral_cache"
PROVIDER_CONFIG_CACHE = "provider_config_cache"


@dataclass(frozen=True)
class RetentionCandidate:
    path: Path
    reason: str
    size_bytes: int


def expired_files(root: Path, days: float, now=None) -> list[RetentionCandidate]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    result = []
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        if datetime.fromtimestamp(stat.st_mtime, timezone.utc) < cutoff:
            result.append(RetentionCandidate(path, f"older than {days:g} days", stat.st_size))
    return result


def expired_cache_files(cache_root: Path, days: float, now=None) -> list[RetentionCandidate]:
    """Return only TTL-managed cache files; provider configuration is persistent."""
    return expired_files(cache_root / EPHEMERAL_CACHE, days, now=now)
