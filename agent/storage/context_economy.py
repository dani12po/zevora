"""Bounded context assembly with privacy-safe token accounting."""
from dataclasses import dataclass
import hashlib
import re
from typing import Iterable

from .context_compressor import compress_context


_TOKEN_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Conservative, dependency-free estimate used before provider accounting."""
    return len(_TOKEN_RE.findall(text or ""))


def _fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "ignore")).hexdigest()


@dataclass(frozen=True)
class ContextEconomyResult:
    text: str
    estimated_context_tokens: int
    compressed_tokens: int
    removed_tokens: int
    provider_tokens: int
    cache_saved_tokens: int
    source_count: int
    deduplicated_count: int
    context_hash: str

    def metrics(self) -> dict:
        return {
            "estimated_context_tokens": self.estimated_context_tokens,
            "compressed_tokens": self.compressed_tokens,
            "removed_tokens": self.removed_tokens,
            "provider_tokens": self.provider_tokens,
            "cache_saved_tokens": self.cache_saved_tokens,
            "source_count": self.source_count,
            "deduplicated_count": self.deduplicated_count,
            "context_hash": self.context_hash,
        }


def build_context(
    sections: Iterable[str],
    *,
    max_tokens: int = 12000,
    provider_tokens: int = 0,
    cache_saved_tokens: int = 0,
) -> ContextEconomyResult:
    items = [str(section) for section in sections if str(section).strip()]
    original = sum(estimate_tokens(item) for item in items)
    max_chars = max(256, int(max_tokens) * 4)
    compressed = compress_context(items, max_chars=max_chars)
    text = compressed["text"]
    compressed_tokens = min(estimate_tokens(text), max(0, int(max_tokens)))
    # The compressor removes duplicate lines and truncates at the configured budget.
    removed = max(0, original - compressed_tokens)
    return ContextEconomyResult(
        text=text,
        estimated_context_tokens=original,
        compressed_tokens=compressed_tokens,
        removed_tokens=removed,
        provider_tokens=max(0, int(provider_tokens)),
        cache_saved_tokens=max(0, int(cache_saved_tokens)),
        source_count=len(items),
        deduplicated_count=max(0, sum(len(item.splitlines()) for item in items) - compressed["retained_lines"]),
        context_hash=_fingerprint(text),
    )
