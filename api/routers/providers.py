"""Provider configuration, manifests, testing, and usage history endpoints."""
import json

from fastapi import HTTPException, Query
import main



from main import app, _PROVIDER_CONFIG_LOCK
from api.schemas import (
    ProviderAnalysisRequest,
    ProviderConfigRequest,
    ProviderEnabledRequest,
    ProviderExampleRequest,
    ProviderManifestRequest,
    ProviderTestRequest,
    ProviderTrustRequest,
)
from api.helpers import _atomic_write_text, _provider_service_error

@app.get('/api/providers')
async def providers():
    discovered = await main.ProviderDiscovery(main.model_registry).providers()
    local = main.local_runtime_status()
    for item in discovered:
        if item.get('provider') == 'local':
            item['runtime_status'] = local
    return discovered
@app.get('/api/providers/config')
def providers_config():
    """Return provider config with API keys masked — never exposes raw secrets."""
    env_file = main.ROOT / '.env'
    env_vals: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                env_vals[k.strip().upper()] = v.strip()
    providers_cfg_file = main.ROOT / 'config' / 'providers.json'
    try: cfg = json.loads(providers_cfg_file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError): cfg = {'providers': {}}
    provider_cfg = cfg.get('providers', {})
    KEY_MAP = {
        'openai': 'OPENAI_API_KEY', 'xai': 'XAI_API_KEY', 'nvidia': 'NVIDIA_API_KEY',
        'deepseek': 'DEEPSEEK_API_KEY', 'gemini': 'GEMINI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY',
        'local_remote': 'REMOTE_LOCAL_API_KEY',
    }
    URL_MAP = {
        'openai': 'OPENAI_BASE_URL', 'xai': 'XAI_BASE_URL', 'nvidia': 'NVIDIA_BASE_URL',
        'deepseek': 'DEEPSEEK_BASE_URL', 'anthropic': 'ANTHROPIC_BASE_URL',
        'local_remote': 'REMOTE_LOCAL_BASE_URL',
    }
    DEFAULT_URLS = {
        'openai': 'https://api.openai.com/v1', 'xai': 'https://api.x.ai/v1',
        'nvidia': 'https://integrate.api.nvidia.com/v1', 'deepseek': 'https://api.deepseek.com/v1',
        'gemini': '', 'anthropic': 'https://api.anthropic.com', 'local_remote': '',
    }
    customs = cfg.get('custom_providers', [])
    for c in customs:
        name = c.get('name', '').lower()
        if not name: continue
        KEY_MAP[name] = c.get('api_key_env', '')
        URL_MAP[name] = ''
        DEFAULT_URLS[name] = c.get('base_url', '')

    result = []
    all_providers = ['local', 'local_remote', 'openai', 'xai', 'nvidia', 'deepseek', 'gemini', 'anthropic'] + [c.get('name', '').lower() for c in customs if c.get('name')]

    for name in all_providers:
        raw_key = env_vals.get(KEY_MAP.get(name, ''), '')
        masked = ('••••••••' + raw_key[-4:]) if raw_key and len(raw_key) >= 4 else ''
        raw_url = env_vals.get(URL_MAP.get(name, ''), DEFAULT_URLS.get(name, ''))
        p = provider_cfg.get(name, {})
        runtime = main.local_runtime_status() if name == 'local' else None
        remote = main.remote_endpoint_status() if name in {'local', 'local_remote'} else None
        result.append({
            'provider': name, 'key_masked': masked, 'key_set': bool(raw_key),
            'base_url': raw_url or DEFAULT_URLS.get(name, ''),
            'remote_status': remote,
            'default_model': p.get('default_model') or {
                'openai': env_vals.get('OPENAI_MODEL', 'gpt-4o-mini'),
                'xai': env_vals.get('XAI_MODEL', 'grok-3-mini'),
                'nvidia': env_vals.get('NVIDIA_MODEL', 'meta/llama-3.1-8b-instruct'),
                'deepseek': env_vals.get('DEEPSEEK_MODEL', 'deepseek-chat'),
                'gemini': env_vals.get('GEMINI_MODEL', 'gemini-2.0-flash'),
                'anthropic': env_vals.get('ANTHROPIC_MODEL', 'claude-3-5-haiku-latest'),
            }.get(name, ''),
            'enabled': p.get('enabled', True), 'routing_priority': p.get('routing_priority', 50),
            'runtime_status': runtime,
            'supports_vision': bool(p.get('supports_vision', next((
                c.get('supports_vision', False) for c in customs
                if c.get('name', '').lower() == name
            ), False))),
        })
    return result


@app.post('/api/providers/config')
async def update_provider_config(body: ProviderConfigRequest):
    """Persist provider settings without exposing API keys."""
    from urllib.parse import urlparse

    provider_name = body.provider.strip().lower()
    if body.api_key is not None and any(char in body.api_key for char in '\r\n'):
        raise HTTPException(400, 'api_key must not contain newlines')
    if body.base_url is not None:
        parsed_url = urlparse(body.base_url.strip())
        if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
            raise HTTPException(400, 'base_url must be an absolute HTTP(S) URL')
        # Reject SSRF-prone endpoints at save time so a stored URL can never
        # turn discovery/health into a 500. Cloud providers must be public;
        # the remote-local adapter keeps loopback/LAN but never metadata IPs.
        from agent.providers.ssrf import (
            assert_local_endpoint_url,
            assert_provider_base_url,
        )
        try:
            if provider_name == 'local_remote':
                assert_local_endpoint_url(body.base_url.strip())
            else:
                assert_provider_base_url(body.base_url.strip())
        except ValueError as error:
            raise HTTPException(400, str(error))
    model = body.default_model.strip() if body.default_model is not None else None
    if model == '':
        raise HTTPException(400, 'default_model cannot be empty')

    providers_cfg_file = main.ROOT / 'config' / 'providers.json'
    env_file = main.ROOT / '.env'
    async with _PROVIDER_CONFIG_LOCK:
        try:
            cfg = json.loads(providers_cfg_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            cfg = {'providers': {}, 'model_overrides': {}}
        customs = cfg.get('custom_providers', [])
        allowed = {'openai', 'xai', 'nvidia', 'deepseek', 'gemini', 'anthropic', 'local_remote'}
        allowed.update(c.get('name', '').lower() for c in customs if c.get('name'))
        if provider_name not in allowed:
            raise HTTPException(400, f'Unknown provider: {provider_name}')

        key_map = {
            'openai': 'OPENAI_API_KEY', 'xai': 'XAI_API_KEY',
            'nvidia': 'NVIDIA_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY',
            'gemini': 'GEMINI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY',
            'local_remote': 'REMOTE_LOCAL_API_KEY',
        }
        url_map = {
            'openai': 'OPENAI_BASE_URL', 'xai': 'XAI_BASE_URL',
            'nvidia': 'NVIDIA_BASE_URL', 'deepseek': 'DEEPSEEK_BASE_URL',
            'anthropic': 'ANTHROPIC_BASE_URL', 'local_remote': 'REMOTE_LOCAL_BASE_URL',
        }
        for custom in customs:
            name = custom.get('name', '').lower()
            if name:
                key_map[name] = custom.get('api_key_env', '')

        lines = env_file.read_text(encoding='utf-8').splitlines() if env_file.exists() else []
        env_map = {}
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key, _, _ = stripped.partition('=')
                env_map[key.strip().upper()] = index

        def set_env(key: str, value: str) -> None:
            if not key:
                return
            if key in env_map:
                lines[env_map[key]] = f'{key}={value}'
            else:
                env_map[key] = len(lines)
                lines.append(f'{key}={value}')

        if body.api_key is not None:
            set_env(key_map.get(provider_name, ''), body.api_key)
        if body.base_url is not None and provider_name in url_map:
            set_env(url_map[provider_name], body.base_url.strip())

        provider_cfg = cfg.setdefault('providers', {}).setdefault(provider_name, {})
        if model is not None:
            provider_cfg['default_model'] = model
        if body.enabled is not None:
            provider_cfg['enabled'] = body.enabled
        if body.routing_priority is not None:
            provider_cfg['routing_priority'] = body.routing_priority
        if body.supports_vision is not None:
            provider_cfg['supports_vision'] = body.supports_vision

        _atomic_write_text(env_file, '\n'.join(lines) + '\n')
        _atomic_write_text(
            providers_cfg_file,
            json.dumps(cfg, indent=2, ensure_ascii=True) + '\n',
        )

    main.reload_settings()
    refresh = await main.ProviderDiscovery(main.model_registry).refresh(provider_name)
    verification = refresh[0] if refresh else {
        'health_status': 'disabled' if body.enabled is False else 'unconfigured',
        'models_discovered': 0,
        'failure_reason': 'PROVIDER_DISABLED' if body.enabled is False else 'PROVIDER_UNCONFIGURED',
        'failure_message': (
            'The provider is disabled.' if body.enabled is False
            else 'The provider credential is not configured.'
        ),
    }
    return {
        'ok': True,
        'provider': provider_name,
        'key_updated': body.api_key is not None,
        'status': verification['health_status'],
        'models_discovered': verification['models_discovered'],
        'failure_reason': verification.get('failure_reason'),
        'failure_message': verification.get('failure_message'),
    }


@app.post('/api/providers/{provider_name}/test')
async def test_builtin_provider(provider_name: str):
    """Verify a built-in provider without changing its saved configuration."""
    normalized = provider_name.strip().lower()
    if normalized == 'local':
        runtime = main.local_runtime_status()
        healthy = bool(
            runtime['enabled']
            and runtime['model_exists']
            and runtime['runtime'] == 'llamacpp'
            and runtime['runtime_available']
        )
        status = (
            'healthy' if healthy
            else 'disabled' if not runtime['enabled']
            else 'unavailable'
        )
        return {
            'ok': healthy,
            'provider': normalized,
            'status': status,
            'models_discovered': 1 if healthy else 0,
            'failure_reason': None if healthy else 'LOCAL_MODEL_UNAVAILABLE',
            'failure_message': None if healthy else 'Embedded local model is not ready.',
        }
    if normalized == 'local_remote':
        from agent.providers.local_endpoint_provider import LocalEndpointProvider
        report = main.remote_endpoint_status()
        if not report['enabled']:
            return {
                'ok': False, 'provider': normalized, 'status': 'disabled',
                'models_discovered': 0, 'failure_reason': 'PROVIDER_DISABLED',
                'failure_message': 'The remote Lexi endpoint is disabled.',
            }
        if not report['base_url']:
            return {
                'ok': False, 'provider': normalized, 'status': 'unconfigured',
                'models_discovered': 0, 'failure_reason': 'PROVIDER_UNCONFIGURED',
                'failure_message': 'The remote Lexi base URL is not configured.',
            }
        healthy = await LocalEndpointProvider().health_check()
        return {
            'ok': bool(healthy),
            'provider': normalized,
            'status': 'healthy' if healthy else 'unavailable',
            'models_discovered': 1 if healthy else 0,
            'failure_reason': None if healthy else 'REMOTE_ENDPOINT_UNAVAILABLE',
            'failure_message': None if healthy else 'The remote Lexi endpoint is unreachable.',
        }
    allowed = {'openai', 'xai', 'nvidia', 'deepseek', 'gemini', 'anthropic'}
    if normalized not in allowed:
        raise HTTPException(404, {
            'code': 'PROVIDER_NOT_FOUND', 'message': 'Provider was not found.',
        })
    refresh = await main.ProviderDiscovery(main.model_registry).refresh(normalized)
    verification = refresh[0]
    return {
        'ok': (
            verification['health_status'] == 'healthy'
            and verification['models_discovered'] > 0
        ),
        'provider': normalized,
        'status': verification['health_status'],
        'models_discovered': verification['models_discovered'],
        'failure_reason': verification.get('failure_reason'),
        'failure_message': verification.get('failure_message'),
    }


@app.get('/api/provider-manifests')
def provider_manifests():
    return {
        'providers': main.provider_service.list(),
        'runtime_availability': main.provider_service.runtime_availability(),
    }


@app.get('/api/provider-manifests/{provider_id}')
def provider_manifest(provider_id: str):
    try:
        return main.provider_service.get(provider_id)
    except (KeyError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests')
async def save_provider_manifest(body: ProviderManifestRequest):
    try:
        saved = main.provider_service.save(
            body.manifest, credential_value=body.credential_value, script=body.script,
        )
        refresh = await main.ProviderDiscovery(main.model_registry).refresh(saved['provider_id'])
        return {'ok': True, 'provider': saved, 'discovery': refresh}
    except (KeyError, PermissionError, TypeError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/import')
async def import_provider_manifest(body: ProviderManifestRequest):
    try:
        saved = main.provider_service.import_manifest(
            body.manifest, credential_value=body.credential_value, script=body.script,
        )
        refresh = await main.ProviderDiscovery(main.model_registry).refresh(saved['provider_id'])
        return {'ok': True, 'provider': saved, 'discovery': refresh}
    except (json.JSONDecodeError, KeyError, PermissionError, TypeError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/analyze')
def analyze_provider_script(body: ProviderAnalysisRequest):
    try:
        return {'ok': True, 'analysis': main.provider_service.analyze(body.source, body.language)}
    except ValueError as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/test')
async def test_provider_manifest(provider_id: str, body: ProviderTestRequest):
    try:
        result = await main.provider_service.test(
            provider_id, runtime_approved=body.runtime_approved,
        )
        return {'ok': bool(result.get('success')), 'result': result}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/runtime-test')
async def test_provider_runtime(provider_id: str, body: ProviderTestRequest):
    if not body.runtime_approved:
        raise HTTPException(403, {
            'code': 'PROVIDER_RUNTIME_APPROVAL_REQUIRED',
            'message': 'Explicit one-time runtime approval is required.',
        })
    try:
        result = await main.provider_service.test(provider_id, runtime_approved=True)
        return {'ok': bool(result.get('success')), 'result': result}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/trust')
def trust_provider_runtime(provider_id: str, body: ProviderTrustRequest):
    try:
        return {'ok': True, 'provider': main.provider_service.trust_runtime(
            provider_id, approved=body.approved,
        )}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/enabled')
def enable_provider_manifest(provider_id: str, body: ProviderEnabledRequest):
    try:
        return {'ok': True, 'provider': main.provider_service.set_enabled(provider_id, body.enabled)}
    except (KeyError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/models/refresh')
async def refresh_provider_models(provider_id: str):
    try:
        result = await main.provider_service.refresh_models(provider_id)
        await main.ProviderDiscovery(main.model_registry).refresh(provider_id)
        return {'ok': True, **result}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/example')
def generate_provider_example(provider_id: str, body: ProviderExampleRequest):
    try:
        return {'ok': True, **main.provider_service.generate_example(provider_id, body.language)}
    except (KeyError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.get('/api/provider-manifests/{provider_id}/export')
def export_provider_manifest(provider_id: str):
    try:
        return main.provider_service.export_manifest(provider_id)
    except KeyError as error:
        raise _provider_service_error(error) from error


@app.get('/api/provider-manifests/{provider_id}/source')
def provider_runtime_source(provider_id: str):
    try:
        return {'provider_id': provider_id, 'source': main.provider_service.runtime_source(provider_id)}
    except (KeyError, OSError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.delete('/api/provider-manifests/{provider_id}')
def delete_provider_manifest(provider_id: str):
    try:
        removed = main.provider_service.remove(provider_id)
    except ValueError as error:
        raise _provider_service_error(error) from error
    if not removed:
        raise _provider_service_error(KeyError(provider_id))
    return {'ok': True, 'provider_id': provider_id}


@app.get('/api/usage/history')
def usage_history(
    provider: str | None = Query(default=None, max_length=80),
    days: int = Query(default=30, ge=1, le=365),
):
    """Per-day, per-provider breakdown from usage_events table."""
    with main.store.connection() as conn:
        sql = '''SELECT date(created_at) day, provider, model,
                    COUNT(*) requests, COALESCE(SUM(cache_hit),0) cache_hits,
                    COALESCE(SUM(input_tokens),0) input_tokens,
                    COALESCE(SUM(output_tokens),0) output_tokens,
                    COALESCE(SUM(estimated_cost),0) estimated_cost
                 FROM usage_events
                 WHERE date(created_at) >= date('now', ?)'''
        args: list = [f'-{days} days']
        if provider:
            sql += ' AND provider=?'; args.append(provider)
        sql += ' GROUP BY day, provider, model ORDER BY day DESC, provider'
        rows = conn.execute(sql, args).fetchall()
    return {'rows': [dict(r) for r in rows], 'days': days, 'provider_filter': provider}
