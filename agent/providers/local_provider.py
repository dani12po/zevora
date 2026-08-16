import asyncio
import importlib
import threading
from pathlib import Path
from time import perf_counter

import psutil

from ..config import settings
from .base import AIProvider
from .errors import ModelNotFoundError, ProviderUnavailableError


IDENTITY_PROMPT = (
    'You are Zevora Local AI, the private on-device assistant in ZEVORA. '
    'When asked your identity or model name, answer "Zevora Local AI". '
    'Do not claim that the underlying model weights were modified or trained by ZEVORA. '
    'Be accurate, concise, and follow the user request.'
)


class _LocalRuntime:
    """Process-wide lazy llama.cpp runtime for the configured GGUF."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._generation_lock = threading.Lock()
        self._loaded_path = ''
        self._loading_error = ''
        self._loaded_rss_mb = 0
        self._load_delta_mb = 0
        self._load_seconds = 0.0

    def reset(self) -> None:
        """Release the Python model reference; primarily useful for tests/reloads."""
        with self._lock:
            self._model = None
            self._loaded_path = ''
            self._loading_error = ''
            self._loaded_rss_mb = 0
            self._load_delta_mb = 0
            self._load_seconds = 0.0

    def _load(self):
        model_path = settings.local_model_file
        if self._model is not None and self._loaded_path == str(model_path):
            return self._model
        with self._lock:
            if self._model is not None and self._loaded_path == str(model_path):
                return self._model
            if not settings.local_model_enabled:
                raise ProviderUnavailableError('local model is disabled')
            if settings.local_model_runtime.lower() != 'llamacpp':
                raise ProviderUnavailableError(
                    f'unsupported local runtime: {settings.local_model_runtime}'
                )
            if not model_path.is_file():
                raise ModelNotFoundError(f'local GGUF not found: {model_path}')

            process = psutil.Process()
            rss_before = process.memory_info().rss
            started = perf_counter()
            try:
                llama_cpp = importlib.import_module('llama_cpp')
                kwargs = {
                    'model_path': str(model_path),
                    'n_ctx': settings.local_model_context_length,
                    'n_gpu_layers': settings.local_model_gpu_layers,
                    'verbose': False,
                }
                if settings.local_model_threads > 0:
                    kwargs['n_threads'] = settings.local_model_threads
                model = llama_cpp.Llama(**kwargs)
            except (ModelNotFoundError, ProviderUnavailableError):
                raise
            except Exception as error:
                self._loading_error = str(error)
                raise ProviderUnavailableError(
                    f'local llama.cpp runtime could not load: {error}'
                ) from error

            rss_after = process.memory_info().rss
            self._model = model
            self._loaded_path = str(model_path)
            self._loading_error = ''
            self._loaded_rss_mb = rss_after // 1024 // 1024
            self._load_delta_mb = max(0, rss_after - rss_before) // 1024 // 1024
            self._load_seconds = round(perf_counter() - started, 3)
            return model

    def complete(self, prompt: str, system: str) -> tuple[str, dict]:
        model = self._load()
        messages = [
            {'role': 'system', 'content': '\n\n'.join(filter(None, [IDENTITY_PROMPT, system]))},
            {'role': 'user', 'content': prompt},
        ]
        try:
            with self._generation_lock:
                result = model.create_chat_completion(
                    messages=messages,
                    max_tokens=settings.local_model_max_tokens,
                    temperature=settings.local_model_temperature,
                    stream=False,
                )
            text = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            return str(text).strip(), usage if isinstance(usage, dict) else {}
        except Exception as error:
            raise ProviderUnavailableError(
                f'local llama.cpp generation failed: {error}'
            ) from error

    def status(self) -> dict:
        model_path = settings.local_model_file
        runtime_available = importlib.util.find_spec('llama_cpp') is not None
        return {
            'provider': 'local',
            'display_name': 'Zevora Local AI',
            'enabled': settings.local_model_enabled,
            'configured': settings.local_model_enabled and model_path.is_file(),
            'runtime': settings.local_model_runtime,
            'runtime_available': runtime_available,
            'model_id': settings.local_model_name,
            'model_path': str(model_path),
            'model_exists': model_path.is_file(),
            'model_size_mb': (
                round(model_path.stat().st_size / 1024 / 1024, 1)
                if model_path.is_file() else 0
            ),
            'loaded': self._model is not None and self._loaded_path == str(model_path),
            'loading_error': self._loading_error,
            'context_length': settings.local_model_context_length,
            'max_output_tokens': settings.local_model_max_tokens,
            'process_rss_mb': psutil.Process().memory_info().rss // 1024 // 1024,
            'loaded_process_rss_mb': self._loaded_rss_mb,
            'load_delta_mb': self._load_delta_mb,
            'load_seconds': self._load_seconds,
        }


_RUNTIME = _LocalRuntime()


def local_runtime_status() -> dict:
    return _RUNTIME.status()


class LocalProvider(AIProvider):
    name = 'local'

    def __init__(self, model_id: str | None = None):
        self.default_model = model_id or settings.local_model_name
        self.supports_vision = False

    def configured(self) -> bool:
        return settings.local_model_enabled and settings.local_model_file.is_file()

    async def health_check(self) -> bool:
        status = local_runtime_status()
        return bool(
            status['enabled']
            and status['model_exists']
            and status['runtime'] == 'llamacpp'
            and status['runtime_available']
        )

    async def list_models(self) -> list[dict]:
        if not self.configured():
            return []
        status = local_runtime_status()
        return [{
            'model_id': self.default_model,
            'display_name': 'Zevora Local AI',
            'capabilities': [
                'general', 'coding', 'reasoning', 'tool_use', 'json',
                'local', 'private',
            ],
            'capability_profile': {
                'instruction_score': .78,
                'coding_score': .68,
                'reasoning_score': .72,
            },
            'context_window': settings.local_model_context_length,
            'max_output_tokens': settings.local_model_max_tokens,
            'supports_streaming': True,
            'supports_tools': True,
            'supports_vision': False,
            'supports_reasoning': True,
            'supports_code': True,
            'supports_json': True,
            'input_price': 0,
            'output_price': 0,
            'availability': 'verified' if status['runtime_available'] else 'unavailable',
            'health_status': 'healthy' if status['runtime_available'] else 'unavailable',
        }]

    async def complete(self, prompt: str, system: str = '') -> tuple[str, dict]:
        return await asyncio.to_thread(_RUNTIME.complete, prompt, system)

    async def complete_for_model(
        self, prompt: str, system: str = '', model_id: str = ''
    ) -> tuple[str, dict]:
        if model_id and model_id != self.default_model:
            raise ModelNotFoundError(f'local model not found: {model_id}')
        return await self.complete(prompt, system)

    async def chat(self, prompt: str, system: str = '') -> tuple[str, dict]:
        return await self.complete(prompt, system)

    async def stream(self, prompt: str, system: str = ''):
        response, _usage = await self.complete(prompt, system)
        yield response
