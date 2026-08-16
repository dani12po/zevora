"""Ollama adapter implementing the local intelligence contract."""
from urllib.parse import urlparse

import httpx

from ..config import settings
from .base import AIProvider
from .errors import ProviderUnavailableError
from .local_intelligence import LocalProviderMetadata, messages_to_prompt


class OllamaLocalProvider(AIProvider):
    name = 'local'
    provider_id = 'ollama'

    def __init__(self, model_id: str | None = None, base_url: str | None = None):
        self.model_id = model_id or settings.local_model_name
        self.base_url = (base_url or settings.local_endpoint_url).rstrip('/')
        self.default_model = self.model_id
        self.supports_vision = False

    def configured(self) -> bool:
        parsed = urlparse(self.base_url)
        return bool(settings.local_model_enabled and parsed.scheme in {'http', 'https'} and parsed.hostname)

    async def health_check(self) -> bool:
        if not self.configured():
            return False
        try:
            async with httpx.AsyncClient(timeout=min(settings.local_endpoint_timeout_seconds, 10)) as client:
                response = await client.get(f'{self.base_url}/api/tags')
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def health(self) -> bool:
        return await self.health_check()

    async def list_models(self) -> list[dict]:
        if not await self.health_check():
            return []
        async with httpx.AsyncClient(timeout=settings.local_endpoint_timeout_seconds) as client:
            response = await client.get(f'{self.base_url}/api/tags')
            response.raise_for_status()
        models = response.json().get('models', [])
        return [{
            'model_id': item.get('name'),
            'display_name': item.get('name'),
            'capabilities': ['text', 'local', 'private'],
            'availability': 'verified',
            'health_status': 'healthy',
            'runtime': 'ollama',
            'size_bytes': item.get('size'),
        } for item in models if item.get('name')]

    async def generate(self, messages: list[dict[str, str]], **kwargs) -> tuple[str, dict]:
        if not self.configured():
            raise ProviderUnavailableError('Ollama local provider is not configured')
        payload = {'model': kwargs.get('model_id') or self.model_id, 'messages': messages, 'stream': False}
        try:
            async with httpx.AsyncClient(timeout=settings.local_endpoint_timeout_seconds) as client:
                response = await client.post(f'{self.base_url}/api/chat', json=payload)
                response.raise_for_status()
            data = response.json()
            return str(data.get('message', {}).get('content', '')).strip(), {
                'input_tokens': int(data.get('prompt_eval_count') or 0),
                'output_tokens': int(data.get('eval_count') or 0),
            }
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise ProviderUnavailableError(f'Ollama local generation failed: {type(error).__name__}') from error

    async def complete(self, prompt: str, system: str = '') -> tuple[str, dict]:
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
        return await self.generate(messages)

    async def complete_for_model(self, prompt: str, system: str = '', model_id: str = ''):
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
        return await self.generate(messages, model_id=model_id or self.model_id)

    def capabilities(self) -> set[str]:
        return {'text', 'local', 'private'}

    def metadata(self) -> LocalProviderMetadata:
        return LocalProviderMetadata(
            provider_id=self.provider_id,
            name='Ollama Local Intelligence',
            model_id=self.model_id,
            capabilities=frozenset(self.capabilities()),
            runtime='ollama',
            installed=self.configured(),
        )
