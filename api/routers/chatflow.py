"""Chat streaming, cancellation, and project indexing endpoints."""
import asyncio
import json
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse


import main
from agent.core.project_index import project_context
from main import app
from api.schemas import ChatMessageRequest, ChatRequest, IndexRequest

def _sse_frame(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=True, separators=(',', ':'))}\n\n"


async def _execute_chat_request(body: ChatRequest, request_id: str) -> dict:
    main._progress_start(request_id)
    request_token = main._workflow_request_id.set(request_id)
    main._progress_update(request_id, 'RECEIVED', 'Request received')
    main._progress_update(request_id, 'UNDERSTANDING', 'Understanding the request', 'running')
    chat_id = body.conversation_id
    if not chat_id:
        chat_id = main.workspace_manager.create_chat(body.message[:80], body.project_id)['id']
    existing = main.workspace_manager.get_chat(chat_id)
    if not existing:
        raise HTTPException(404, 'Conversation not found')
    if body.project_id is not None and existing['project_id'] != body.project_id:
        project = main.workspace_manager.get(body.project_id)
        if not project:
            raise HTTPException(404, 'Project not found')
        with main.workspace_manager.connection() as conn:
            conn.execute('UPDATE chats SET project_id=? WHERE id=?', (body.project_id, chat_id))
        existing = main.workspace_manager.get_chat(chat_id)
    if existing['title'] == 'New chat':
        main.workspace_manager.set_title(chat_id, body.message[:80])
    try:
        result = await main.chat_message(
            chat_id,
            ChatMessageRequest(
                content=body.message, mode=body.mode, provider=body.provider,
                model=body.model, attachments=body.attachments, actions=body.actions,
                progress_id=request_id,
            ),
        )
        main._progress_update(request_id, 'COMPLETED', 'Workflow completed')
        main._progress_finish(request_id)
        workflow = main._progress_snapshot(request_id)
        result['workflow'] = workflow
        main.workspace_manager.update_assistant_message(
            chat_id, result['message_id'], result['response'], main._chat_metadata(result),
        )
        return {'ok': True, **result, 'conversation_id': chat_id, 'request_id': request_id}
    except asyncio.CancelledError:
        snapshot = main._progress_snapshot(request_id) or {}
        if snapshot.get('status') != 'cancelled':
            main._progress_update(request_id, 'CANCELLED', 'Request cancelled', 'cancelled')
            main._progress_finish(request_id, 'cancelled')
        raise
    except Exception:
        main._progress_update(request_id, 'FAILED', 'Request failed during processing', 'failed')
        main._progress_finish(request_id, 'failed')
        raise
    finally:
        main._workflow_request_id.reset(request_token)


async def _chat_request(body: ChatRequest) -> dict:
    request_id = body.request_id or 'zv-' + uuid.uuid4().hex[:12]
    current = main._chat_runs.get(request_id)
    if current is None:
        current = asyncio.create_task(_execute_chat_request(body, request_id))
        main._chat_runs[request_id] = current
        if len(main._chat_runs) > 128:
            for key, run in list(main._chat_runs.items()):
                if key != request_id and run.done():
                    main._chat_runs.pop(key, None)
                if len(main._chat_runs) <= 128:
                    break
    return await asyncio.shield(current)


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


@app.post('/api/chat/stream')
async def chat_stream(body: ChatRequest, request: Request):
    request_id = body.request_id or 'zv-' + uuid.uuid4().hex[:12]
    body.request_id = request_id
    queue: asyncio.Queue = asyncio.Queue()
    with main._progress_lock:
        main._stream_subscribers.setdefault(request_id, set()).add(queue)
        snapshot = main._progress_events.get(request_id)
        replay = [dict(item) for item in (snapshot or {}).get('events', [])]

    async def run() -> None:
        try:
            result = await main._chat_request(body)
            await queue.put({'type': 'final', 'data': result})
        except asyncio.CancelledError:
            await queue.put({
                'type': 'error',
                'error': {'code': 'REQUEST_CANCELLED', 'message': 'Request cancelled.'},
            })
        except Exception as error:
            await queue.put({'type': 'error', 'error': await _stream_error(error)})

    async def events():
        for item in replay:
            await queue.put({'type': 'workflow', **item})
        subscriber = asyncio.create_task(run())
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    snapshot = main._progress_snapshot(request_id)
                    yield _sse_frame({
                        'type': 'heartbeat', 'request_id': request_id,
                        'sequence': snapshot.get('sequence', 0) if snapshot else 0,
                        'timestamp': main._utc_timestamp(),
                    })
                    continue
                yield _sse_frame(event)
                if event.get('type') in {'final', 'error'}:
                    break
        finally:
            with main._progress_lock:
                subscribers = main._stream_subscribers.get(request_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        main._stream_subscribers.pop(request_id, None)
            # Cancel only this subscriber; _chat_request is shared and shielded.
            if not subscriber.done():
                subscriber.cancel()
            await asyncio.gather(subscriber, return_exceptions=True)

    return StreamingResponse(
        events(), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.post('/api/chat/cancel/{request_id}')
async def cancel_chat_request(request_id: str):
    run = main._chat_runs.get(request_id)
    if run is None:
        raise HTTPException(404, 'Chat request not found')
    snapshot = main._progress_snapshot(request_id) or {}
    if not run.done() and snapshot.get('status') not in {'completed', 'failed', 'cancelled'}:
        main._progress_update(request_id, 'CANCELLED', 'Cancellation requested', 'cancelled')
        main._progress_finish(request_id, 'cancelled')
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
    elif not run.done():
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
    snapshot = main._progress_snapshot(request_id) or {}
    return {
        'ok': True,
        'request_id': request_id,
        'status': snapshot.get('status', 'cancelled'),
    }




@app.post('/api/chat')
async def chat(body: ChatRequest):
    return await main._chat_request(body)
@app.post('/api/index')
def index(body: IndexRequest):
    root = Path(body.path).resolve()
    registered = next((
        project for project in main.workspace_manager.projects()
        if Path(project['path']).resolve() == root
    ), None)
    if not registered:
        raise HTTPException(403, {
            'code': 'PROJECT_NOT_REGISTERED',
            'message': 'Load the project into the workspace before indexing it.',
        })
    if not root.is_dir():
        raise HTTPException(400, {
            'code': 'PROJECT_PATH_INVALID', 'message': 'Project directory not found.',
        })
    context = project_context(root, '')
    main.store.replace_project_files(str(root), context['rows'])
    return {
        'project': str(root), 'files_indexed': context['files_indexed'],
        'context_hash': context['context_hash'],
    }
