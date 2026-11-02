"""Collective registry provider contracts."""
from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Any

import httpx


class CollectiveRegistry(ABC):
    @abstractmethod
    async def publish(self, contributions: list[dict[str, Any]]) -> dict: ...


class LocalOnlyRegistry(CollectiveRegistry):
    def __init__(self, destination: Path):
        self.destination = destination

    async def publish(self, contributions: list[dict[str, Any]]) -> dict:
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.write_text(json.dumps(contributions, sort_keys=True, indent=2), encoding='utf-8')
        return {'published': len(contributions), 'registry': 'local-only'}


class HTTPRegistry(CollectiveRegistry):
    def __init__(self, endpoint: str, timeout: int = 30):
        self.endpoint = endpoint
        self.timeout = timeout

    async def publish(self, contributions: list[dict[str, Any]]) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.endpoint, json={'contributions': contributions})
            response.raise_for_status()
        return {'published': len(contributions), 'registry': 'http'}


class GitHubRegistry(HTTPRegistry):
    """GitHub release/API adapter; never stores raw local user data."""

    async def publish(self, contributions: list[dict[str, Any]]) -> dict:
        result = await super().publish(contributions)
        result['registry'] = 'github-release'
        return result
