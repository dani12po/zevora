import re

import logging

import httpx

from ..config import settings
from .base import AIProvider
from .errors import (
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderTimeoutError,
    map_http_error,
    raise_for_response,
)


logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self,
        name,
        api_key,
        base_url,
        default_model='',
        supports_vision=False,
    ):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.default_model = default_model
        self.supports_vision = bool(supports_vision)

    def configured(self):
        return bool(self.api_key)

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    @staticmethod
    def _supports_chat(model_id):
        """Reject catalog entries that clearly target a non-chat endpoint."""
        blocked = re.compile(
            r'(^|[/_.-])(embed(?:ding|qa)?|rerank(?:qa)?|retrieval|moderation|'
            r'guard|safety|shield|detector|classifier|ocr|tts|stt|asr|'
            r'whisper|translat(?:e|ion))',
            re.IGNORECASE,
        )
        return not blocked.search(model_id)

    async def health_check(self):
        if not self.configured():
            return False
        try:
            async with httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as client:
                response = await client.get(
                    f'{self.base_url}/models', headers=self._headers()
                )
                raise_for_response(self.name, response)
            return True
        except ProviderError:
            return False
        except Exception as error:
            logger.warning("Provider health check failed for %s: %s", self.name, type(error).__name__)
            return False

    async def list_models(self):
        if not self.configured():
            return []
        try:
            async with httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as client:
                response = await client.get(
                    f'{self.base_url}/models', headers=self._headers()
                )
                raise_for_response(self.name, response)
                data = response.json()
            model_ids = [
                item.get('id')
                for item in data.get('data', [])
                if item.get('id') and self._supports_chat(item['id'])
            ]
            if self.default_model and self.default_model not in model_ids:
                model_ids.insert(0, self.default_model)
            capabilities = ['general', 'coding', 'reasoning']
            if self.supports_vision:
                capabilities.append('vision')
            return [
                {
                    'model_id': model_id,
                    'display_name': model_id,
                    'capabilities': list(capabilities),
                    'supports_vision': self.supports_vision,
                    'availability': 'verified',
                }
                for model_id in model_ids
            ]
        except Exception as error:
            mapped = map_http_error(self.name, error)
            raise mapped from error

    async def complete(self, prompt, system=''):
        return await self.complete_for_model(prompt, system, self.default_model)

    async def complete_for_model(self, prompt, system='', model_id=''):
        if not self.configured():
            raise ProviderAuthenticationError(f'{self.name} is not configured')
        if not model_id:
            raise ModelNotFoundError(f'{self.name} model is not configured')
        payload = {
            'model': model_id,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ],
        }
        return await self._post_completion(payload)

    async def complete_multimodal(self, prompt, images, system='', model_id=''):
        model_id = model_id or self.default_model
        if not self.configured():
            raise ProviderAuthenticationError(f'{self.name} is not configured')
        if not model_id:
            raise ModelNotFoundError(f'{self.name} model is not configured')
        if not self.supports_vision:
            raise ProviderError(f'{self.name} does not support image input')
        content = [{'type': 'text', 'text': prompt}]
        content.extend(
            {
                'type': 'image_url',
                'image_url': {
                    'url': (
                        f"data:{image['media_type']};base64,"
                        f"{image['data_base64']}"
                    )
                },
            }
            for image in images
        )
        payload = {
            'model': model_id,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': content},
            ],
        }
        return await self._post_completion(payload)

    async def _post_completion(self, payload):
        try:
            async with httpx.AsyncClient(
                timeout=settings.provider_timeout_seconds
            ) as client:
                response = await client.post(
                    f'{self.base_url}/chat/completions',
                    headers=self._headers(),
                    json=payload,
                )
                raise_for_response(self.name, response)
                data = response.json()
            return data['choices'][0]['message']['content'], data.get('usage', {})
        except Exception as error:
            mapped = map_http_error(self.name, error)
            raise mapped from error
