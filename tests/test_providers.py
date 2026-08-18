import asyncio

import httpx
import main
import pytest

from agent.config import settings
from agent.models.registry import ModelRegistry
from agent.providers.anthropic_provider import AnthropicProvider
from agent.providers.discovery import ProviderDiscovery
from agent.providers.errors import (
    InvalidRequestError,
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from agent.providers.gemini_provider import GeminiProvider
from agent.providers.openai_compatible import OpenAICompatibleProvider


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    response = FakeResponse(
        payload={
            'choices': [{
                'message': {'content': 'answer'},
            }],
            'usage': {'prompt_tokens': 2, 'completion_tokens': 3},
        }
    )
    error = None
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response

    async def post(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def install_client(monkeypatch, response=None, error=None):
    FakeClient.instances = []
    FakeClient.response = response or FakeResponse(
        payload={
            'choices': [{
                'message': {'content': 'answer'},
            }],
            'usage': {'prompt_tokens': 2, 'completion_tokens': 3},
        }
    )
    FakeClient.error = error
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)


def test_openai_compatible_uses_configured_timeout(monkeypatch):
    install_client(monkeypatch)
    monkeypatch.setattr(settings, 'provider_timeout_seconds', 17)
    provider = OpenAICompatibleProvider(
        'custom', 'key', 'https://example.test/v1', 'model'
    )

    asyncio.run(provider.complete('hello'))

    assert FakeClient.instances[0].kwargs['timeout'] == 17


@pytest.mark.parametrize(
    ('status', 'exception'),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (404, ModelNotFoundError),
        (429, ProviderRateLimitError),
        (422, InvalidRequestError),
        (500, ProviderUnavailableError),
    ],
)
def test_openai_statuses_use_shared_exceptions(
    monkeypatch, status, exception
):
    install_client(monkeypatch, response=FakeResponse(status))
    provider = OpenAICompatibleProvider(
        'custom', 'key', 'https://example.test/v1', 'model'
    )

    with pytest.raises(exception):
        asyncio.run(provider.complete('hello'))


def test_openai_timeout_is_normalized(monkeypatch):
    install_client(monkeypatch, error=httpx.ReadTimeout('timed out'))
    provider = OpenAICompatibleProvider(
        'custom', 'key', 'https://example.test/v1', 'model'
    )

    with pytest.raises(ProviderTimeoutError):
        asyncio.run(provider.complete('hello'))


def test_openai_malformed_response_is_normalized(monkeypatch):
    install_client(monkeypatch, response=FakeResponse(payload={'choices': []}))
    provider = OpenAICompatibleProvider(
        'custom', 'key', 'https://example.test/v1', 'model'
    )

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(provider.complete('hello'))


def test_native_capability_metadata_respects_vision_policy(monkeypatch):
    monkeypatch.setattr(settings, 'gemini_api_key', 'gemini-key')
    monkeypatch.setattr(settings, 'anthropic_api_key', 'anthropic-key')

    gemini = asyncio.run(GeminiProvider('gemini-model').list_models())[0]
    anthropic = asyncio.run(
        AnthropicProvider('claude-model', supports_vision=True).list_models()
    )[0]

    assert gemini['supports_vision'] is False
    assert 'vision' not in gemini['capabilities']
    assert anthropic['supports_vision'] is True
    assert 'vision' in anthropic['capabilities']


def test_refresh_failed_health_check_returns_diagnostic_and_zero_models(tmp_path, monkeypatch):
    class FailingProvider:
        def configured(self):
            return True

        async def health_check(self):
            raise ProviderAuthenticationError('secret')

        async def list_models(self):
            raise AssertionError('list_models must not run after failed health check')

    registry = ModelRegistry(tmp_path / 'models.db')
    monkeypatch.setattr(
        'agent.providers.discovery.configured_providers',
        lambda: [{'provider': 'openai', 'configured': True, 'enabled': True}],
    )
    monkeypatch.setattr(
        'agent.providers.discovery.get_provider', lambda _name: FailingProvider()
    )

    result = asyncio.run(ProviderDiscovery(registry).refresh('openai'))

    assert result[0]['health_status'] == 'unavailable'
    assert result[0]['models_discovered'] == 0
    assert result[0]['failure_reason'] == 'AUTH_ERROR'
    assert 'API key' in result[0]['failure_message']
    assert registry.list('openai') == []


def test_refresh_success_populates_registry_and_cloud_candidates(tmp_path, monkeypatch):
    class HealthyProvider:
        def configured(self):
            return True

        async def health_check(self):
            return True

        async def list_models(self):
            return [{'model_id': 'verified-model', 'capabilities': ['general']}]

    registry = ModelRegistry(tmp_path / 'models.db')
    monkeypatch.setattr(
        'agent.providers.discovery.configured_providers',
        lambda: [{'provider': 'openai', 'configured': True, 'enabled': True}],
    )
    monkeypatch.setattr(
        'agent.providers.discovery.get_provider', lambda _name: HealthyProvider()
    )
    monkeypatch.setattr(main.settings, 'routing_mode', 'CLOUD_ONLY')
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'default_model': 'verified-model', 'routing_priority': 50},
    )

    result = asyncio.run(ProviderDiscovery(registry).refresh('openai'))
    models = registry.list('openai')
    candidates = main._cloud_candidates('hello', models)

    assert result[0]['health_status'] == 'healthy'
    assert result[0]['models_discovered'] == 1
    assert models[0]['model_id'] == 'verified-model'
    assert any(candidate.provider == 'openai' for candidate in candidates)


def test_refresh_healthy_provider_with_no_models_is_not_ready(tmp_path, monkeypatch):
    class EmptyProvider:
        def configured(self):
            return True

        async def health_check(self):
            return True

        async def list_models(self):
            return []

    registry = ModelRegistry(tmp_path / 'models.db')
    monkeypatch.setattr(
        'agent.providers.discovery.configured_providers',
        lambda: [{'provider': 'openai', 'configured': True, 'enabled': True}],
    )
    monkeypatch.setattr(
        'agent.providers.discovery.get_provider', lambda _name: EmptyProvider()
    )

    result = asyncio.run(ProviderDiscovery(registry).refresh('openai'))

    assert result[0]['health_status'] == 'healthy'
    assert result[0]['models_discovered'] == 0
    assert result[0]['failure_reason'] == 'NO_MODELS'
    assert registry.list('openai') == []


def test_disabled_provider_refresh_invalidates_cached_healthy_models(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path / 'models.db')
    registry.upsert({
        'provider': 'nvidia', 'model_id': 'model-a', 'availability': 'verified',
        'health_status': 'healthy', 'capabilities': ['general'],
    })
    monkeypatch.setattr(
        'agent.providers.discovery.configured_providers',
        lambda: [{'provider': 'nvidia', 'configured': True, 'enabled': False}],
    )

    result = asyncio.run(ProviderDiscovery(registry).refresh('nvidia'))

    assert result == [{
        'provider': 'nvidia', 'health_status': 'disabled', 'models_discovered': 0,
        'failure_reason': 'PROVIDER_DISABLED',
        'failure_message': 'The provider is disabled.',
    }]
    cached = registry.list('nvidia')[0]
    assert cached['health_status'] == 'disabled'
    assert cached['availability'] == 'disabled'


def test_native_multimodal_rejects_disabled_vision(monkeypatch):
    monkeypatch.setattr(settings, 'gemini_api_key', 'gemini-key')
    monkeypatch.setattr(settings, 'anthropic_api_key', 'anthropic-key')
    image = [{'media_type': 'image/png', 'data_base64': 'aW1hZ2U='}]

    with pytest.raises(ProviderError):
        asyncio.run(GeminiProvider('gemini-model').complete_multimodal('look', image))
    with pytest.raises(ProviderError):
        asyncio.run(AnthropicProvider('claude-model').complete_multimodal('look', image))
