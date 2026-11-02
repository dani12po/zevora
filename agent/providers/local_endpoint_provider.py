"""Remote Lexi backend: generic OpenAI-compatible llama.cpp adapter.

Deployment identity is ``local_remote`` — Lexi GGUF running in an EXTERNAL
llama.cpp server (Colab, Kaggle, self-hosted GPU, or any compatible endpoint).
This extends the existing adapter rather than duplicating provider
infrastructure. Only BASE_URL + MODEL_ID (+ optional API key) are required;
the architecture never depends on one hosting vendor or tunnel service.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..config import settings
from .base import AIProvider
from .errors import ProviderUnavailableError, map_http_error
from .local_intelligence import LocalProviderMetadata

logger = logging.getLogger(__name__)

# Health state cache so routine checks stay cheap (Phase 22). Keyed by
# (base_url, model) because provider instances are constructed per call.
_HEALTH_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
HEALTH_CACHE_TTL_SECONDS = 30.0

# Last observed remote endpoint state for the provider UI (Phase 17).
_ENDPOINT_STATE: dict = {
    'last_check': None,
    'last_success': None,
    'last_latency_ms': None,
    'last_error': None,
}


def reset_remote_health_cache() -> None:
    """Clear cached remote health (primarily useful for tests)."""
    _HEALTH_CACHE.clear()


def remote_endpoint_status() -> dict:
    """Bounded remote Lexi connection report for UI/health surfaces."""
    return {
        'deployment': 'remote',
        'runtime': 'llamacpp',
        'protocol': 'openai-compatible',
        'enabled': settings.remote_local_enabled,
        'base_url': settings.remote_local_base_url or None,
        'model_id': settings.remote_local_model,
        'streaming': settings.remote_local_streaming,
        'timeout_seconds': settings.remote_local_timeout_seconds,
        'health_check_timeout_seconds': settings.remote_local_health_check_timeout_seconds,
        **_ENDPOINT_STATE,
    }


class LocalEndpointProvider(AIProvider):
    """OpenAI-compatible remote Lexi adapter (deployment ``local_remote``)."""

    name = 'local_remote'
    provider_id = 'local_remote'

    def __init__(self, model_id: str | None = None, base_url: str | None = None):
        self.default_model = (
            model_id or settings.remote_local_model or settings.local_model_name
        )
        configured_base = (
            base_url or settings.remote_local_base_url or settings.local_endpoint_url
        )
        self.base_url = configured_base.rstrip('/')
        self.supports_vision = False

    # ── Configuration ──────────────────────────────────────────────────────
    def _validate_base_url(self) -> tuple[str, str | None]:
        """Validate the user-configured endpoint without SSRF-bypassing cloud guards.

        Only explicit http/https URLs with a host are accepted. Loopback and
        private hosts are allowed here because this adapter serves EXPLICITLY
        user-configured local endpoints (loopback dev servers included); the
        strict cloud SSRF guard intentionally does not apply. Cloud
        instance-metadata addresses stay blocked — no model server lives there.
        Nothing is logged with credentials.
        """
        from .ssrf import assert_local_endpoint_url

        try:
            return assert_local_endpoint_url(self.base_url), None
        except ValueError as error:
            return '', str(error)

    def configured(self) -> bool:
        base_url, problem = self._validate_base_url()
        return bool(
            base_url
            and (settings.remote_local_enabled or settings.local_model_enabled)
            and not problem
        )

    def _headers(self) -> dict[str, str]:
        api_key = settings.remote_local_api_key or settings.local_endpoint_api_key
        return {'Authorization': f'Bearer {api_key}'} if api_key else {}

    @property
    def _timeout(self) -> int:
        return max(1, settings.remote_local_timeout_seconds)

    @property
    def _health_timeout(self) -> int:
        return max(
            1,
            min(settings.remote_local_health_check_timeout_seconds, self._timeout),
        )

    # ── Health (cached, cheap) ─────────────────────────────────────────────
    async def health_check(self) -> bool:
        if not self.configured():
            return False
        cache_key = (self.base_url, self.default_model)
        cached = _HEALTH_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < HEALTH_CACHE_TTL_SECONDS:
            return cached[1]
        started = time.monotonic()
        _ENDPOINT_STATE['last_check'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        try:
            async with httpx.AsyncClient(timeout=self._health_timeout) as client:
                response = await client.get(f'{self.base_url}/models', headers=self._headers())
            healthy = response.status_code == 200 and self._model_present(response)
        except (httpx.HTTPError, ValueError):
            healthy = False
        latency_ms = int((time.monotonic() - started) * 1000)
        _ENDPOINT_STATE['last_latency_ms'] = latency_ms
        if healthy:
            _ENDPOINT_STATE['last_success'] = _ENDPOINT_STATE['last_check']
            _ENDPOINT_STATE['last_error'] = None
        else:
            _ENDPOINT_STATE['last_error'] = 'REMOTE_ENDPOINT_UNAVAILABLE'
        _HEALTH_CACHE[cache_key] = (time.monotonic(), healthy)
        return healthy

    def _model_present(self, response: httpx.Response) -> bool:
        """Confirm the requested model exists when the server lists models."""
        try:
            items = response.json().get('data', [])
        except ValueError:
            return True  # reachable endpoint; do not fail closed on odd payloads
        ids = {str(item.get('id') or '') for item in items if isinstance(item, dict)}
        if not ids:
            return True
        return self.default_model in ids

    async def health(self) -> dict:
        """Detailed remote health for diagnostics (never performs generation)."""
        healthy = await self.health_check()
        return {**remote_endpoint_status(), 'healthy': healthy}

    # ── Models / generation ────────────────────────────────────────────────
    async def list_models(self) -> list[dict]:
        if not await self.health_check():
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f'{self.base_url}/models', headers=self._headers())
                response.raise_for_status()
            profile = settings.active_local_model_profile
            models = []
            for item in response.json().get('data', []):
                model_id = item.get('id')
                if not model_id:
                    continue
                models.append({
                    'model_id': model_id,
                    'display_name': model_id,
                    'deployment': 'remote',
                    'runtime': profile.runtime,
                    'protocol': 'openai-compatible',
                    'capabilities': [
                        'general', 'coding', 'reasoning', 'tool_use', 'json',
                        'local', 'private',
                    ],
                    'capability_profile': {
                        'instruction_score': .90,
                        'coding_score': .86,
                        'reasoning_score': .84,
                    },
                    'context_window': profile.context_length,
                    'max_output_tokens': profile.max_output_tokens,
                    'supports_streaming': settings.remote_local_streaming,
                    'supports_tools': True,
                    'supports_vision': False,
                    'supports_reasoning': True,
                    'supports_code': True,
                    'supports_json': True,
                    'input_price': 0,
                    'output_price': 0,
                    'availability': 'verified',
                    'health_status': 'healthy',
                })
            return models
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            raise ProviderUnavailableError(
                f'local remote model discovery failed: {type(error).__name__}'
            ) from error

    async def complete(self, prompt: str, system: str = '') -> tuple[str, dict]:
        return await self.complete_for_model(prompt, system, self.default_model)

    async def complete_for_model(self, prompt: str, system: str = '', model_id: str = ''):
        profile = settings.active_local_model_profile
        payload = {
            'model': model_id or self.default_model,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
            'max_tokens': profile.max_output_tokens,
            'temperature': profile.temperature,
            'stream': False,
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f'{self.base_url}/chat/completions', headers=self._headers(), json=payload
                )
                if response.status_code in {401, 403, 404, 429} or response.status_code >= 400:
                    from .errors import raise_for_response
                    raise_for_response('local_remote', response)
            data = response.json()
            choice = (data.get('choices') or [{}])[0]
            usage = data.get('usage') or {}
            _ENDPOINT_STATE['last_success'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            _ENDPOINT_STATE['last_error'] = None
            return str(choice.get('message', {}).get('content', '')).strip(), {
                'input_tokens': int(usage.get('prompt_tokens') or 0),
                'output_tokens': int(usage.get('completion_tokens') or 0),
                'latency_ms': int((time.monotonic() - started) * 1000),
            }
        except ProviderUnavailableError:
            raise
        except Exception as error:
            raise map_http_error('local_remote', error) from error

    async def stream(self, prompt: str, system: str = ''):
        """SSE streaming when the server supports it, else buffered fallback."""
        if not settings.remote_local_streaming:
            response, _usage = await self.complete(prompt, system)
            yield response
            return
        profile = settings.active_local_model_profile
        payload = {
            'model': self.default_model,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
            'max_tokens': profile.max_output_tokens,
            'temperature': profile.temperature,
            'stream': True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    'POST', f'{self.base_url}/chat/completions',
                    headers=self._headers(), json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        text = line.strip()
                        if not text.startswith('data:'):
                            continue
                        data = text[5:].strip()
                        if data == '[DONE]':
                            return
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            continue
                        choices = chunk.get('choices') or []
                        delta = (choices[0].get('delta') or {}) if choices else {}
                        content = delta.get('content')
                        if content:
                            yield content
                        if choices and choices[0].get('finish_reason'):
                            return
        except Exception as error:
            logger.info('local_remote_streaming_fallback reason=%s', type(error).__name__)
            response, _usage = await self.complete(prompt, system)
            yield response

    def capabilities(self) -> set[str]:
        return {'text', 'general', 'coding', 'reasoning', 'tool_use', 'json', 'local', 'private'}

    def metadata(self) -> LocalProviderMetadata:
        return LocalProviderMetadata(
            provider_id=self.provider_id,
            name='Remote Lexi (OpenAI-Compatible)',
            model_id=self.default_model,
            capabilities=frozenset(self.capabilities()),
            runtime='llamacpp',
            context_length=settings.active_local_model_profile.context_length,
            installed=self.configured(),
        )
