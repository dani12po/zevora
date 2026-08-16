"""OpenAI-compatible local endpoint adapter."""
from urllib.parse import urlparse

import httpx

from ..config import settings
from .base import AIProvider
from .errors import ProviderUnavailableError
from .local_intelligence import LocalProviderMetadata


class LocalEndpointProvider(AIProvider):
    name = 'local'
    provider_id = 'openai-compatible-local'

    def __init__(self, model_id: str | None = None, base_url: str | None = None):
        self.default_model = model_id or settings.local_model_name
        self.base_url = (base_url or settings.local_endpoint_url).rstrip('/')
        self.supports_vision = False

    def configured(self) -> bool:
        parsed = urlparse(self.base_url)
        return bool(settings.local_model_enabled and parsed.scheme in {'http', 'https'} and parsed.hostname)

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {settings.local_endpoint_api_key}'} if settings.local_endpoint_api_key else {}

    async def health_check(self) -> bool:
        if not self.configured():
            return False
        try:
            async with httpx.AsyncClient(timeout=min(settings.local_endpoint_timeout_seconds, 10)) as client:
                response = await client.get(f'{self.base_url}/models', headers=self._headers())
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def health(self) -> bool:
        return await self.health_check()

    async def list_models(self) -> list[dict]:
        if not await self.health_check():
            return []
        try:
            async with httpx.AsyncClient(timeout=settings.local_endpoint_timeout_seconds) as client:
                response = await client.get(f'{self.base_url}/models', headers=self._headers())
                response.raise_for_status()
            return [{
                'model_id': item.get('id'),
                'display_name': item.get('id'),
                'capabilities': ['text', 'local', 'private'],
                'availability': 'verified',
                'health_status': 'healthy',
                'runtime': 'openai-compatible',
            } for item in response.json().get('data', []) if item.get('id')]
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise ProviderUnavailableError(f'local endpoint model discovery failed: {type(error).__name__}') from error

    async def complete(self, prompt: str, system: str = '') -> tuple[str, dict]:
        return await self.complete_for_model(prompt, system, self.default_model)

    async def complete_for_model(self, prompt: str, system: str = '', model_id: str = ''):
        payload = {
            'model': model_id or self.default_model,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
            'stream': False,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.local_endpoint_timeout_seconds) as client:
                response = await client.post(f'{self.base_url}/chat/completions', headers=self._headers(), json=payload)
                response.raise_for_status()
            data = response.json()
            choice = (data.get('choices') or [{}])[0]
            usage = data.get('usage') or {}
            return str(choice.get('message', {}).get('content', '')).strip(), {
                'input_tokens': int(usage.get('prompt_tokens') or 0),
                'output_tokens': int(usage.get('completion_tokens') or 0),
            }
        except (httpx.HTTPError, ValueError, TypeError, IndexError) as error:
            raise ProviderUnavailableError(f'local endpoint generation failed: {type(error).__name__}') from error

    def capabilities(self) -> set[str]:
        return {'text', 'local', 'private'}

    def metadata(self) -> LocalProviderMetadata:
        return LocalProviderMetadata(
            provider_id=self.provider_id,
            name='OpenAI-Compatible Local Intelligence',
            model_id=self.default_model,
            capabilities=frozenset(self.capabilities()),
            runtime='openai-compatible',
            installed=self.configured(),
        )
