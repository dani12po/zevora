"""Chat CRUD, chat turns, workflow progress endpoint, and stream event mapper."""
from fastapi import HTTPException, Query
from agent.security.redaction import redact

import main
from fastapi.responses import JSONResponse
from main import app
from api.schemas import (
    ChatCreateRequest,
    ChatFeedbackRequest,
    ChatMessageRequest,
    ChatRenameRequest,
)

@app.get('/api/chats')
def chats(
    limit: int = Query(default=100, ge=1, le=500),
    query: str | None = Query(default=None, max_length=120),
):
    with main.workspace_manager.connection() as conn:
        if query:
            rows = conn.execute(
                'SELECT * FROM chats WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?',
                (f'%{query}%', limit)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?',
                (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
@app.post('/api/chats')
def create_chat(body:ChatCreateRequest):
    if body.project_id is not None and not main.workspace_manager.get(body.project_id):
        raise HTTPException(404, {
            'code': 'PROJECT_NOT_FOUND', 'message': 'Selected project was not found.',
        })
    return main.workspace_manager.create_chat(body.title,body.project_id)
@app.get('/api/chats/{chat_id}/export')
def export_chat(chat_id: str, format: str = Query(default='json', pattern='^(json|markdown|md)$')):
    """Export one conversation as JSON or a shareable Markdown transcript."""
    chat = main.workspace_manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, 'Chat not found')
    fmt = 'markdown' if format in ('markdown', 'md') else 'json'
    if fmt == 'json':
        return chat
    lines = [f"# {chat.get('title') or 'Untitled chat'}", '']
    created = chat.get('created_at')
    if created:
        lines += [f"_Created: {created}_", '']
    for message in chat.get('messages', []):
        role = (message.get('role') or 'unknown').capitalize()
        content = message.get('content') or ''
        lines += [f"## {role}", '', content, '']
    return JSONResponse(
        content={'markdown': '\n'.join(lines)},
        headers={'Content-Disposition': f'attachment; filename="{chat_id}.md"'},
    )
@app.get('/api/chats/{chat_id}')
def get_chat(chat_id:str):
    chat=main.workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    return chat
@app.delete('/api/chats')
def delete_all_chats():
    with main.workspace_manager.connection() as conn:
        count = conn.execute('SELECT COUNT(*) FROM chats').fetchone()[0]
        conn.execute('DELETE FROM message_feedback')
        conn.execute('DELETE FROM chat_messages')
        conn.execute('DELETE FROM chats')
    return {'ok':True,'deleted':count}
@app.delete('/api/chats/{chat_id}')
def delete_chat(chat_id:str):
    with main.workspace_manager.connection() as conn:
        row=conn.execute('SELECT id FROM chats WHERE id=?',(chat_id,)).fetchone()
        if not row: raise HTTPException(404,'Chat not found')
        conn.execute('DELETE FROM message_feedback WHERE chat_id=?',(chat_id,))
        conn.execute('DELETE FROM chat_messages WHERE chat_id=?',(chat_id,))
        conn.execute('DELETE FROM chats WHERE id=?',(chat_id,))
    return {'ok':True,'deleted':chat_id}
@app.patch('/api/chats/{chat_id}')
def rename_chat(chat_id:str,body:ChatRenameRequest):
    with main.workspace_manager.connection() as conn:
        row=conn.execute('SELECT id FROM chats WHERE id=?',(chat_id,)).fetchone()
        if not row: raise HTTPException(404,'Chat not found')
        conn.execute('UPDATE chats SET title=? WHERE id=?',(body.title[:120],chat_id))
    return {'ok':True,'id':chat_id,'title':body.title[:120]}
_CHAT_METADATA_KEYS = (
    'route','reason','provider','model','tools','quality_score','attachments',
    'agent_trace','agentic_log','fallback_trace','estimated_cost','context_hash','project_files',
    'project_discovery','context_status','flow','execution_ms','workflow',
)

def _chat_metadata(result):
    return {key:result.get(key) for key in _CHAT_METADATA_KEYS}

async def _complete_chat_turn(chat, content, body):
    project=main.workspace_manager.get(chat['project_id']) if chat['project_id'] else None
    result = await main.task(main.TaskRequest(
        prompt=content, project=project['path'] if project else None,
        mode=body.mode, chat_mode=getattr(body, 'chat_mode', 'auto') or 'auto',
        provider=body.provider, model=body.model,
        attachments=body.attachments, actions=body.actions, progress_id=body.progress_id,
    ))
    if body.progress_id:
        result['workflow'] = main._progress_snapshot(body.progress_id)
    return result

@app.post('/api/chats/{chat_id}/messages')
async def chat_message(chat_id:str,body:ChatMessageRequest):
    chat=main.workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    result=await _complete_chat_turn(chat, body.content, body)
    message_id=main.workspace_manager.add_exchange(chat_id,redact(body.content),result['response'],main._chat_metadata(result))
    return {**result,'message_id':message_id,'chat_id':chat_id,'feedback':None}

@app.post('/api/chats/{chat_id}/messages/{message_id}/regenerate')
async def regenerate_message(chat_id:str,message_id:int,body:ChatMessageRequest):
    chat=main.workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    content=main.workspace_manager.previous_user_message(chat_id,message_id)
    if content is None:
        raise HTTPException(404,'Original user message not found for this answer')
    result=await _complete_chat_turn(chat, content, body)
    main.workspace_manager.update_assistant_message(
        chat_id, message_id, result['response'], main._chat_metadata(result),
    )
    return {**result,'message_id':message_id,'chat_id':chat_id,'feedback':None,'regenerated':True}

@app.post('/api/chats/{chat_id}/messages/{message_id}/feedback')
def message_feedback(chat_id: str, message_id: int, body: ChatFeedbackRequest):
    chat = main.workspace_manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, 'Chat not found')
    try:
        rating = main.workspace_manager.set_feedback(chat_id, message_id, body.rating)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {'ok': True, 'chat_id': chat_id, 'message_id': message_id, 'rating': rating}
