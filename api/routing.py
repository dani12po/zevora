"""Model routing, provider fallback, and hybrid completion orchestration."""
import asyncio
from time import perf_counter

from fastapi import HTTPException
from agent.providers.errors import (
    ModelNotFoundError,
    ProviderUnavailableError,
    failure_details,
)
from agent.routing.hybrid_router import Route
from agent.routing.quality_gate import validate
from agent.security.redaction import redact

from api.helpers import (
    _fallback_failure_message, _model_metadata, _usage_tokens, _estimated_cost,
)
import main

def _filter_routing_models(
    available_models: list[dict], mode: str = 'auto',
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    if mode == 'local':
        return [item for item in available_models if item.get('provider') in {'local', 'local_remote'}]
    if mode == 'remote_local':
        return [item for item in available_models if item.get('provider') == 'local_remote']
    if mode in {'provider', 'model'}:
        return [
            item for item in available_models
            if item.get('provider') == provider
            and (mode != 'model' or item.get('model_id') == model)
        ]
    return available_models


async def _routing_candidates(
    prompt: str, context_tokens: int = 0, mode: str = 'auto',
    provider: str | None = None, model: str | None = None,
    require_native_tools: bool = True,
) -> tuple[list[dict], list]:
    """Resolve candidates, refreshing configured providers when the registry is stale."""
    available_models = _filter_routing_models(
        main.model_registry.list(), mode, provider, model
    )
    candidates = main._cloud_candidates(
        prompt, available_models, context_tokens, require_native_tools
    )
    if candidates:
        return available_models, candidates

    refresh_provider = 'local' if mode == 'local' else provider
    try:
        await asyncio.wait_for(
            main.ProviderDiscovery(main.model_registry).refresh(refresh_provider),
            timeout=main.settings.discovery_timeout_seconds,
        )
    except asyncio.TimeoutError:
        # A slow health/model-list probe must not block response generation indefinitely.
        pass
    available_models = _filter_routing_models(
        main.model_registry.list(), mode, provider, model
    )
    return available_models, main._cloud_candidates(
        prompt, available_models, context_tokens, require_native_tools
    )


def _cloud_candidates(
    prompt: str, available_models: list[dict], context_tokens: int = 0,
    require_native_tools: bool = True,
) -> list:
    """Build the hybrid provider/model fallback sequence.

    The legacy name is retained for planner and extension compatibility.
    """
    performance = main.store.routing_performance()
    if hasattr(main.hybrid_router, 'candidates'):
        candidates = main.hybrid_router.candidates(
            prompt,
            available_models,
            performance=performance,
            context_tokens=context_tokens,
            require_native_tools=require_native_tools,
        )
        if not main.settings.cloud_fallback:
            return candidates[:1]
        return candidates[:max(1, main.settings.routing_max_attempts)]

    primary = main.hybrid_router.decide(
        prompt,
        available_models,
        performance=performance,
        context_tokens=context_tokens,
        require_native_tools=require_native_tools,
    )
    if primary.route not in {Route.LOCAL, Route.CLOUD}:
        return []
    candidates = [primary]
    if main.settings.cloud_fallback:
        fallback = main.hybrid_router.decide(
            prompt, available_models, exclude_providers={primary.provider},
            performance=performance, context_tokens=context_tokens,
            require_native_tools=require_native_tools,
        )
        if fallback.route in {Route.LOCAL, Route.CLOUD}:
            candidates.append(fallback)
    return candidates


async def _provider_completion(candidate, prompt: str, system: str,
                               images: list[dict] | None = None):
    provider = main.get_provider(candidate.provider)
    if images:
        return await provider.complete_multimodal(
            prompt, images, system, candidate.model_id or ''
        )
    if candidate.model_id and hasattr(provider, 'complete_for_model'):
        return await provider.complete_for_model(prompt, system, candidate.model_id)
    return await provider.complete(prompt, system)

# Stable fallback reason codes recorded in the fallback trace (Phase 26).
# Provider messages may already carry one of these codes; otherwise the
# provider + error type determines the classification below.
_FALLBACK_REASON_CODES = (
    'LOCAL_MODEL_MISSING',
    'LOCAL_MODEL_RESOURCE_INSUFFICIENT',
    'LOCAL_MODEL_RUNTIME_ERROR',
    'REMOTE_ENDPOINT_UNAVAILABLE',
    'REMOTE_MODEL_NOT_FOUND',
    'QUALITY_GATE_REJECTED',
)


def _failure_reason(candidate, error: Exception) -> tuple[str, str]:
    """Return a stable, secret-free failure classification for the chat UI."""
    message = redact(str(error))[:300]
    for code in _FALLBACK_REASON_CODES:
        if code in str(error):
            return code, message
    provider = str(candidate.provider or '').lower()
    if provider == 'local_remote':
        if isinstance(error, ModelNotFoundError):
            return 'REMOTE_MODEL_NOT_FOUND', 'The remote Lexi endpoint does not serve the requested model.'
        return 'REMOTE_ENDPOINT_UNAVAILABLE', 'The remote Lexi endpoint could not be reached.'
    if provider == 'local':
        if isinstance(error, ModelNotFoundError):
            return 'LOCAL_MODEL_MISSING', 'The embedded Lexi model file is not installed.'
        if isinstance(error, ProviderUnavailableError):
            return 'LOCAL_MODEL_RUNTIME_ERROR', 'The embedded Lexi runtime could not complete the request.'
    return failure_details(error, local=candidate.route is Route.LOCAL)


def _attempt_record(candidate, status: str, error: Exception | None = None) -> dict:
    record = {
        'source': 'local_model' if candidate.route is Route.LOCAL else 'cloud_provider',
        'route': candidate.route.value, 'provider': candidate.provider,
        'model': candidate.model_id or '', 'status': status,
    }
    if error is not None:
        failure_reason, failure_message = _failure_reason(candidate, error)
        record.update({
            'error': type(error).__name__,
            'failure_reason': failure_reason,
            'failure_message': failure_message,
        })
    return record


async def _cloud_completion(prompt: str, system: str, requested_format: str = '',
                            response_validator=None,
                            require_native_tools: bool = True,
                            routing_prompt: str | None = None) -> dict:
    """Run hybrid completion; legacy name retained for caller compatibility."""
    classification_prompt = routing_prompt if routing_prompt is not None else prompt
    extra_context_tokens = max(
        0, main.estimate_tokens(prompt) - main.estimate_tokens(classification_prompt)
    )
    available_models, candidates = await main._routing_candidates(
        classification_prompt, context_tokens=extra_context_tokens,
        require_native_tools=require_native_tools,
    )
    if not candidates:
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': _fallback_failure_message([]),
            'fallback_trace': [],
        })

    fallback_trace: list[dict] = []
    for candidate in candidates:
        started = perf_counter()
        await main._emit_stream_event({
            'type': 'attempt_start', **_attempt_record(candidate, 'running'),
        })
        try:
            response, usage = await main._provider_completion(candidate, prompt, system)
            checked = validate(response, requested_format)
            if not checked['accepted']:
                raise ValueError('Provider returned an invalid response format')
            if response_validator:
                response_validator(response)
            input_tokens, output_tokens = _usage_tokens(usage)
            model_metadata = _model_metadata(
                available_models, candidate.provider, candidate.model_id
            )
            model = candidate.model_id or ''
            estimated_cost = _estimated_cost(model_metadata, input_tokens, output_tokens)
            latency = int((perf_counter() - started) * 1000)
            main.store.add_routing_experience(
                candidate.route.value, candidate.provider, model,
                ','.join(candidate.task_type), True, checked['quality_score'], latency,
                candidate.tools,
            )
            with main.store.connection() as conn:
                conn.execute(
                    "INSERT INTO usage_events(provider,model,task_type,input_tokens,output_tokens,estimated_cost,cache_hit,created_at) VALUES(?,?,?,?,?,?,?,datetime('now'))",
                    (candidate.provider, model, 'planning', input_tokens,
                     output_tokens, estimated_cost, 0),
                )
            success_record = _attempt_record(candidate, 'success')
            fallback_trace.append(success_record)
            await main._emit_stream_event({'type': 'attempt_result', **success_record})
            return {
                'response': response, 'usage': usage, 'decision': candidate,
                'provider': candidate.provider, 'model': model,
                'estimated_cost': estimated_cost, 'fallback_trace': fallback_trace,
            }
        except Exception as error:
            latency = int((perf_counter() - started) * 1000)
            main.store.add_routing_experience(
                candidate.route.value, candidate.provider, candidate.model_id or '',
                ','.join(candidate.task_type), False, 0.0, latency, candidate.tools,
            )
            failure_record = _attempt_record(candidate, 'failed', error)
            fallback_trace.append(failure_record)
            await main._emit_stream_event({'type': 'attempt_result', **failure_record})

    raise HTTPException(503, {
        'code': 'AI_EXECUTION_ERROR',
        'message': _fallback_failure_message(fallback_trace),
        'fallback_trace': fallback_trace,
    })
