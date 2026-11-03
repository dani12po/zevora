"""Stateless helpers shared by the gateway endpoints and orchestrators."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from agent.providers.errors import (
    ModelNotFoundError,
    ProviderUnavailableError,
    failure_details,
)
from agent.routing.hybrid_router import Route
from agent.security.redaction import redact

_AGENTIC_LOG_INSTRUCTION = '''
Before answering, write a short workflow in a <agentic_log>...</agentic_log> block using bullet points,
then write the final answer normally. Do not claim that you read files, ran commands, or changed code
inside the agentic log unless this request includes authoritative tool observations proving it; otherwise
describe analysis and answer composition only. Do not emit any UI toolbar markup.
'''.strip()

def _parse_agentic_response(response: str) -> tuple[str, list[str] | None]:
    """Extract a closed model workflow block without damaging malformed responses."""
    match = re.search(
        r'<agentic_log\s*>(.*?)</agentic_log\s*>',
        response or '',
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return response, None
    entries = []
    for line in match.group(1).splitlines():
        cleaned = re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', '', line).strip()
        if cleaned:
            entries.append(cleaned)
    clean_response = (response[:match.start()] + response[match.end():]).strip()
    return clean_response, entries

def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)

def _provider_service_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(404, {
            'code': 'PROVIDER_NOT_FOUND', 'message': 'Provider was not found.',
        })
    if isinstance(error, PermissionError):
        return HTTPException(403, {
            'code': 'PROVIDER_RUNTIME_APPROVAL_REQUIRED', 'message': redact(str(error)),
        })
    return HTTPException(400, {
        'code': 'PROVIDER_CONFIGURATION_INVALID', 'message': redact(str(error)),
    })

_CHAT_METADATA_KEYS = (
    'route','reason','provider','model','tools','quality_score','attachments',
    'agent_trace','agentic_log','fallback_trace','estimated_cost','context_hash','project_files',
    'project_discovery','context_status','flow','execution_ms','workflow',
)

def _chat_metadata(result):
    return {key:result.get(key) for key in _CHAT_METADATA_KEYS}

def _sse_frame(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=True, separators=(',', ':'))}\n\n"

async def _stream_error(error: Exception) -> dict:
    if isinstance(error, HTTPException):
        detail = error.detail
        payload = detail if isinstance(detail, dict) else {'message': str(detail)}
        return {
            'code': payload.get('code') or ('AI_EXECUTION_ERROR' if error.status_code >= 500 else 'REQUEST_ERROR'),
            'message': payload.get('message', 'Gateway request failed'),
            **{key: value for key, value in payload.items() if key not in {'code', 'message'}},
        }
    return {'code': 'INTERNAL_ERROR', 'message': 'An unexpected gateway error occurred. Retry the request.'}

def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

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

def _fallback_failure_message(fallback_trace: list[dict]) -> str:
    """Describe only the provider classes that were actually attempted."""
    failed = [item for item in fallback_trace if item.get('status') == 'failed']
    local_attempted = any(item.get('source') == 'local_model' for item in failed)
    cloud_names = list(dict.fromkeys(
        str(item.get('provider') or 'cloud').strip()
        for item in failed if item.get('source') == 'cloud_provider'
    ))
    if local_attempted and not cloud_names:
        return (
            'Local Intelligence gagal, dan tidak ada provider cloud yang terkonfigurasi '
            'untuk fallback. Tambahkan API key di halaman Providers agar ada cadangan otomatis.'
        )
    if local_attempted:
        providers = ', '.join(cloud_names)
        return (
            f'Local Intelligence dan {len(cloud_names)} provider cloud ({providers}) '
            'semuanya gagal merespons.'
        )
    if cloud_names:
        providers = ', '.join(cloud_names)
        return (
            f'{len(cloud_names)} provider cloud ({providers}) semuanya gagal merespons. '
            'Local Intelligence tidak dicoba karena dinonaktifkan atau tidak dikonfigurasi.'
        )
    return (
        'Tidak ada model AI lokal atau provider cloud yang siap digunakan. '
        'Periksa Local Intelligence atau konfigurasi provider di halaman Providers.'
    )

def _usage_tokens(usage: dict) -> tuple[int, int]:
    input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens') or 0
    output_tokens = usage.get('output_tokens') or usage.get('completion_tokens') or 0
    return max(0, int(input_tokens)), max(0, int(output_tokens))

def _estimated_cost(model: dict | None, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from registry prices expressed per million tokens."""
    if not model:
        return 0.0
    input_price = max(0.0, float(model.get('input_price') or 0))
    output_price = max(0.0, float(model.get('output_price') or 0))
    return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)

def _model_metadata(models: list[dict], provider: str | None, model_id: str | None) -> dict | None:
    return next((
        item for item in models
        if item.get('provider') == provider and item.get('model_id') == model_id
    ), None)

def _flow_status(*, workspace: str, discovery: str, context: str, route: str,
                 action: str, verification: str, knowledge: str) -> dict:
    return {
        'workspace': workspace, 'discovery': discovery, 'context': context,
        'route': route, 'action': action, 'verification': verification,
        'knowledge': knowledge,
    }

def _action_receipt(root: Path, trace) -> str:
    """Build a factual user response solely from successful MCP observations."""
    lines = ['Workspace actions completed successfully.', '']
    for item in trace.observations:
        output = item.get('output')
        relative = None
        if isinstance(output, dict):
            relative = output.get('path') or output.get('destination')
        if not relative:
            lines.append(f"- {item['tool']}: completed")
            continue

        target = (root / str(relative)).resolve()
        details = []
        if isinstance(output, dict) and output.get('line_count') is not None:
            details.append(f"{output['line_count']} lines")
        if isinstance(output, dict) and output.get('bytes') is not None:
            details.append(f"{output['bytes']} bytes")
        suffix = f" ({', '.join(details)})" if details else ''
        lines.append(f"**{item['tool']}** — `{target}`{suffix}")

        preview = output.get('preview') if isinstance(output, dict) else None
        if preview is not None:
            # Choose a fence longer than any backtick run in the observed text.
            # The preview remains unchanged while its markdown stays inert.
            preview_text = str(preview)
            longest_run = max(
                (len(match.group(0)) for match in re.finditer(r'`+', preview_text)),
                default=0,
            )
            fence = '`' * max(3, longest_run + 1)
            lines.extend(['', f'{fence}zevora-file-preview', preview_text, fence])
        lines.append('')
    return '\n'.join(lines).rstrip()

def _requires_workspace_agent(prompt: str) -> bool:
    """Detect explicit filesystem/workspace work before normal chat generation."""
    text = prompt.lower()
    file_terms = (
        'file', 'folder', 'directory', 'local storage', 'penyimpanan', 'disk ',
        'html', 'javascript', 'css', 'script', 'kode', 'code', 'simpan', 'tulis',
        'buatkan', 'buat file', 'create file', 'write file', 'save file', 'edit file',
    )
    action_terms = (
        'buat', 'buatkan', 'create', 'write', 'tulis', 'simpan', 'save', 'edit',
        'ubah', 'update', 'delete', 'hapus', 'move', 'copy', 'jalankan', 'run',
        'baca', 'read', 'inspect', 'lihat', 'list',
    )
    return any(term in text for term in file_terms) and any(term in text for term in action_terms)
