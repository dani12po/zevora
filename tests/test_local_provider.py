import asyncio
from types import SimpleNamespace

from agent.providers import local_provider
from agent.providers.local_provider import LocalProvider


def test_local_provider_lazy_loads_once_and_injects_zevora_identity(tmp_path, monkeypatch):
    model_file = tmp_path / 'zevora.gguf'
    model_file.write_bytes(b'fake gguf')
    constructions = []
    requests = []

    class FakeLlama:
        def __init__(self, **kwargs):
            constructions.append(kwargs)

        def create_chat_completion(self, **kwargs):
            requests.append(kwargs)
            return {
                'choices': [{'message': {'content': 'Zevora Local AI'}}],
                'usage': {'input_tokens': 4, 'output_tokens': 3},
            }

    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', True)
    monkeypatch.setattr(local_provider.settings, 'local_model_runtime', 'llamacpp')
    monkeypatch.setattr(local_provider.settings, 'local_model_path', str(model_file))
    monkeypatch.setattr(local_provider.settings, 'local_model_context_length', 4096)
    monkeypatch.setattr(local_provider.settings, 'local_model_max_tokens', 128)
    monkeypatch.setattr(local_provider.settings, 'local_model_threads', 2)
    monkeypatch.setattr(local_provider.settings, 'local_model_gpu_layers', 0)
    monkeypatch.setattr(
        local_provider.importlib, 'import_module',
        lambda name: SimpleNamespace(Llama=FakeLlama) if name == 'llama_cpp' else None,
    )
    monkeypatch.setattr(local_provider.importlib.util, 'find_spec', lambda _name: object())
    local_provider._RUNTIME.reset()

    provider = LocalProvider('zevora')
    first = asyncio.run(provider.complete('kamu model apa?'))
    second = asyncio.run(provider.complete('ulang'))
    status = local_provider.local_runtime_status()

    assert first == ('Zevora Local AI', {'input_tokens': 4, 'output_tokens': 3})
    assert second[0] == 'Zevora Local AI'
    assert len(constructions) == 1
    assert constructions[0]['model_path'] == str(model_file.resolve())
    assert constructions[0]['n_ctx'] == 4096
    assert constructions[0]['n_threads'] == 2
    assert 'You are Zevora Local AI' in requests[0]['messages'][0]['content']
    assert status['loaded'] is True
    assert status['display_name'] == 'Zevora Local AI'

    local_provider._RUNTIME.reset()


def test_local_provider_lists_model_without_loading_weights(tmp_path, monkeypatch):
    model_file = tmp_path / 'zevora.gguf'
    model_file.write_bytes(b'fake gguf')
    monkeypatch.setattr(local_provider.settings, 'local_model_enabled', True)
    monkeypatch.setattr(local_provider.settings, 'local_model_path', str(model_file))
    monkeypatch.setattr(local_provider.importlib.util, 'find_spec', lambda _name: object())
    local_provider._RUNTIME.reset()

    models = asyncio.run(LocalProvider().list_models())

    assert models[0]['display_name'] == 'Zevora Local AI'
    assert models[0]['supports_vision'] is False
    assert local_provider.local_runtime_status()['loaded'] is False
