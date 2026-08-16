import logging

import httpx

from ..config import settings
from .base import AIProvider
from .errors import (
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderError,
    map_http_error,
    raise_for_response,
)


logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    name = 'anthropic'

    def __init__(self, default_model=None, supports_vision=False):
        self.default_model = default_model or settings.anthropic_model
        self.supports_vision = bool(supports_vision)

    def configured(self):
        return bool(settings.anthropic_api_key)

    async def health_check(self):
        if not self.configured():
            return False
        try:
            await self.list_models()
            return True
        except Exception as error:
            logger.warning("Provider health check failed for %s: %s", self.name, type(error).__name__)
            return False

    async def list_models(self):
        if not self.configured():
            return []
        return [{
            'model_id': self.default_model,
            'display_name': self.default_model,
            'capabilities': [
                'general', 'coding', 'reasoning',
                *(['vision'] if self.supports_vision else []),
            ],
            'supports_vision': self.supports_vision,
            'availability': 'verified',
        }]

    async def complete(self, prompt, system=''):
        return await self._message(prompt, system, self.default_model)

    async def complete_multimodal(self, prompt, images, system='', model_id=''):
        if not self.supports_vision:
            raise ProviderError('anthropic does not support image input')
        content = [{
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': image['media_type'],
                'data': image['data_base64'],
            },
        } for image in images]
        content.append({'type': 'text', 'text': prompt})
        return await self._message(content, system, model_id or self.default_model)

    async def _message(self, content, system='', model_id=''):
        if not self.configured():
            raise ProviderAuthenticationError(
                'anthropic is not configured'
            )
        selected = model_id or self.default_model
        if not selected:
            raise ModelNotFoundError('anthropic model is not configured')
        headers = {
            'x-api-key': settings.anthropic_api_key,
            'anthropic-version': '2023-06-01',
        }
        payload = {
            'model': selected,
            'max_tokens': 2048,
            'system': system,
            'messages': [{'role': 'user', 'content': content}],
        }
        try:
            async with httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as client:
                response = await client.post(
                    f'{settings.anthropic_base_url.rstrip("/")}/v1/messages',
                    headers=headers,
                    json=payload,
                )
                raise_for_response(self.name, response)
                data = response.json()
            text = ''.join(
                part['text'] for part in data['content']
                if part['type'] == 'text'
            )
            return text, data.get('usage', {})
        except Exception as error:
            mapped = map_http_error(self.name, error)
            raise mapped from error
