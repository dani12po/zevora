"""Lexi Llama 3 8B Q4_K_M hybrid integration tests (mocked, no 5.73 GB download)."""
import asyncio
import hashlib
from dataclasses import replace

import httpx
import pytest

import main
from agent.config import (
    DEFAULT_LEXI_PROFILE,
    LocalModelProfile,
    _apply_zevora_env_aliases,
)
from agent.models.downloader import (
    ChecksumMismatchError,
    DownloadError,
    SizeMismatchError,
    download_gguf,
    resolve_download_url,
)
from agent.models.registry import ModelRegistry
from agent.providers import local_endpoint_provider, local_provider
from agent.providers.errors import ModelNotFoundError, ProviderUnavailableError
from agent.providers.local_endpoint_provider import (
    LocalEndpointProvider,
    remote_endpoint_status,
    reset_remote_health_cache,
)
from agent.providers.local_provider import LocalProvider, check_local_resources
from agent.routing.hybrid_router import AdaptiveHybridRouter, Route


# ── Helpers ────────────────────────────────────────────────────────────────
def _use_profile(monkeypatch, model_file=None, **overrides):
    profile = replace(DEFAULT_LEXI_PROFILE, **overrides)
    if model_file is not None:
        profile = replace(profile, model_file_path=str(model_file))
    monkeypatch.setattr(local_provider.settings, 'active_local_model_profile', profile)
    return profile


@pytest.fixture(autouse=True)
def _clean_remote_state(monkeypatch):
    reset_remote_health_cache()
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )
    yield
    reset_remote_health_cache()


EMBEDDED = {
    'provider': 'local', 'model_id': 'lexi-llama-3-8b-q4_k_m',
    'deployment': 'embedded',
    'capabilities': ['general', 'coding', 'reasoning', 'local', 'private', 'tool_use'],
    'capability_profile': {'instruction_score': .9, 'coding_score': .86, 'reasoning_score': .84},
    'availability': 'verified', 'health_status': 'healthy', 'input_price': 0,
    'supports_tools': True, 'installed': True, 'context_window': 8192,
}
REMOTE = {
    **EMBEDDED, 'provider': 'local_remote', 'deployment': 'remote',
}
CLOUD = {
    'provider': 'openai', 'model_id': 'gpt-4o-mini',
    'capabilities': ['general', 'coding', 'reasoning'],
    'capability_profile': {'instruction_score': .95, 'coding_score': .9, 'reasoning_score': .9},
    'availability': 'verified', 'health_status': 'healthy', 'input_price': .15,
    'supports_tools': True,
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError('mock', request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in driven by a handler function."""
    handler = staticmethod(lambda method, url, **kwargs: _FakeResponse())

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        return type(self).handler('GET', url)

    async def post(self, url, headers=None, json=None):
        return type(self).handler('POST', url, payload=json)


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(local_endpoint_provider.httpx, 'AsyncClient', _FakeAsyncClient)
    return _FakeAsyncClient


# ── Phase 3: profile + defaults ────────────────────────────────────────────
def test_lexi_default_profile():
    profile = LocalModelProfile()
    assert profile.repository == 'bartowski/Lexi-Llama-3-8B-Uncensored-GGUF'
    assert profile.filename == 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    assert profile.model_id == 'lexi-llama-3-8b-q4_k_m'
    assert profile.display_name == 'Lexi Llama 3 8B Q4_K_M'
    assert profile.quantization == 'Q4_K_M'
    assert profile.runtime == 'llamacpp'
    assert profile.format == 'gguf'
    assert profile.context_length == 8192
    assert profile.max_output_tokens == 2048
    assert profile.temperature == 0.4
    assert profile.batch_size == 512
    assert profile.deployment_mode == 'bundled'


def test_lexi_gguf_filename_and_url():
    assert DEFAULT_LEXI_PROFILE.filename == 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    url = resolve_download_url(DEFAULT_LEXI_PROFILE.repository, DEFAULT_LEXI_PROFILE.filename)
    assert url == (
        'https://huggingface.co/bartowski/Lexi-Llama-3-8B-Uncensored-GGUF'
        '/resolve/main/Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    )
    # Single-file resolve endpoint: never a whole-repository clone.
    assert 'snapshot' not in url and 'archive' not in url


def test_zevora_env_aliases_and_gpu_auto(monkeypatch):
    from agent.config import Settings
    monkeypatch.setenv('ZEVORA_LOCAL_MODEL_REPOSITORY', 'someone/Some-GGUF')
    monkeypatch.delenv('LOCAL_MODEL_REPOSITORY', raising=False)
    _apply_zevora_env_aliases()
    assert Settings().local_model_repository == 'someone/Some-GGUF'
    # Phase 19 AUTO option coerces instead of failing parsing.
    assert Settings(local_model_gpu_layers='auto').local_model_gpu_layers == 0
    # Flat legacy fields remain for backward compatibility.
    assert hasattr(Settings(), 'local_model_quant')


def test_remote_lexi_defaults_disabled():
    from agent.config import settings
    assert settings.remote_local_enabled is False
    assert settings.remote_local_timeout_seconds == 120
    assert settings.remote_local_streaming is True


# ── Phase 4/15/16: embedded runtime ────────────────────────────────────────
def test_embedded_status_reports_lexi_deployment(tmp_path, monkeypatch):
    model_file = tmp_path / 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    model_file.write_bytes(b'fake gguf')
    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', True)
    _use_profile(monkeypatch, model_file)
    monkeypatch.setattr(local_provider.importlib.util, 'find_spec', lambda _name: object())
    local_provider._RUNTIME.reset()
    try:
        status = local_provider.local_runtime_status()
        assert status['deployment'] == 'embedded'
        assert status['model_id'] == 'lexi-llama-3-8b-q4_k_m'
        assert status['model_repository'] == 'bartowski/Lexi-Llama-3-8B-Uncensored-GGUF'
        assert status['model_filename'] == 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
        assert status['runtime'] == 'llamacpp'
        assert status['context_length'] == 8192
    finally:
        local_provider._RUNTIME.reset()


def test_resource_preflight_reports_insufficient(tmp_path, monkeypatch):
    model_file = tmp_path / 'big.gguf'
    model_file.write_bytes(b'x' * 1024)
    _use_profile(monkeypatch, model_file)

    class TinyRAM:
        available = 1024  # 1 KiB: nothing fits once overhead applies

    monkeypatch.setattr(local_provider.psutil, 'virtual_memory', lambda: TinyRAM())
    with pytest.raises(ProviderUnavailableError, match='LOCAL_MODEL_RESOURCE_INSUFFICIENT'):
        check_local_resources(model_file)


def test_resource_preflight_uses_calibrated_overhead(tmp_path, monkeypatch):
    """Weights + KV-cache (~96 KiB/token) + scratch, without the old 25% tax."""
    model_file = tmp_path / 'model.gguf'
    model_file.write_bytes(b'x' * (1024 * 1024))  # 1 MiB of weights
    _use_profile(monkeypatch, model_file, context_length=8192)

    class RoomyRAM:
        available = 2 * 1024 * 1024 * 1024  # 2 GiB free

    monkeypatch.setattr(local_provider.psutil, 'virtual_memory', lambda: RoomyRAM())
    report = check_local_resources(model_file)
    expected = 1024 * 1024 + 8192 * 96 * 1024 + 256 * 1024 * 1024
    assert report['required_bytes'] == expected
    assert report['sufficient'] is True


def test_gpu_auto_resolves_without_forcing(monkeypatch):
    _use_profile(monkeypatch, gpu_layers=4)
    assert local_provider.resolve_gpu_layers() == 4
    _use_profile(monkeypatch, gpu_layers=0)
    monkeypatch.setattr(local_provider, '_gpu_available', lambda: False)
    assert local_provider.resolve_gpu_layers() == 0
    monkeypatch.setattr(local_provider, '_gpu_available', lambda: True)
    assert local_provider.resolve_gpu_layers() == -1


# ── Phase 5: downloader ────────────────────────────────────────────────────
def _mock_transport(payload: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        range_header = request.headers.get('range', '')
        start = 0
        if range_header.startswith('bytes='):
            try:
                start = int(range_header.split('=')[1].split('-')[0])
            except ValueError:
                start = 0
        body = payload[start:]
        status = 206 if start else 200
        headers = {'content-length': str(len(body))}
        if start:
            headers['content-range'] = f'bytes {start}-{len(payload) - 1}/{len(payload)}'
        return httpx.Response(status, headers=headers, content=body)
    return httpx.MockTransport(handler)


def test_downloader_installs_single_file_atomically(tmp_path):
    payload = b'gguf-bytes-12345'
    client = httpx.Client(transport=_mock_transport(payload))
    dest = tmp_path / 'sub' / 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    progress = []
    result = download_gguf(
        repository='bartowski/Lexi-Llama-3-8B-Uncensored-GGUF',
        filename='Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf',
        dest=dest,
        expected_size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        progress_cb=lambda done, total: progress.append((done, total)),
        client=client,
    )
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + '.part').exists()
    assert dest.with_name(dest.name + '.sha256').is_file()
    assert result['bytes'] == len(payload)
    assert progress and progress[-1][0] == len(payload)


def test_downloader_refuses_silent_overwrite(tmp_path):
    dest = tmp_path / 'model.gguf'
    dest.write_bytes(b'existing')
    client = httpx.Client(transport=_mock_transport(b'new'))
    with pytest.raises(DownloadError, match='already exists'):
        download_gguf(
            repository='r', filename='f.gguf', dest=dest, client=client,
        )
    assert dest.read_bytes() == b'existing'


def test_downloader_rolls_back_on_size_mismatch(tmp_path):
    client = httpx.Client(transport=_mock_transport(b'short'))
    dest = tmp_path / 'model.gguf'
    with pytest.raises(SizeMismatchError):
        download_gguf(
            repository='r', filename='f.gguf', dest=dest,
            expected_size_bytes=9999, client=client,
        )
    assert not dest.exists()
    assert not dest.with_name(dest.name + '.part').exists()


def test_downloader_rolls_back_on_checksum_mismatch(tmp_path):
    client = httpx.Client(transport=_mock_transport(b'payload'))
    dest = tmp_path / 'model.gguf'
    with pytest.raises(ChecksumMismatchError):
        download_gguf(
            repository='r', filename='f.gguf', dest=dest,
            sha256='0' * 64, client=client,
        )
    assert not dest.exists()


def test_downloader_resumes_partial_file(tmp_path):
    payload = b'0123456789abcdef'
    dest = tmp_path / 'model.gguf'
    dest.with_name(dest.name + '.part').write_bytes(payload[:6])
    client = httpx.Client(transport=_mock_transport(payload))
    result = download_gguf(
        repository='r', filename='f.gguf', dest=dest, client=client,
    )
    assert result['resumed'] is True
    assert dest.read_bytes() == payload


# ── Phase 6/22/23: remote Lexi ─────────────────────────────────────────────
def _remote_settings(monkeypatch, base_url='http://gpu-host:8080'):
    monkeypatch.setattr(local_endpoint_provider.settings, 'remote_local_enabled', True)
    monkeypatch.setattr(local_endpoint_provider.settings, 'remote_local_base_url', base_url)
    monkeypatch.setattr(local_endpoint_provider.settings, 'remote_local_model', 'lexi-llama-3-8b-q4_k_m')


def test_remote_lists_models_via_get_models(fake_http, monkeypatch):
    _remote_settings(monkeypatch)

    def handler(method, url, **kwargs):
        assert url == 'http://gpu-host:8080/models'
        return _FakeResponse(200, {'data': [{'id': 'lexi-llama-3-8b-q4_k_m'}]})

    fake_http.handler = staticmethod(handler)
    models = asyncio.run(LocalEndpointProvider().list_models())
    assert models[0]['model_id'] == 'lexi-llama-3-8b-q4_k_m'
    assert models[0]['deployment'] == 'remote'
    assert models[0]['protocol'] == 'openai-compatible'


def test_remote_chat_completions(fake_http, monkeypatch):
    _remote_settings(monkeypatch)

    def handler(method, url, **kwargs):
        if method == 'GET':
            return _FakeResponse(200, {'data': [{'id': 'lexi-llama-3-8b-q4_k_m'}]})
        assert url == 'http://gpu-host:8080/chat/completions'
        assert kwargs['payload']['model'] == 'lexi-llama-3-8b-q4_k_m'
        assert kwargs['payload']['stream'] is False
        return _FakeResponse(200, {
            'choices': [{'message': {'content': '  hello remote  '}}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 2},
        })

    fake_http.handler = staticmethod(handler)
    text, usage = asyncio.run(LocalEndpointProvider().complete('hi', 'sys'))
    assert text == 'hello remote'
    assert usage['output_tokens'] == 2


def test_remote_health_failure_and_status(fake_http, monkeypatch):
    _remote_settings(monkeypatch, base_url='http://gone-host:8080')

    def handler(method, url, **kwargs):
        raise httpx.ConnectError('refused')

    fake_http.handler = staticmethod(handler)
    provider = LocalEndpointProvider()
    assert asyncio.run(provider.health_check()) is False
    assert asyncio.run(provider.list_models()) == []
    status = remote_endpoint_status()
    assert status['deployment'] == 'remote'
    assert status['last_error'] == 'REMOTE_ENDPOINT_UNAVAILABLE'


def test_remote_streaming_falls_back_to_buffered(monkeypatch):
    _remote_settings(monkeypatch)
    provider = LocalEndpointProvider()

    async def fake_complete(prompt, system=''):
        return 'buffered answer', {}

    monkeypatch.setattr(provider, 'complete', fake_complete)

    class _BrokenStream:
        async def __aenter__(self):
            raise httpx.ConnectError('no sse')

        async def __aexit__(self, *args):
            return False

    class BrokenStreamClient(_FakeAsyncClient):
        def stream(self, *args, **kwargs):  # noqa: ARG002
            return _BrokenStream()

    monkeypatch.setattr(local_endpoint_provider.httpx, 'AsyncClient', BrokenStreamClient)
    chunks = asyncio.run(_collect(provider.stream('hi', '')))
    assert chunks == ['buffered answer']


async def _collect(gen):
    return [chunk async for chunk in gen]


def test_remote_not_configured_without_url(monkeypatch):
    monkeypatch.setattr(local_endpoint_provider.settings, 'remote_local_enabled', True)
    monkeypatch.setattr(local_endpoint_provider.settings, 'remote_local_base_url', '')
    monkeypatch.setattr(local_endpoint_provider.settings, 'local_endpoint_url', 'not-a-url')
    assert LocalEndpointProvider().configured() is False


# ── Phase 7/10/26: routing + fallback ───────────────────────────────────────
def test_router_modes_cover_remote_local_only(monkeypatch):
    router = AdaptiveHybridRouter()
    monkeypatch.setattr(
        'agent.routing.hybrid_router.settings.routing_mode', 'REMOTE_LOCAL_ONLY'
    )
    candidates = router.candidates('explain REST', [EMBEDDED, REMOTE, CLOUD])
    assert candidates and {item.provider for item in candidates} == {'local_remote'}
    monkeypatch.setattr(
        'agent.routing.hybrid_router.settings.routing_mode', 'LOCAL_ONLY'
    )
    candidates = router.candidates('explain REST', [EMBEDDED, REMOTE, CLOUD])
    assert {item.provider for item in candidates} == {'local', 'local_remote'}


def test_auto_prefers_embedded_then_remote_then_cloud():
    candidates = AdaptiveHybridRouter().candidates('what is REST API?', [EMBEDDED, REMOTE, CLOUD])
    ordered = [(item.route, item.provider) for item in candidates]
    assert ordered[0] == (Route.LOCAL, 'local')
    assert ordered[1] == (Route.LOCAL, 'local_remote')
    assert ordered[2][0] == Route.CLOUD


def test_tool_and_context_filtering_apply_to_remote():
    router = AdaptiveHybridRouter()
    no_tools = {**REMOTE, 'supports_tools': False, 'capabilities': ['general']}
    decision = router.decide('run terminal command', [no_tools, EMBEDDED])
    assert decision.provider == 'local'
    narrow = {**REMOTE, 'context_window': 8}
    decision = router.decide('explain REST API', [narrow], context_tokens=64)
    assert (decision.provider, decision.model_id) != ('local_remote', narrow['model_id'])


def test_failure_reasons_cover_remote_and_resource():
    from agent.routing.hybrid_router import RoutingDecision
    embedded = RoutingDecision(Route.LOCAL, 'local', 'm', 't', [], 0.1, [], 0.0)
    remote = RoutingDecision(Route.LOCAL, 'local_remote', 'm', 't', [], 0.1, [], 0.0)
    assert main._failure_reason(remote, ProviderUnavailableError('x'))[0] == 'REMOTE_ENDPOINT_UNAVAILABLE'
    assert main._failure_reason(remote, ModelNotFoundError('x'))[0] == 'REMOTE_MODEL_NOT_FOUND'
    assert main._failure_reason(embedded, ModelNotFoundError('x'))[0] == 'LOCAL_MODEL_MISSING'
    assert main._failure_reason(
        embedded, ProviderUnavailableError('LOCAL_MODEL_RESOURCE_INSUFFICIENT: nope')
    )[0] == 'LOCAL_MODEL_RESOURCE_INSUFFICIENT'


# ── Phase 21: registry distinguishes deployments ───────────────────────────
def test_registry_keeps_embedded_and_remote_distinct(tmp_path):
    registry = ModelRegistry(tmp_path / 'models.db')
    registry.upsert({'provider': 'local', 'model_id': 'lexi-llama-3-8b-q4_k_m',
                     'runtime': 'llamacpp', 'quantization': 'Q4_K_M', 'installed': True})
    registry.upsert({'provider': 'local_remote', 'model_id': 'lexi-llama-3-8b-q4_k_m',
                     'runtime': 'llamacpp', 'quantization': 'Q4_K_M', 'installed': True})
    assert len(registry.list('local')) == 1
    assert len(registry.list('local_remote')) == 1
    assert registry.list('local')[0]['quantization'] == 'Q4_K_M'


def test_local_provider_health_respects_disabled(tmp_path, monkeypatch):
    _use_profile(monkeypatch, tmp_path / 'missing.gguf')
    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', False)
    assert asyncio.run(LocalProvider().health_check()) is False
