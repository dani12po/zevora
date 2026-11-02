"""Provider-agnostic local intelligence contract and adapter helpers."""
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class LocalProviderMetadata:
    provider_id: str
    name: str
    model_id: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    runtime: str = "unknown"
    context_length: int | None = None
    installed: bool = False
    version: str | None = None


@runtime_checkable
class LocalIntelligenceProvider(Protocol):
    """Common contract; each adapter owns its runtime and lifecycle."""

    provider_id: str
    name: str
    model_id: str

    async def health(self) -> bool: ...
    async def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, dict]: ...
    def capabilities(self) -> set[str]: ...
    def metadata(self) -> LocalProviderMetadata: ...


def messages_to_prompt(messages: list[dict[str, str]]) -> tuple[str, str]:
    """Extract a bounded system/user pair for adapters with chat APIs."""
    system = "\n\n".join(
        str(item.get("content", "")) for item in messages if item.get("role") == "system"
    )
    user = "\n\n".join(
        str(item.get("content", "")) for item in messages if item.get("role") != "system"
    )
    return user, system
