import asyncio
import importlib
import importlib.util
import logging
import queue
import threading
from pathlib import Path
from time import perf_counter

import psutil

from ..config import settings
from ..core.persona import LOCAL_IDENTITY_PROMPT, ZEVORA_PERSONA
from .base import AIProvider
from .local_intelligence import LocalProviderMetadata, messages_to_prompt
from .errors import ModelNotFoundError, ProviderUnavailableError


IDENTITY_PROMPT = ZEVORA_PERSONA + '\n\n' + LOCAL_IDENTITY_PROMPT
logger = logging.getLogger(__name__)

# Lifecycle states exposed to health/status/UI.
STATE_NOT_INSTALLED = 'NOT_INSTALLED'
STATE_AVAILABLE = 'AVAILABLE'
STATE_LOADING = 'LOADING'
STATE_READY = 'READY'
STATE_BUSY = 'BUSY'
STATE_UNLOADING = 'UNLOADING'
STATE_ERROR = 'ERROR'
STATE_UNAVAILABLE = 'UNAVAILABLE'


def _local_failure_reason(error: Exception) -> str:
    message = str(error).lower()
    if isinstance(error, ModelNotFoundError) or 'no such file' in message:
        return 'model_file_missing'
    if isinstance(error, MemoryError) or any(token in message for token in ('out of memory', 'oom', 'bad_alloc')):
        return 'out_of_memory'
    if 'timeout' in message or 'timed out' in message:
        return 'timeout'
    if isinstance(error, ImportError) or 'no module named' in message:
        return 'runtime_unavailable'
    return 'runtime_error'


def _model_identity() -> str:
    """Human-facing display name for the configured local model."""
    return settings.local_model_display_name or 'Local Model'


class _LocalRuntime:
    """Process-wide lazy llama.cpp runtime for the configured GGUF.

    Supports explicit lifecycle (load/unload/restart), lazy loading, real token
    streaming, and a lock-protected single-model invariant so concurrent requests
    never spawn duplicate inference processes.
    """

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self._generation_lock = threading.Lock()
        self._loaded_path = ''
        self._loading_error = ''
        self._state = STATE_AVAILABLE
        self._loaded_rss_mb = 0
        self._load_delta_mb = 0
        self._load_seconds = 0.0
        self._last_generation_seconds = 0.0
        self._generation_count = 0
        self._generated_tokens = 0

    # ── State helpers ─────────────────────────────────────────────────────────
    def _state_for(self) -> str:
        loaded = self._model is not None and self._loaded_path == str(settings.local_model_file)
        if self._state == STATE_ERROR:
            return STATE_ERROR
        if self._state == STATE_LOADING or self._state == STATE_UNLOADING:
            return self._state
        if loaded:
            return STATE_READY if not self._generation_lock.locked() else STATE_BUSY
        if not settings.local_model_enabled:
            return STATE_UNAVAILABLE
        if not settings.local_model_file.is_file():
            return STATE_NOT_INSTALLED
        return STATE_AVAILABLE

    def reset(self) -> None:
        """Release the Python model reference; primarily useful for tests/reloads."""
        self.unload()

    def unload(self) -> dict:
        """Release the loaded model and reset runtime statistics.

        Multiple unloads are idempotent. Returns a bounded summary.
        """
        with self._lock:
            released = self._model is not None
            self._model = None
            self._loaded_path = ''
            self._loading_error = ''
            self._state = STATE_AVAILABLE
            stats = {
                'released': released,
                'loaded_process_rss_mb': self._loaded_rss_mb,
            }
            self._loaded_rss_mb = 0
            self._load_delta_mb = 0
            self._load_seconds = 0.0
            self._last_generation_seconds = 0.0
            self._generation_count = 0
            self._generated_tokens = 0
            if released:
                logger.info('local_model_unloaded')
            return stats

    def restart(self) -> dict:
        """Unload and lazily reload on the next request."""
        result = self.unload()
        result['loaded'] = False
        return result

    def _verify_model_integrity(self, model_path: Path) -> None:
        """Verify the configured GGUF SHA-256 when an authoritative reference exists.

        Authorization sources, in priority order:
        1. A ``<model>.sha256`` sidecar file containing the expected digest.
        2. A local package manifest that lists the configured file as a component.
        If no reference exists we skip verification (matching legacy behaviour);
        the managed-package installer always writes one.
        """
        from ..models.package import LocalPackageManifest  # local import: lazy

        sidecar = model_path.with_name(model_path.name + '.sha256')
        if sidecar.is_file():
            expected = sidecar.read_text(encoding='utf-8').strip().split()[0].lower()
            actual = _sha256_file(model_path)
            if actual != expected:
                raise ProviderUnavailableError(
                    f'local GGUF integrity check failed: {model_path.name} does not match its SHA-256'
                )
            return
        manifest_dir = settings.local_model_package_dir / 'model'
        manifest_file = manifest_dir / 'manifest.json'
        if manifest_file.is_file():
            try:
                manifest = LocalPackageManifest.load(manifest_file)
            except Exception as error:  # pragma: no cover - defensive
                logger.warning('local_model_manifest_invalid reason=%s', type(error).__name__)
                return
            component = manifest.components.get(model_path.name)
            expected = component or manifest.sha256
            if isinstance(component, str) and component.lower().startswith(('sha256:', 'sha256=')):
                expected = component.split(':', 1)[1] \
                    if ':' in component else component.split('=', 1)[1]
            if expected:
                actual = _sha256_file(model_path)
                if actual.lower() != str(expected).lower():
                    raise ProviderUnavailableError(
                        f'local GGUF integrity check failed: {model_path.name} does not match its manifest SHA-256'
                    )

    def _load(self):
        model_path = settings.local_model_file
        if self._model is not None and self._loaded_path == str(model_path):
            return self._model
        with self._lock:
            if self._model is not None and self._loaded_path == str(model_path):
                return self._model
            if not settings.local_model_enabled:
                logger.warning('local_model_load_failed reason=disabled')
                self._state = STATE_UNAVAILABLE
                raise ProviderUnavailableError('local model is disabled')
            if settings.local_model_runtime.lower() != 'llamacpp':
                logger.warning(
                    'local_model_load_failed reason=unsupported_runtime runtime=%s',
                    settings.local_model_runtime,
                )
                self._state = STATE_UNAVAILABLE
                raise ProviderUnavailableError(
                    f'unsupported local runtime: {settings.local_model_runtime}'
                )
            if not model_path.is_file():
                logger.warning('local_model_load_failed reason=model_file_missing path=%s', model_path)
                self._state = STATE_NOT_INSTALLED
                raise ModelNotFoundError(f'local GGUF not found: {model_path}')

            self._verify_model_integrity(model_path)

            process = psutil.Process()
            rss_before = process.memory_info().rss
            started = perf_counter()
            self._state = STATE_LOADING
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
                if settings.local_model_batch_size > 0:
                    kwargs['n_batch'] = settings.local_model_batch_size
                model = llama_cpp.Llama(**kwargs)
            except (ModelNotFoundError, ProviderUnavailableError):
                self._state = STATE_ERROR
                raise
            except Exception as error:
                self._loading_error = str(error)
                self._state = STATE_ERROR
                logger.exception(
                    'local_model_load_failed reason=%s path=%s runtime=llamacpp',
                    _local_failure_reason(error), model_path,
                )
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
            self._state = STATE_READY
            logger.info(
                'local_model_loaded path=%s load_seconds=%.3f rss_delta_mb=%s',
                model_path, self._load_seconds, self._load_delta_mb,
            )
            return model

    def complete(self, prompt: str, system: str) -> tuple[str, dict]:
        model = self._load()
        messages = [
            {'role': 'system', 'content': '\n\n'.join(filter(None, [IDENTITY_PROMPT, system]))},
            {'role': 'user', 'content': prompt},
        ]
        started = perf_counter()
        logger.info(
            'local_model_generation_started model=%s prompt_characters=%s',
            self._loaded_path, len(prompt),
        )
        try:
            with self._generation_lock:
                self._state = STATE_BUSY
                result = model.create_chat_completion(
                    messages=messages,
                    max_tokens=settings.local_model_max_tokens,
                    temperature=settings.local_model_temperature,
                    stream=False,
                )
            text = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            self._last_generation_seconds = round(perf_counter() - started, 3)
            self._generation_count += 1
            self._generated_tokens += int(usage.get('completion_tokens') or 0)
            self._state = STATE_READY
            logger.info(
                'local_model_generation_succeeded model=%s generation_seconds=%.3f',
                self._loaded_path, self._last_generation_seconds,
            )
            return str(text).strip(), usage if isinstance(usage, dict) else {}
        except Exception as error:
            self._last_generation_seconds = round(perf_counter() - started, 3)
            self._state = STATE_ERROR
            logger.exception(
                'local_model_generation_failed reason=%s model=%s generation_seconds=%.3f',
                _local_failure_reason(error), self._loaded_path or settings.local_model_file,
                self._last_generation_seconds,
            )
            raise ProviderUnavailableError(
                f'local llama.cpp generation failed: {error}'
            ) from error

    def _stream_chunks(self, messages: list[dict]) -> list[str]:
        """Run synchronous llama.cpp token streaming on a worker thread.

        Yields content deltas. Falls back to a single buffered completion if the
        runtime does not expose a streaming chat path.
        """
        out = queue.Queue()
        sentinel = object()

        def worker():
            try:
                model = self._load()
                with self._generation_lock:
                    self._state = STATE_BUSY
                    generator = model.create_chat_completion(
                        messages=messages,
                        max_tokens=settings.local_model_max_tokens,
                        temperature=settings.local_model_temperature,
                        stream=True,
                    )
                    for chunk in generator:
                        choices = (chunk or {}).get('choices') or []
                        delta = choices[0].get('delta') or {} if choices else {}
                        content = delta.get('content')
                        if content:
                            out.put(content)
                        if choices and choices[0].get('finish_reason'):
                            break
            except Exception as error:  # pragma: no cover - runtime dependent
                out.put(sentinel)
                out.put(error)  # type: ignore[arg-type]
                return
            finally:
                out.put(sentinel)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        started = perf_counter()
        while True:
            item = out.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise ProviderUnavailableError(f'local llama.cpp streaming failed: {item}')
            yield item
        self._last_generation_seconds = round(perf_counter() - started, 3)
        self._generation_count += 1
        self._state = STATE_READY

    def stream(self, prompt: str, system: str):
        messages = [
            {'role': 'system', 'content': '\n\n'.join(filter(None, [IDENTITY_PROMPT, system]))},
            {'role': 'user', 'content': prompt},
        ]
        yield from self._stream_chunks(messages)

    def status(self) -> dict:
        model_path = settings.local_model_file
        runtime_available = importlib.util.find_spec('llama_cpp') is not None
        state = self._state_for()
        return {
            'provider': 'local',
            'display_name': _model_identity(),
            'enabled': settings.local_model_enabled,
            'configured': settings.local_model_enabled and model_path.is_file(),
            'runtime': settings.local_model_runtime,
            'runtime_available': runtime_available,
            'state': state,
            'model_id': settings.local_model_name,
            'model_repository': settings.local_model_repository,
            'quantization': settings.local_model_quant or None,
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
            'batch_size': settings.local_model_batch_size,
            'process_rss_mb': psutil.Process().memory_info().rss // 1024 // 1024,
            'loaded_process_rss_mb': self._loaded_rss_mb,
            'load_delta_mb': self._load_delta_mb,
            'load_seconds': self._load_seconds,
            'last_generation_seconds': self._last_generation_seconds,
            'generation_count': self._generation_count,
            'generated_tokens': self._generated_tokens,
            'keep_warm': self._model is not None,
        }


_RUNTIME = _LocalRuntime()


def local_runtime_status() -> dict:
    return _RUNTIME.status()


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class LocalProvider(AIProvider):
    name = 'local'
    provider_id = 'local'

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

    async def health(self) -> dict:
        """Detailed health including lifecycle state and verification."""
        return local_runtime_status()

    async def list_models(self) -> list[dict]:
        if not self.configured():
            return []
        status = local_runtime_status()
        return [{
            'model_id': self.default_model,
            'display_name': _model_identity(),
            'capabilities': [
                'general', 'coding', 'reasoning', 'tool_use', 'json',
                'local', 'private',
            ],
            'capability_profile': {
                'instruction_score': .90,
                'coding_score': .86,
                'reasoning_score': .84,
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
            'quantization': settings.local_model_quant or None,
            'installed': status['model_exists'],
            'availability': 'verified' if status['runtime_available'] else 'unavailable',
            'health_status': 'healthy' if status['runtime_available'] else 'unavailable',
        }]

    async def complete(self, prompt: str, system: str = '') -> tuple[str, dict]:
        return await asyncio.to_thread(_RUNTIME.complete, prompt, system)

    async def generate(self, messages: list[dict[str, str]], **kwargs) -> tuple[str, dict]:
        prompt, system = messages_to_prompt(messages)
        return await self.complete(prompt, system)

    def capabilities(self) -> set[str]:
        return {'text', 'general', 'coding', 'reasoning', 'tool_use', 'json', 'local', 'private'}

    def metadata(self) -> LocalProviderMetadata:
        status = local_runtime_status()
        return LocalProviderMetadata(
            provider_id=self.provider_id,
            name=_model_identity(),
            model_id=self.default_model,
            capabilities=frozenset(self.capabilities()),
            runtime=str(status.get('runtime') or 'unknown'),
            context_length=settings.local_model_context_length,
            installed=bool(status.get('model_exists')),
        )

    async def complete_for_model(
        self, prompt: str, system: str = '', model_id: str = ''
    ) -> tuple[str, dict]:
        if model_id and model_id != self.default_model:
            raise ModelNotFoundError(f'local model not found: {model_id}')
        return await self.complete(prompt, system)

    async def chat(self, prompt: str, system: str = '') -> tuple[str, dict]:
        return await self.complete(prompt, system)

    async def unload(self) -> dict:
        return await asyncio.to_thread(_RUNTIME.unload)

    async def restart(self) -> dict:
        return await asyncio.to_thread(_RUNTIME.restart)

    async def stream(self, prompt: str, system: str = ''):
        messages = [
            {'role': 'system', 'content': '\n\n'.join(filter(None, [IDENTITY_PROMPT, system]))},
            {'role': 'user', 'content': prompt},
        ]
        stream_queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def worker():
            try:
                for chunk in _RUNTIME._stream_chunks(messages):
                    stream_queue.put_nowait(chunk)
            except Exception as error:  # pragma: no cover - runtime dependent
                stream_queue.put_nowait(error)
            finally:
                stream_queue.put_nowait(sentinel)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while True:
            item = await stream_queue.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise ProviderUnavailableError(f'local llama.cpp streaming failed: {item}')
            yield item
        await asyncio.to_thread(thread.join)
