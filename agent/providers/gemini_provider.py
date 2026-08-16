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


class GeminiProvider(AIProvider):
    """Native Gemini REST provider; configured through env and provider policy."""

    name = 'gemini'

    def __init__(self, default_model=None, supports_vision=False):
        self.default_model = default_model or settings.gemini_model
        self.supports_vision = bool(supports_vision)

    def configured(self):
        return bool(settings.gemini_api_key)

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
        return await self._generate([{'text': prompt}], system)

    async def complete_multimodal(self, prompt, images, system='', model_id=''):
        if not self.supports_vision:
            raise ProviderError('gemini does not support image input')
        parts = [{'text': prompt}]
        parts.extend({
            'inline_data': {
                'mime_type': image['media_type'],
                'data': image['data_base64'],
            }
        } for image in images)
        return await self._generate(parts, system, model_id or self.default_model)

    async def _generate(self, parts, system='', model_id=''):
        if not self.configured():
            raise ProviderAuthenticationError(
                'gemini is not configured'
            )
        selected = model_id or self.default_model
        if not selected:
            raise ModelNotFoundError('gemini model is not configured')
        payload = {'contents': [{'parts': parts}]}
        if system:
            payload['system_instruction'] = {'parts': [{'text': system}]}
        url = (
            'https://generativelanguage.googleapis.com/v1beta/models/'
            f'{selected}:generateContent?key={settings.gemini_api_key}'
        )
        try:
            async with httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as client:
                response = await client.post(url, json=payload)
                raise_for_response(self.name, response)
                data = response.json()
            usage = data.get('usageMetadata', {})
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text, {
                'input_tokens': usage.get('promptTokenCount'),
                'output_tokens': usage.get('candidatesTokenCount'),
            }
        except Exception as error:
            mapped = map_http_error(self.name, error)
            raise mapped from error
