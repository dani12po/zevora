import json
from pathlib import Path
from ..config import settings, ROOT
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
    custom = next(
        (item for item in config.get('custom_providers', []) if item.get('name', '').lower() == normalized),
        {},
    )
    return {
        'enabled': bool(policy.get('enabled', True)),
        'routing_priority': int(policy.get('routing_priority', 50)),
        'default_model': str(
            policy.get('default_model') or custom.get('default_model') or _built_in_default_model(normalized)
        ).strip(),
        'supports_vision': bool(policy.get('supports_vision', custom.get('supports_vision', False))),
        'runtime': str(policy.get('runtime', '')).strip(),
        'model_path': str(policy.get('model_path', '')).strip(),
        'context_length': policy.get('context_length'),
        'max_output_tokens': policy.get('max_output_tokens'),
        'capability_profile': policy.get('capability_profile', {}),
    }


def _local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = (ROOT / '.env').read_text(encoding='utf-8').splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key, _, value = stripped.partition('=')
            values[key.strip().upper()] = value.strip()
    return values


def _load_custom_providers() -> dict:
    """Load user-defined OpenAI-compatible providers from config/providers.json.

    Custom providers are defined under the ``custom_providers`` key::

        {
          "custom_providers": [
            {
              "name": "my-proxy",
              "base_url": "https://my-proxy.example.com/v1",
              "api_key_env": "MY_PROXY_API_KEY",
              "default_model": "gpt-4o"
            }
          ]
        }
    """
    customs = _provider_config().get('custom_providers', [])
    factories: dict = {}
    env_values = _local_env()
    for entry in customs:
        name = entry.get('name', '').strip().lower()
        base_url = entry.get('base_url', '').strip()
        api_key_env = entry.get('api_key_env', '').strip()
        default_model = entry.get('default_model', '').strip()
        supports_vision = bool(entry.get('supports_vision', False))
        if not name or not base_url:
            continue
        api_key = env_values.get(api_key_env.upper(), '') if api_key_env else ''
        factories[name] = lambda n=name, k=api_key, u=base_url, m=default_model, v=supports_vision: (
            OpenAICompatibleProvider(n, k, u, m, v)
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
    # Merge custom providers — user-defined names take precedence
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
