import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.config import DEFAULT_LEXI_PROFILE
from agent.providers import local_provider
from agent.providers.local_provider import LocalProvider


def _use_profile(monkeypatch, model_file, **overrides):
    """Point the active Lexi profile at a tmp GGUF without touching flat config."""
    profile = replace(
        DEFAULT_LEXI_PROFILE,
        model_file_path=str(model_file),
        **overrides,
    )
    monkeypatch.setattr(local_provider.settings, 'active_local_model_profile', profile)
    return profile


def test_local_provider_lazy_loads_once_and_injects_local_identity(tmp_path, monkeypatch):
    model_file = tmp_path / 'lexi-llama-3-8b-q4_k_m.gguf'
    model_file.write_bytes(b'fake gguf')
    constructions = []
    requests = []

    class FakeLlama:
        def __init__(self, **kwargs):
            constructions.append(kwargs)

        def create_chat_completion(self, **kwargs):
            requests.append(kwargs)
            return {
                'choices': [{'message': {'content': 'Lexi-Llama-3-8B-Uncensored'}}],
                'usage': {'input_tokens': 4, 'output_tokens': 3},
            }

    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', True)
    _use_profile(
        monkeypatch, model_file,
        context_length=4096, max_output_tokens=128, threads=2, batch_size=256,
    )
    monkeypatch.setattr(
        local_provider.importlib, 'import_module',
        lambda name: SimpleNamespace(Llama=FakeLlama) if name == 'llama_cpp' else None,
    )
    monkeypatch.setattr(local_provider.importlib.util, 'find_spec', lambda _name: object())
    local_provider._RUNTIME.reset()

    provider = LocalProvider('lexi-llama-3-8b-q4_k_m')
    first = asyncio.run(provider.complete('kamu model apa?'))
    second = asyncio.run(provider.complete('ulang'))
    status = local_provider.local_runtime_status()

    assert first == ('Lexi-Llama-3-8B-Uncensored', {'input_tokens': 4, 'output_tokens': 3})
    assert second[0] == 'Lexi-Llama-3-8B-Uncensored'
    assert len(constructions) == 1
    assert constructions[0]['model_path'] == str(model_file.resolve())
    assert constructions[0]['n_ctx'] == 4096
    assert constructions[0]['n_threads'] == 2
    assert constructions[0]['n_batch'] == 256
    assert requests[0]['max_tokens'] == 128
    assert 'You are Zevora Local AI' in requests[0]['messages'][0]['content']
    assert status['loaded'] is True
    assert status['deployment'] == 'embedded'
    assert status['display_name'] == 'Lexi Llama 3 8B Q4_K_M'
    assert status['quantization'] == 'Q4_K_M'
    assert status['state'] == 'READY'

    local_provider._RUNTIME.reset()


def test_local_provider_lists_model_without_loading_weights(tmp_path, monkeypatch):
    model_file = tmp_path / 'lexi-llama-3-8b-q4_k_m.gguf'
    model_file.write_bytes(b'fake gguf')
    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', True)
    _use_profile(monkeypatch, model_file)
    monkeypatch.setattr(local_provider.importlib.util, 'find_spec', lambda _name: object())
    local_provider._RUNTIME.reset()

    models = asyncio.run(LocalProvider().list_models())

    assert models[0]['display_name'] == 'Lexi Llama 3 8B Q4_K_M'
    assert models[0]['model_id'] == 'lexi-llama-3-8b-q4_k_m'
    assert models[0]['quantization'] == 'Q4_K_M'
    assert models[0]['deployment'] == 'embedded'
    assert models[0]['installed'] is True
    assert models[0]['supports_vision'] is False
    assert local_provider.local_runtime_status()['loaded'] is False


def test_local_provider_logs_specific_missing_model_reason(tmp_path, monkeypatch, caplog):
    missing_model = tmp_path / 'missing.gguf'
    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', True)
    _use_profile(monkeypatch, missing_model)
    local_provider._RUNTIME.reset()

    with pytest.raises(local_provider.ModelNotFoundError):
        asyncio.run(LocalProvider().complete('hello'))

    assert 'local_model_load_failed reason=model_file_missing' in caplog.text
    assert str(missing_model) in caplog.text
    local_provider._RUNTIME.reset()
