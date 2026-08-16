import json
from ..config import settings, ROOT
from .configuration import ProviderStore
from .credentials import CredentialResolver
from .manifest_provider import ManifestProvider
from .openai_compatible import OpenAICompatibleProvider
from .gemini_provider import GeminiProvider
from .anthropic_provider import AnthropicProvider
from .local_provider import LocalProvider
from .ollama_provider import OllamaLocalProvider
from .local_endpoint_provider import LocalEndpointProvider


def _provider_config() -> dict:
    cfg_file = ROOT / 'config' / 'providers.json'
    try:
        return json.loads(cfg_file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'providers': {}, 'custom_providers': []}


def _built_in_default_model(name: str) -> str:
    return {
        'local': settings.local_model_name,
        'openai': settings.openai_model,
        'xai': settings.xai_model,
        'nvidia': settings.nvidia_model,
        'deepseek': settings.deepseek_model,
        'anthropic': settings.anthropic_model,
        'gemini': settings.gemini_model,
    }.get(name.lower(), '')


def provider_policy(name: str) -> dict:
    config = _provider_config()
    normalized = name.lower()
    policy = config.get('providers', {}).get(normalized, {})
    custom = next((item for item in ProviderStore().list() if item.provider_id == normalized), None)
    return {
        'enabled': bool(policy.get('enabled', custom.enabled if custom else True)),
        'routing_priority': int(policy.get('routing_priority', custom.routing_priority if custom else 50)),
        'default_model': str(
            policy.get('default_model') or (custom.default_model if custom else '')
            or _built_in_default_model(normalized)
        ).strip(),
        'supports_vision': (
            policy.get('supports_vision') if 'supports_vision' in policy
            else (custom.capabilities.get('vision') if custom else False)
        ),
        'runtime': str(policy.get('runtime', custom.runtime.runtime if custom and custom.runtime else '')).strip(),
        'protocol': custom.protocol if custom else ('local' if normalized == 'local' else 'builtin'),
        'state': custom.state if custom else ('CONFIGURED' if policy else 'UNCONFIGURED'),
        'model_path': str(policy.get('model_path', '')).strip(),
        'context_length': policy.get('context_length', custom.context_length if custom else None),
        'max_output_tokens': policy.get('max_output_tokens'),
        'capability_profile': policy.get('capability_profile', {}),
        'capabilities': dict(custom.capabilities) if custom else {},
        'credential_source': custom.credential.source if custom else 'environment',
        'credential_name': custom.credential.name if custom else '',
    }


def _load_custom_providers() -> dict:
    """Load provider-agnostic user manifests without resolving credentials early."""
    factories: dict = {}
    resolver = CredentialResolver()
    for manifest in ProviderStore().list():
        factories[manifest.provider_id] = (
            lambda item=manifest, credentials=resolver: ManifestProvider(item, credentials)
        )
    return factories


def provider_factories() -> dict:
    """Return local, cloud, and custom provider factories."""
    local_runtime = settings.local_model_runtime.lower().replace('_', '-')
    local_factory = {
        'llamacpp': lambda: LocalProvider(provider_policy('local')['default_model']),
        'ollama': lambda: OllamaLocalProvider(provider_policy('local')['default_model']),
        'openai-compatible': lambda: LocalEndpointProvider(provider_policy('local')['default_model']),
        'openai-compatible-local': lambda: LocalEndpointProvider(provider_policy('local')['default_model']),
    }.get(local_runtime, lambda: LocalProvider(provider_policy('local')['default_model']))
    built_in = {
        'local': local_factory,
        'openai': lambda: OpenAICompatibleProvider(
            'openai', settings.openai_api_key, settings.openai_base_url,
            provider_policy('openai')['default_model'], provider_policy('openai')['supports_vision']
        ),
        'xai': lambda: OpenAICompatibleProvider(
            'xai', settings.xai_api_key, settings.xai_base_url,
            provider_policy('xai')['default_model'], provider_policy('xai')['supports_vision']
        ),
        'nvidia': lambda: OpenAICompatibleProvider(
            'nvidia', settings.nvidia_api_key, settings.nvidia_base_url,
            provider_policy('nvidia')['default_model'], provider_policy('nvidia')['supports_vision']
        ),
        'deepseek': lambda: OpenAICompatibleProvider(
            'deepseek', settings.deepseek_api_key, settings.deepseek_base_url,
            provider_policy('deepseek')['default_model'], provider_policy('deepseek')['supports_vision']
        ),
        'anthropic': lambda: AnthropicProvider(
            provider_policy('anthropic')['default_model'],
            provider_policy('anthropic')['supports_vision'],
        ),
        'gemini': lambda: GeminiProvider(
            provider_policy('gemini')['default_model'],
            provider_policy('gemini')['supports_vision'],
        ),
    }
    # User manifests are normal router candidates and may override built-in IDs explicitly.
    built_in.update(_load_custom_providers())
    return built_in


def get_provider(name: str):
    try:
        return provider_factories()[name.lower()]()
    except KeyError:
        raise ValueError(f'Unsupported provider: {name}')


def configured_providers() -> list[dict]:
    providers = []
    for name, factory in provider_factories().items():
        provider = factory()
        policy = provider_policy(name)
        configured = getattr(provider, 'configured', lambda: False)()
        providers.append({'provider': name, 'configured': configured, **policy})
    return providers
