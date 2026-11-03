"""Filesystem, terminal, tools, projects, and model listing endpoints."""
from pathlib import Path

from fastapi import HTTPException, Query
import main



from main import app
from api.schemas import (
    FileWriteRequest,
    MCPToolUpdateRequest,
    ProjectCreateRequest,
    ProjectLoadRequest,
    TerminalSessionRequest,
)

@app.get('/api/filesystem/tree')
def filesystem_tree(project_id: int):
    """Nested directory tree for the active project, skipping noise folders."""
    project, gateway = project_gateway(project_id)
    SKIP = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.pytest_cache',
            'dist', 'build', '.next', '.nuxt', 'target', '.mypy_cache', '.ruff_cache'}
    def _tree(rel: str, depth: int = 0):
        if depth > 6: return []
        try:
            result = gateway.execute('list_directory', {'path': rel})
            if not result.ok: return []
        except (ValueError, OSError): return []
        nodes = []
        for entry in result.output:
            name = entry['name']
            if name in SKIP or name.startswith('.'): continue
            child_rel = entry['path']
            is_dir = entry['type'] == 'directory'
            node = {'name': name, 'path': child_rel, 'type': 'dir' if is_dir else 'file'}
            if is_dir:
                node['children'] = _tree(child_rel, depth + 1)
            nodes.append(node)
        return nodes
    return {'project': project['path'], 'tree': _tree('')}
@app.get('/api/filesystem/file')
def filesystem_file(
    project_id: int = Query(gt=0),
    path: str = Query(min_length=1, max_length=4096),
):
    """Read a single project file for preview (max 200 KB)."""
    _, gateway = project_gateway(project_id)
    try:
        result = gateway.execute('read_file', {'path': path})
    except (OSError, ValueError) as error:
        raise HTTPException(400, str(error))
    if not result.ok: raise HTTPException(400, result.output)
    payload = result.output
    content = payload['content']
    return {
        'path': payload['path'], 'content': content,
        'offset': payload['offset'], 'bytes_read': payload['bytes_read'],
        'next_offset': payload['next_offset'],
        'truncated': payload['next_offset'] is not None,
    }

@app.post('/api/terminal/sessions')
def start_terminal_session(body: TerminalSessionRequest):
    project = main.workspace_manager.get(body.project_id)
    if not project:
        raise HTTPException(404, {'code': 'PROJECT_NOT_FOUND', 'message': 'Selected project was not found.'})
    try:
        result = main.terminal_sessions.start(
            Path(project['path']), body.command, approved=body.approved,
            timeout=body.timeout, cwd=body.cwd,
            preferences=main.workspace_manager.permissions(body.project_id),
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(400, {'code': 'TERMINAL_COMMAND_REJECTED', 'message': str(error)}) from error
    if not result.get('ok'):
        status = 403 if result.get('approval_required') else 400
        raise HTTPException(status, {
            'code': 'TERMINAL_APPROVAL_REQUIRED' if status == 403 else 'TERMINAL_COMMAND_REJECTED',
            'message': result.get('error', 'Terminal command was rejected.'),
            'risk': result.get('risk'),
            'details': result.get('details', {}),
        })
    return result

@app.get('/api/terminal/sessions/{session_id}')
def terminal_session_status(session_id: str, after: int = Query(default=0, ge=0)):
    result = main.terminal_sessions.get(session_id, after)
    if result is None:
        raise HTTPException(404, {'code': 'TERMINAL_SESSION_NOT_FOUND', 'message': 'Terminal session was not found.'})
    return result

@app.post('/api/terminal/sessions/{session_id}/kill')
def kill_terminal_session(session_id: str):
    result = main.terminal_sessions.kill(session_id)
    if result is None:
        raise HTTPException(404, {'code': 'TERMINAL_SESSION_NOT_FOUND', 'message': 'Terminal session was not found.'})
    return {'ok': True, **result}

@app.delete('/api/terminal/sessions/{session_id}')
def clear_terminal_session(session_id: str):
    if not main.terminal_sessions.clear(session_id):
        raise HTTPException(404, {'code': 'TERMINAL_SESSION_NOT_FOUND', 'message': 'Terminal session was not found.'})
    return {'ok': True, 'session_id': session_id}

@app.get('/api/models')
def models(provider: str | None = None): return main.model_registry.list(provider)
@app.post('/api/models/refresh')
async def refresh_models(provider: str | None = None): return await main.ProviderDiscovery(main.model_registry).refresh(provider)
@app.get('/api/route')
def route(prompt: str = Query(min_length=1, max_length=20_000)):
    return main.hybrid_router.decide(prompt, main.model_registry.list()).to_dict()
@app.get('/api/tools')
def tools(): return main.mcp_gateway.tools()
@app.put('/api/tools/{tool_name}')
def update_tool(tool_name: str, body: MCPToolUpdateRequest):
    try:
        return main.mcp_gateway.set_tool_enabled(tool_name, body.enabled)
    except ValueError as error:
        raise HTTPException(404, {
            'code': 'MCP_TOOL_NOT_FOUND', 'message': str(error),
        }) from error
@app.get('/api/routing/main.settings')
def routing_settings():
    return {
        'mode': main.settings.routing_mode,
        'cloud_fallback': main.settings.cloud_fallback,
        'cost_optimization': main.settings.cost_optimization,
        'max_repair_attempts': main.settings.max_repair_attempts,
    }
@app.post('/api/projects/create')
def create_project(body: ProjectCreateRequest):
    result=main.mcp_gateway.execute('create_project',{'name':body.name},approved=body.approved)
    if result.approval_required: raise HTTPException(403,result.output)
    if not result.ok: raise HTTPException(400,result.output)
    # Auto-register the new project folder into the workspace database.
    project = main.workspace_manager.load(result.output['project'])
    return {**result.output, 'id': project['id']}
@app.get('/api/projects')
def workspace_projects(): return main.workspace_manager.projects()
@app.post('/api/projects/load')
def load_workspace_project(body:ProjectLoadRequest):
    try: return main.workspace_manager.load(body.path)
    except (OSError, ValueError) as error:
        raise HTTPException(400, {
            'code': 'PROJECT_PATH_INVALID', 'message': str(error),
        }) from error
@app.post('/api/projects/pick-folder')
def pick_workspace_folder():
    """Local-only native fallback when the browser folder-picker API is unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
        path=filedialog.askdirectory(title='Select ZEVORA project folder',mustexist=True)
        root.destroy()
    except Exception as error:
        raise HTTPException(501,{'code':'PICKER_UNAVAILABLE','message':f'Native folder picker is unavailable: {type(error).__name__}'})
    if not path: return {'ok':True,'cancelled':True}
    project=main.workspace_manager.load(path)
    return {'ok':True,'cancelled':False,'project':project}
@app.get('/api/projects/{project_id}')
def workspace_project(project_id:int):
    project=main.workspace_manager.get(project_id)
    if not project: raise HTTPException(404,'Project not found')
    return project
def project_gateway(project_id:int):
    project=main.workspace_manager.get(project_id)
    if not project: raise HTTPException(404,'Project not found')
    return project,main.LocalMCPGateway(Path(project['path']))
@app.get('/api/projects/{project_id}/files')
def project_files(project_id:int):
    project,gateway=project_gateway(project_id)
    result=gateway.execute('list_directory',{'path':''})
    if not result.ok: raise HTTPException(400,result.output)
    return {'project':project['path'],'entries':result.output}
@app.get('/api/projects/{project_id}/files/read')
def project_file(
    project_id: int,
    path: str = Query(min_length=1, max_length=4096),
):
    _,gateway=project_gateway(project_id)
    try: result=gateway.execute('read_file',{'path':path})
    except (OSError,ValueError) as error: raise HTTPException(400,str(error))
    if not result.ok: raise HTTPException(400,result.output)
    return result.output
@app.put('/api/projects/{project_id}/files/write')
def write_project_file(project_id: int, body: FileWriteRequest):
    _, gateway = project_gateway(project_id)
    try:
        result = gateway.execute('write_file', {
            'path': body.path,
            'content': body.content,
        })
    except (OSError, ValueError) as error:
        raise HTTPException(400, {
            'code': 'FILE_WRITE_FAILED', 'message': str(error),
        }) from error
    if not result.ok:
        raise HTTPException(400, {
            'code': 'FILE_WRITE_FAILED',
            'message': str(result.output),
        })
    return {'ok': True, **result.output}
@app.post('/api/projects/{project_id}/audit')
def audit_workspace_project(project_id:int):
    try: return main.workspace_manager.audit(project_id)
    except ValueError as error: raise HTTPException(404,str(error))
