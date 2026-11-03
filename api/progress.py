"""In-process workflow progress tracking and SSE stream fan-out."""
import asyncio
from contextvars import ContextVar
from threading import Lock

from agent.security.redaction import redact

from api.helpers import _utc_timestamp

_progress_lock = Lock()
_progress_events: dict[str, dict] = {}
_stream_event_callback: ContextVar = ContextVar('stream_event_callback', default=None)
_workflow_request_id: ContextVar = ContextVar('workflow_request_id', default=None)
_stream_subscribers: dict[str, set[asyncio.Queue]] = {}

async def _emit_stream_event(event: dict) -> None:
    request_id = _workflow_request_id.get()
    if not request_id:
        return
    event_type = event.get('type', 'workflow')
    if event_type == 'attempt_start':
        _workflow_record(
            request_id, stage='PROVIDER_ROUTING', event='provider_selected', status='running',
            title='Provider selected',
            message=f"Trying {event.get('provider') or 'configured provider'}"
                    + (f" / {event['model']}" if event.get('model') else ''),
            data=event,
        )
    elif event_type == 'attempt_result':
        succeeded = event.get('status') == 'success'
        _workflow_record(
            request_id, stage='PROVIDER_ROUTING',
            event='provider_selected' if succeeded else 'provider_fallback',
            status='completed' if succeeded else 'failed',
            title='Provider response ready' if succeeded else 'Provider attempt failed',
            message=(
                f"Using {event.get('provider') or 'configured provider'}"
                if succeeded else event.get('failure_message') or 'Trying the next available provider'
            ),
            data=event,
        )
    else:
        _workflow_record(
            request_id,
            stage=event.get('stage', 'EXECUTION'), event=event.get('event', event_type),
            status=event.get('status', 'completed'), title=event.get('title', 'Agent activity'),
            message=event.get('message', ''), data=event.get('data'),
        )

def _progress_snapshot(request_id: str | None) -> dict | None:
    if not request_id:
        return None
    with _progress_lock:
        current = _progress_events.get(request_id)
        if current is None:
            return None
        snapshot = dict(current)
        snapshot['events'] = [dict(item) for item in current.get('events', [])]
        snapshot['stages'] = [dict(item) for item in current.get('stages', [])]
        if current.get('current'):
            snapshot['current'] = dict(current['current'])
        return snapshot


def _progress_start(request_id: str) -> None:
    with _progress_lock:
        _progress_events[request_id] = {
            'request_id': request_id, 'status': 'queued', 'state': 'queued',
            'sequence': 0, 'events': [], 'stages': [],
        }
        while len(_progress_events) > 128:
            _progress_events.pop(next(iter(_progress_events)))


def _workflow_record(
    request_id: str | None, *, stage: str, event: str, status: str,
    title: str, message: str = '', data: dict | None = None,
) -> dict | None:
    if not request_id:
        return None
    safe_stage = str(stage or 'EXECUTION').upper()[:48]
    safe_status = str(status or 'completed').lower()[:24]
    safe_message = redact(str(message or ''))[:500]
    state_by_stage = {
        'RECEIVED': 'queued', 'UNDERSTAND': 'running', 'UNDERSTANDING': 'running',
        'ATTACHMENTS': 'running', 'INSPECT': 'running', 'WORKSPACE_DISCOVERY': 'running',
        'RETRIEVE': 'running', 'CONTEXT_RETRIEVAL': 'running', 'REASON': 'running',
        'ANALYSIS': 'running', 'PLAN': 'running', 'PLANNING': 'running',
        'APPROVAL': 'waiting_approval', 'ACT': 'executing', 'EXECUTION': 'executing',
        'VERIFY': 'verifying', 'VERIFICATION': 'verifying', 'FIX': 'repairing',
        'DEBUGGING': 'repairing', 'FINAL_RESPONSE': 'finalizing', 'FINALIZATION': 'finalizing',
        'COMPLETED': 'completed', 'FAILED': 'failed', 'CANCELLED': 'cancelled',
    }
    with _progress_lock:
        current = _progress_events.get(request_id)
        if current is None:
            return None
        current['sequence'] += 1
        item = {
            'type': 'workflow', 'request_id': request_id,
            'sequence': current['sequence'], 'timestamp': _utc_timestamp(),
            'stage': safe_stage, 'event': str(event or 'stage_completed')[:64],
            'status': safe_status, 'title': redact(str(title or safe_stage))[:120],
            'message': safe_message,
        }
        if data:
            item['data'] = data
        current['events'].append(item)
        current['current'] = item
        current['state'] = state_by_stage.get(safe_stage, current.get('state', 'running'))
        current['status'] = current['state'] if current['state'] in {'completed', 'failed', 'cancelled'} else 'running'
        subscribers = list(_stream_subscribers.get(request_id, ()))
    for queue in subscribers:
        queue.put_nowait({'type': 'workflow', **item})
    callback = _stream_event_callback.get()
    if callback is not None:
        result = callback(dict(item))
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)
    return item


def _progress_update(request_id: str | None, stage: str, detail: str = '', status: str = 'completed') -> None:
    event_status = str(status or 'completed').lower()
    event_name = (
        'stage_started' if event_status == 'running' else
        'stage_failed' if event_status in {'failed', 'cancelled'} else 'stage_completed'
    )
    title = str(stage or 'Workflow').replace('_', ' ').title()
    item = _workflow_record(
        request_id, stage=stage, event=event_name, status=event_status,
        title=title, message=detail,
    )
    if item is None:
        return
    with _progress_lock:
        current = _progress_events.get(request_id)
        if current is not None:
            current['stages'].append({
                'stage': item['stage'], 'detail': item['message'], 'status': item['status'],
                'sequence': item['sequence'],
            })


def _progress_finish(request_id: str | None, status: str = 'completed') -> None:
    if not request_id:
        return
    with _progress_lock:
        current = _progress_events.get(request_id)
        if current:
            current['status'] = status
            current['state'] = status
