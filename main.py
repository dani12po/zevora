from pathlib import Path
import hmac
import json
import os
from contextlib import asynccontextmanager
from threading import Lock
from time import perf_counter
import asyncio
import uuid
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent.config import ROOT, reload_settings, settings
from agent.memory.store import Store
from agent.models.manager import LocalIntelligenceManager
from agent.models.registry import ModelRegistry
from agent.providers.discovery import ProviderDiscovery
from agent.providers.local_provider import local_runtime_status
from agent.providers.registry import get_provider
from agent.routing.hybrid_router import AdaptiveHybridRouter, Route
from agent.routing.model_selector import ModelSelector
from agent.routing.quality_gate import validate
from agent.routing.router import ModelRouter
from agent.routing.task_classifier import TaskClassifier
from agent.security.redaction import redact
from agent.core.attachments import attachment_context, process_attachment
from agent.core.execution import AgentAction, ProjectAgentExecutor
from agent.core.planning import parse_action_plan, planning_system_prompt, public_action
from agent.core.project_index import format_project_context, index_project, project_context
from agent.core.workspace import WorkspaceManager
from agent.intelligence.engine import LocalIntelligenceEngine
from agent.skills.openclaw import OpenClawSkillSource
from agent.storage.cleanup import CleanupManager
from agent.storage.maintenance import MaintenanceScheduler
from agent.storage.storage_manager import StorageManager
from agent.tools.mcp_gateway import LocalMCPGateway

# ── Singletons ────────────────────────────────────────────────────────────────
store         = Store(settings.database_file)
router        = ModelRouter()
local_manager = LocalIntelligenceManager()
intelligence_engine = LocalIntelligenceEngine(settings.database_file)
basic_skills  = OpenClawSkillSource()
storage_manager   = StorageManager(ROOT)
model_registry    = ModelRegistry(ROOT / 'data' / 'database' / 'model_registry.db')
mcp_gateway       = LocalMCPGateway()
hybrid_router     = AdaptiveHybridRouter()
workspace_manager = WorkspaceManager(ROOT / 'data' / 'database' / 'workspace.db')
_PROVIDER_CONFIG_LOCK = Lock()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)

# ── App + lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app):
    # One bounded startup refresh; requests never trigger repeated model discovery.
    await ProviderDiscovery(model_registry).refresh()
    yield

app = FastAPI(
    title='ZEVORA — Zero-External Vendor Oriented Reasoning Agent',
    version='0.1.0',
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:7432', 'http://localhost:7432',
                   'http://127.0.0.1:3000', 'http://localhost:3000'],
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
    allow_headers=['Content-Type'],
)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

@app.exception_handler(HTTPException)
async def api_http_error(_: Request, error: HTTPException):
    """Return machine-readable failures without affecting the gateway process."""
    detail = error.detail
    message = detail.get('message') if isinstance(detail, dict) else str(detail)
    code = (detail.get('code') if isinstance(detail, dict) else None) or (
        'AI_EXECUTION_ERROR' if error.status_code >= 500 else 'REQUEST_ERROR'
    )
    error_payload = {'code': code, 'message': message}
    if isinstance(detail, dict):
        error_payload.update({
            key: value for key, value in detail.items()
            if key not in {'code', 'message'}
        })
    return JSONResponse(
        status_code=error.status_code,
        content={'ok': False, 'error': error_payload},
    )

@app.exception_handler(Exception)
async def api_unexpected_error(_: Request, error: Exception):
    return JSONResponse(status_code=500, content={
        'ok': False,
        'error': {'code': 'INTERNAL_ERROR',
                  'message': f'Unexpected gateway error: {type(error).__name__}'},
    })

class AttachmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1)

class AgentActionRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)
    approved: bool = False
    purpose: str = Field(default='', max_length=500)

class TaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    project: str | None = None
    system: str = 'You are a safe, concise personal AI agent.'
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    project_id: int
class MCPToolUpdateRequest(BaseModel):
    enabled: bool
class IndexRequest(BaseModel): path: str
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    approved: bool = False
class ProjectLoadRequest(BaseModel): path: str
class SettingsUpdateRequest(BaseModel):
    routing_mode: str | None = None
    cloud_fallback: bool | None = None
    cost_optimization: bool | None = None
class ChatCreateRequest(BaseModel): title: str = 'New chat'; project_id: int | None = None
class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1,max_length=20000)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
class ChatRequest(BaseModel):
    message: str = Field(min_length=1,max_length=20000)
    conversation_id: str | None = None
    project_id: int | None = None
    project_context: str | None = None
    mode: str = 'auto'
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
class ChatRenameRequest(BaseModel): title: str = Field(min_length=1, max_length=120)
class ProviderConfigRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    routing_priority: int | None = Field(default=None, ge=0, le=100)
    supports_vision: bool | None = None

@app.get('/')
def dashboard():
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / 'static' / 'index.html')
@app.get('/health')
def gateway_health(): return {'ok':True,'status':'ok','service':'zevora','version':'0.1.0','gateway':'running'}
def _schedule_shutdown():
    asyncio.get_running_loop().call_later(
        .2, lambda: os.kill(os.getpid(), __import__('signal').SIGINT)
    )
@app.post('/shutdown')
async def shutdown_gateway(x_zevora_shutdown_token: str | None = Header(default=None)):
    expected = os.environ.get('ZEVORA_SHUTDOWN_TOKEN', '')
    if not expected or not x_zevora_shutdown_token or not hmac.compare_digest(
        x_zevora_shutdown_token, expected
    ):
        raise HTTPException(403, {
            'code': 'SHUTDOWN_FORBIDDEN',
            'message': 'A valid gateway controller token is required.',
        })
    _schedule_shutdown()
    return {'status':'stopping'}
@app.get('/api/health')
async def health():
    resource = local_manager.resource_state()
    configured = [p['provider'] for p in ProviderDiscovery(model_registry).configured_list()
                  if p['configured'] and p['enabled']]
    return {
        'ok': True, 'status': 'ok', 'service': 'zevora', 'version': '0.1.0',
        'gateway': 'running', 'ready': True,
        'providers_configured': configured,
        'local_resource': resource,
        'local_model': local_runtime_status(),
        'semantic_cache_enabled': settings.semantic_cache_enabled,
        'basic_skills': {
            'enabled': settings.basic_skills_enabled,
            'source_available': basic_skills.directory.is_dir(),
            'allowed': sorted(settings.allowed_basic_skills),
        },
    }
@app.get('/api/stats')
def stats(): return {'today':store.usage(), 'resources':local_manager.resource_state()}
@app.get('/api/memory')
def memory(): return {'categories':store.memory_categories()}
@app.get('/api/intelligence')
def intelligence_stats(): return intelligence_engine.stats(settings.database_file).__dict__
@app.get('/api/settings')
def ui_settings():
    return {
        'gateway_url': 'http://127.0.0.1:7432',
        'routing_mode': settings.routing_mode,
        'cloud_fallback': settings.cloud_fallback,
        'cost_optimization': settings.cost_optimization,
    }
@app.post('/api/settings')
def update_ui_settings(body:SettingsUpdateRequest):
    if body.routing_mode and body.routing_mode.upper() not in {'AUTO','LOCAL_ONLY','CLOUD_ONLY'}:
        raise HTTPException(400,'routing_mode must be AUTO, LOCAL_ONLY, or CLOUD_ONLY')
    config_file=ROOT/'config'/'ui_settings.json'; config_file.parent.mkdir(parents=True,exist_ok=True)
    try: saved=json.loads(config_file.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): saved={}
    if body.routing_mode is not None: saved['routing_mode']=body.routing_mode.upper()
    if body.cloud_fallback is not None: saved['cloud_fallback']=body.cloud_fallback
    if body.cost_optimization is not None: saved['cost_optimization']=body.cost_optimization
    config_file.write_text(json.dumps(saved,indent=2),encoding='utf-8')
    reload_settings()
    return {'ok':True,**saved}
@app.get('/api/storage')
def storage(): return storage_manager.report()
@app.post('/api/maintenance/cleanup-plan')
def cleanup_plan(): return CleanupManager(ROOT).run(dry_run=True)
@app.post('/api/maintenance/intelligence')
def intelligence_cleanup(execute: bool = False):
    store_result = store.retention(dry_run=not execute)
    knowledge_result = {'knowledge_removed': 0}
    if execute:
        knowledge_result = intelligence_engine.prune()
    else:
        with intelligence_engine.connection() as conn:
            count = conn.execute(
                """SELECT COUNT(*) count FROM knowledge
                   WHERE datetime(COALESCE(last_accessed, updated_at)) < datetime('now', '-180 days')
                     AND COALESCE(hit_count, 0)=0
                     AND COALESCE(importance, 0.5) < 0.75"""
            ).fetchone()['count']
        knowledge_result = {'knowledge_candidates': count}
    return {'ok': True, 'executed': execute, **store_result, **knowledge_result}
@app.get('/api/maintenance/plan')
def maintenance_plan(): return MaintenanceScheduler(ROOT).plan()
@app.get('/api/providers')
async def providers():
    discovered = await ProviderDiscovery(model_registry).providers()
    local = local_runtime_status()
    for item in discovered:
        if item.get('provider') == 'local':
            item['runtime_status'] = local
    return discovered
@app.get('/api/providers/config')
def providers_config():
    """Return provider config with API keys masked — never exposes raw secrets."""
    env_file = ROOT / '.env'
    env_vals: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                env_vals[k.strip().upper()] = v.strip()
    providers_cfg_file = ROOT / 'config' / 'providers.json'
    try: cfg = json.loads(providers_cfg_file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError): cfg = {'providers': {}}
    provider_cfg = cfg.get('providers', {})
    KEY_MAP = {
        'openai': 'OPENAI_API_KEY', 'xai': 'XAI_API_KEY', 'nvidia': 'NVIDIA_API_KEY',
        'deepseek': 'DEEPSEEK_API_KEY', 'gemini': 'GEMINI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY',
    }
    URL_MAP = {
        'openai': 'OPENAI_BASE_URL', 'xai': 'XAI_BASE_URL', 'nvidia': 'NVIDIA_BASE_URL',
        'deepseek': 'DEEPSEEK_BASE_URL', 'anthropic': 'ANTHROPIC_BASE_URL',
    }
    DEFAULT_URLS = {
        'openai': 'https://api.openai.com/v1', 'xai': 'https://api.x.ai/v1',
        'nvidia': 'https://integrate.api.nvidia.com/v1', 'deepseek': 'https://api.deepseek.com/v1',
        'gemini': '', 'anthropic': 'https://api.anthropic.com',
    }
    customs = cfg.get('custom_providers', [])
    for c in customs:
        name = c.get('name', '').lower()
        if not name: continue
        KEY_MAP[name] = c.get('api_key_env', '')
        URL_MAP[name] = ''
        DEFAULT_URLS[name] = c.get('base_url', '')

    result = []
    all_providers = ['local', 'openai', 'xai', 'nvidia', 'deepseek', 'gemini', 'anthropic'] + [c.get('name', '').lower() for c in customs if c.get('name')]

    for name in all_providers:
        raw_key = env_vals.get(KEY_MAP.get(name, ''), '')
        masked = ('••••••••' + raw_key[-4:]) if raw_key and len(raw_key) >= 4 else ''
        raw_url = env_vals.get(URL_MAP.get(name, ''), DEFAULT_URLS.get(name, ''))
        p = provider_cfg.get(name, {})
        runtime = local_runtime_status() if name == 'local' else None
        result.append({
            'provider': name, 'key_masked': masked, 'key_set': bool(raw_key),
            'base_url': raw_url or DEFAULT_URLS.get(name, ''),
            'default_model': p.get('default_model') or {
                'openai': env_vals.get('OPENAI_MODEL', 'gpt-4o-mini'),
                'xai': env_vals.get('XAI_MODEL', 'grok-3-mini'),
                'nvidia': env_vals.get('NVIDIA_MODEL', 'meta/llama-3.1-8b-instruct'),
                'deepseek': env_vals.get('DEEPSEEK_MODEL', 'deepseek-chat'),
                'gemini': env_vals.get('GEMINI_MODEL', 'gemini-2.0-flash'),
                'anthropic': env_vals.get('ANTHROPIC_MODEL', 'claude-3-5-haiku-latest'),
            }.get(name, ''),
            'enabled': p.get('enabled', True), 'routing_priority': p.get('routing_priority', 50),
            'runtime_status': runtime,
            'supports_vision': bool(p.get('supports_vision', next((
                c.get('supports_vision', False) for c in customs
                if c.get('name', '').lower() == name
            ), False))),
        })
    return result


@app.post('/api/providers/config')
async def update_provider_config(body: ProviderConfigRequest):
    """Persist provider settings without exposing API keys."""
    from urllib.parse import urlparse

    provider_name = body.provider.strip().lower()
    if body.api_key is not None and any(char in body.api_key for char in '\r\n'):
        raise HTTPException(400, 'api_key must not contain newlines')
    if body.base_url is not None:
        parsed_url = urlparse(body.base_url.strip())
        if parsed_url.scheme not in {'http', 'https'} or not parsed_url.netloc:
            raise HTTPException(400, 'base_url must be an absolute HTTP(S) URL')
    model = body.default_model.strip() if body.default_model is not None else None
    if model == '':
        raise HTTPException(400, 'default_model cannot be empty')

    providers_cfg_file = ROOT / 'config' / 'providers.json'
    env_file = ROOT / '.env'
    with _PROVIDER_CONFIG_LOCK:
        try:
            cfg = json.loads(providers_cfg_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            cfg = {'providers': {}, 'model_overrides': {}}
        customs = cfg.get('custom_providers', [])
        allowed = {'openai', 'xai', 'nvidia', 'deepseek', 'gemini', 'anthropic'}
        allowed.update(c.get('name', '').lower() for c in customs if c.get('name'))
        if provider_name not in allowed:
            raise HTTPException(400, f'Unknown provider: {provider_name}')

        key_map = {
            'openai': 'OPENAI_API_KEY', 'xai': 'XAI_API_KEY',
            'nvidia': 'NVIDIA_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY',
            'gemini': 'GEMINI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY',
        }
        url_map = {
            'openai': 'OPENAI_BASE_URL', 'xai': 'XAI_BASE_URL',
            'nvidia': 'NVIDIA_BASE_URL', 'deepseek': 'DEEPSEEK_BASE_URL',
            'anthropic': 'ANTHROPIC_BASE_URL',
        }
        for custom in customs:
            name = custom.get('name', '').lower()
            if name:
                key_map[name] = custom.get('api_key_env', '')

        lines = env_file.read_text(encoding='utf-8').splitlines() if env_file.exists() else []
        env_map = {}
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key, _, _ = stripped.partition('=')
                env_map[key.strip().upper()] = index

        def set_env(key: str, value: str) -> None:
            if not key:
                return
            if key in env_map:
                lines[env_map[key]] = f'{key}={value}'
            else:
                env_map[key] = len(lines)
                lines.append(f'{key}={value}')

        if body.api_key is not None:
            set_env(key_map.get(provider_name, ''), body.api_key)
        if body.base_url is not None and provider_name in url_map:
            set_env(url_map[provider_name], body.base_url.strip())

        provider_cfg = cfg.setdefault('providers', {}).setdefault(provider_name, {})
        if model is not None:
            provider_cfg['default_model'] = model
        if body.enabled is not None:
            provider_cfg['enabled'] = body.enabled
        if body.routing_priority is not None:
            provider_cfg['routing_priority'] = body.routing_priority
        if body.supports_vision is not None:
            provider_cfg['supports_vision'] = body.supports_vision

        _atomic_write_text(env_file, '\n'.join(lines) + '\n')
        _atomic_write_text(
            providers_cfg_file,
            json.dumps(cfg, indent=2, ensure_ascii=True) + '\n',
        )

    reload_settings()
    refresh = await ProviderDiscovery(model_registry).refresh(provider_name)
    return {
        'ok': True,
        'provider': provider_name,
        'key_updated': body.api_key is not None,
        'status': refresh[0]['health_status'] if refresh else (
            'disabled' if body.enabled is False else 'unconfigured'
        ),
        'models_discovered': refresh[0]['models_discovered'] if refresh else 0,
    }

@app.get('/api/usage/history')
def usage_history(provider: str | None = None, days: int = 30):
    """Per-day, per-provider breakdown from usage_events table."""
    with store.connection() as conn:
        sql = '''SELECT date(created_at) day, provider, model,
                    COUNT(*) requests, COALESCE(SUM(cache_hit),0) cache_hits,
                    COALESCE(SUM(input_tokens),0) input_tokens,
                    COALESCE(SUM(output_tokens),0) output_tokens,
                    COALESCE(SUM(estimated_cost),0) estimated_cost
                 FROM usage_events
                 WHERE date(created_at) >= date('now', ?)'''
        args: list = [f'-{max(1,min(days,365))} days']
        if provider:
            sql += ' AND provider=?'; args.append(provider)
        sql += ' GROUP BY day, provider, model ORDER BY day DESC, provider'
        rows = conn.execute(sql, args).fetchall()
    return {'rows': [dict(r) for r in rows], 'days': days, 'provider_filter': provider}
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
def filesystem_file(project_id: int, path: str):
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

@app.get('/api/models')
def models(provider: str | None = None): return model_registry.list(provider)
@app.post('/api/models/refresh')
async def refresh_models(provider: str | None = None): return await ProviderDiscovery(model_registry).refresh(provider)
@app.get('/api/route')
def route(prompt: str):
    return hybrid_router.decide(prompt, model_registry.list()).to_dict()
@app.get('/api/tools')
def tools(): return mcp_gateway.tools()
@app.put('/api/tools/{tool_name}')
def update_tool(tool_name: str, body: MCPToolUpdateRequest):
    try:
        return mcp_gateway.set_tool_enabled(tool_name, body.enabled)
    except ValueError as error:
        raise HTTPException(404, {
            'code': 'MCP_TOOL_NOT_FOUND', 'message': str(error),
        }) from error
@app.get('/api/routing/settings')
def routing_settings():
    return {
        'mode': settings.routing_mode,
        'cloud_fallback': settings.cloud_fallback,
        'cost_optimization': settings.cost_optimization,
        'max_repair_attempts': settings.max_repair_attempts,
    }
@app.post('/api/projects/create')
def create_project(body: ProjectCreateRequest):
    result=mcp_gateway.execute('create_project',{'name':body.name},approved=body.approved)
    if result.approval_required: raise HTTPException(403,result.output)
    if not result.ok: raise HTTPException(400,result.output)
    # Auto-register the new project folder into the workspace database.
    project = workspace_manager.load(result.output['project'])
    return {**result.output, 'id': project['id']}
@app.get('/api/projects')
def workspace_projects(): return workspace_manager.projects()
@app.post('/api/projects/load')
def load_workspace_project(body:ProjectLoadRequest):
    try: return workspace_manager.load(body.path)
    except ValueError as error: raise HTTPException(400,str(error))
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
    project=workspace_manager.load(path)
    return {'ok':True,'cancelled':False,'project':project}
@app.get('/api/projects/{project_id}')
def workspace_project(project_id:int):
    project=workspace_manager.get(project_id)
    if not project: raise HTTPException(404,'Project not found')
    return project
def project_gateway(project_id:int):
    project=workspace_manager.get(project_id)
    if not project: raise HTTPException(404,'Project not found')
    return project,LocalMCPGateway(Path(project['path']))
@app.get('/api/projects/{project_id}/files')
def project_files(project_id:int):
    project,gateway=project_gateway(project_id)
    result=gateway.execute('list_directory',{'path':''})
    if not result.ok: raise HTTPException(400,result.output)
    return {'project':project['path'],'entries':result.output}
@app.get('/api/projects/{project_id}/files/read')
def project_file(project_id:int,path:str):
    _,gateway=project_gateway(project_id)
    try: result=gateway.execute('read_file',{'path':path})
    except (OSError,ValueError) as error: raise HTTPException(400,str(error))
    if not result.ok: raise HTTPException(400,result.output)
    return result.output
@app.post('/api/projects/{project_id}/audit')
def audit_workspace_project(project_id:int):
    try: return workspace_manager.audit(project_id)
    except ValueError as error: raise HTTPException(404,str(error))
@app.get('/api/chats')
def chats(limit: int = 100, query: str | None = None):
    with workspace_manager.connection() as conn:
        if query:
            rows = conn.execute(
                'SELECT * FROM chats WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?',
                (f'%{query}%', min(limit, 500))
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?',
                (min(limit, 500),)
            ).fetchall()
    return [dict(r) for r in rows]
@app.post('/api/chats')
def create_chat(body:ChatCreateRequest): return workspace_manager.create_chat(body.title,body.project_id)
@app.get('/api/chats/{chat_id}')
def get_chat(chat_id:str):
    chat=workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    return chat
@app.delete('/api/chats/{chat_id}')
def delete_chat(chat_id:str):
    with workspace_manager.connection() as conn:
        row=conn.execute('SELECT id FROM chats WHERE id=?',(chat_id,)).fetchone()
        if not row: raise HTTPException(404,'Chat not found')
        conn.execute('DELETE FROM chat_messages WHERE chat_id=?',(chat_id,))
        conn.execute('DELETE FROM chats WHERE id=?',(chat_id,))
    return {'ok':True,'deleted':chat_id}
@app.patch('/api/chats/{chat_id}')
def rename_chat(chat_id:str,body:ChatRenameRequest):
    with workspace_manager.connection() as conn:
        row=conn.execute('SELECT id FROM chats WHERE id=?',(chat_id,)).fetchone()
        if not row: raise HTTPException(404,'Chat not found')
        conn.execute('UPDATE chats SET title=? WHERE id=?',(body.title[:120],chat_id))
    return {'ok':True,'id':chat_id,'title':body.title[:120]}
@app.post('/api/chats/{chat_id}/messages')
async def chat_message(chat_id:str,body:ChatMessageRequest):
    chat=workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    project=workspace_manager.get(chat['project_id']) if chat['project_id'] else None
    result=await task(TaskRequest(
        prompt=body.content, project=project['path'] if project else None,
        attachments=body.attachments, actions=body.actions,
    ))
    metadata={key:result.get(key) for key in (
        'route','reason','provider','model','tools','quality_score','attachments',
        'agent_trace','fallback_trace','estimated_cost','context_hash','project_files',
        'project_discovery','context_status','flow','execution_ms',
    )}
    message_id=workspace_manager.add_exchange(chat_id,redact(body.content),result['response'],metadata)
    return {**result,'message_id':message_id}
@app.post('/api/chat')
async def chat(body:ChatRequest):
    request_id='zv-'+uuid.uuid4().hex[:12]
    chat_id=body.conversation_id
    if not chat_id: chat_id=workspace_manager.create_chat(body.message[:80],body.project_id)['id']
    existing=workspace_manager.get_chat(chat_id)
    if not existing: raise HTTPException(404,'Conversation not found')
    if body.project_id is not None and existing['project_id'] != body.project_id:
        project = workspace_manager.get(body.project_id)
        if not project:
            raise HTTPException(404, 'Project not found')
        with workspace_manager.connection() as conn:
            conn.execute('UPDATE chats SET project_id=? WHERE id=?', (body.project_id, chat_id))
        existing = workspace_manager.get_chat(chat_id)
    if existing['title']=='New chat': workspace_manager.set_title(chat_id,body.message[:80])
    result=await chat_message(
        chat_id, ChatMessageRequest(
            content=body.message, attachments=body.attachments, actions=body.actions,
        )
    )
    return {'ok':True,**result,'conversation_id':chat_id,'request_id':request_id}
@app.post('/api/index')
def index(body: IndexRequest):
    root = Path(body.path).resolve()
    if not root.is_dir(): raise HTTPException(400, 'Project directory not found')
    context = project_context(root, '')
    store.replace_project_files(str(root), context['rows'])
    return {
        'project': str(root), 'files_indexed': context['files_indexed'],
        'context_hash': context['context_hash'],
    }


def _cloud_candidates(prompt: str, available_models: list[dict]) -> list:
    """Build the hybrid provider/model fallback sequence.

    The legacy name is retained for planner and extension compatibility.
    """
    performance = store.routing_performance()
    if hasattr(hybrid_router, 'candidates'):
        candidates = hybrid_router.candidates(
            prompt, available_models, performance=performance
        )
        return candidates if settings.cloud_fallback else candidates[:1]

    primary = hybrid_router.decide(
        prompt, available_models, performance=performance
    )
    if primary.route not in {Route.LOCAL, Route.CLOUD}:
        return []
    candidates = [primary]
    if settings.cloud_fallback:
        fallback = hybrid_router.decide(
            prompt, available_models, exclude_providers={primary.provider},
            performance=performance,
        )
        if fallback.route in {Route.LOCAL, Route.CLOUD}:
            candidates.append(fallback)
    return candidates


async def _provider_completion(candidate, prompt: str, system: str,
                               images: list[dict] | None = None):
    provider = get_provider(candidate.provider)
    if images:
        return await provider.complete_multimodal(
            prompt, images, system, candidate.model_id or ''
        )
    if candidate.model_id and hasattr(provider, 'complete_for_model'):
        return await provider.complete_for_model(prompt, system, candidate.model_id)
    return await provider.complete(prompt, system)


def _attempt_record(candidate, status: str, error: Exception | None = None) -> dict:
    record = {
        'source': 'local_model' if candidate.route is Route.LOCAL else 'cloud_provider',
        'route': candidate.route.value, 'provider': candidate.provider,
        'model': candidate.model_id or '', 'status': status,
    }
    if error is not None:
        record['error'] = type(error).__name__
    return record


async def _cloud_completion(prompt: str, system: str, requested_format: str = '',
                            response_validator=None) -> dict:
    """Run hybrid completion; legacy name retained for caller compatibility."""
    available_models = model_registry.list()
    candidates = _cloud_candidates(prompt, available_models)
    if not candidates:
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': 'No configured local or cloud model is available for reasoning.',
            'fallback_trace': [],
        })

    fallback_trace: list[dict] = []
    for candidate in candidates:
        started = perf_counter()
        try:
            response, usage = await _provider_completion(candidate, prompt, system)
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
            store.add_routing_experience(
                candidate.route.value, candidate.provider, model,
                ','.join(candidate.task_type), True, checked['quality_score'], latency,
                candidate.tools,
            )
            with store.connection() as conn:
                conn.execute(
                    "INSERT INTO usage_events(provider,model,task_type,input_tokens,output_tokens,estimated_cost,cache_hit,created_at) VALUES(?,?,?,?,?,?,?,datetime('now'))",
                    (candidate.provider, model, 'planning', input_tokens,
                     output_tokens, estimated_cost, 0),
                )
            fallback_trace.append(_attempt_record(candidate, 'success'))
            return {
                'response': response, 'usage': usage, 'decision': candidate,
                'provider': candidate.provider, 'model': model,
                'estimated_cost': estimated_cost, 'fallback_trace': fallback_trace,
            }
        except Exception as error:
            latency = int((perf_counter() - started) * 1000)
            store.add_routing_experience(
                candidate.route.value, candidate.provider, candidate.model_id or '',
                ','.join(candidate.task_type), False, 0.0, latency, candidate.tools,
            )
            fallback_trace.append(_attempt_record(candidate, 'failed', error))

    raise HTTPException(503, {
        'code': 'AI_EXECUTION_ERROR',
        'message': 'All capable local and cloud model alternatives failed.',
        'fallback_trace': fallback_trace,
    })


@app.post('/api/agent/plan')
async def plan_agent_actions(body: PlanRequest):
    project = workspace_manager.get(body.project_id)
    if not project:
        raise HTTPException(404, {
            'code': 'PROJECT_NOT_FOUND', 'message': 'Selected project was not found.'
        })
    root = Path(project['path']).resolve()
    context = project_context(root, body.prompt)
    store.replace_project_files(str(root), context['rows'])
    base_prompt = (
        f'User request:\n{redact(body.prompt)}\n\n'
        f'{format_project_context(context)}'
    )
    inspection_tools = {
        'list_directory', 'read_file', 'search_files', 'file_exists', 'get_file_info',
    }
    max_iterations = max(1, min(12, settings.max_agent_iterations))
    max_tool_calls = max(1, min(30, settings.max_agent_tool_calls))
    timeout_seconds = max(1, min(300, settings.agent_timeout_seconds))
    started = perf_counter()
    gateway = LocalMCPGateway(root)
    enabled_tools = gateway.enabled_tools()
    pending_actions: list[AgentAction] = []
    inspection_count = 0
    observations: list[dict] = []
    seen_plans: set[str] = set()
    completion = None

    for iteration in range(max_iterations):
        if perf_counter() - started >= timeout_seconds:
            raise HTTPException(409, {
                'code': 'AGENT_LOOP_LIMIT',
                'message': 'Planning timed out before a stable action plan was produced.',
                'iteration': iteration, 'tool_calls': inspection_count,
                'last_tool_result': observations[-1] if observations else None,
                'intervention_required': True,
            })
        observation_context = ''
        if observations:
            observation_context = (
                '\n\nAuthoritative tool observations from this planning run:\n'
                + json.dumps(observations, ensure_ascii=True)[-20_000:]
                + '\nReturn the next necessary actions only. Do not repeat completed inspections.'
            )
        completion = await _cloud_completion(
            base_prompt + observation_context,
            planning_system_prompt(
                max_tool_calls - inspection_count, enabled_tools
            ), 'json',
            lambda response: parse_action_plan(
                response, max_tool_calls - inspection_count, enabled_tools
            ),
        )
        actions = parse_action_plan(
            completion['response'], max_tool_calls - inspection_count, enabled_tools
        )
        signature = json.dumps(
            [public_action(action) for action in actions], sort_keys=True
        )
        if signature in seen_plans:
            raise HTTPException(409, {
                'code': 'AGENT_LOOP_LIMIT',
                'message': 'The provider repeated an already completed action plan.',
                'iteration': iteration + 1, 'tool_calls': inspection_count,
                'last_tool_result': observations[-1] if observations else None,
                'intervention_required': True,
            })
        seen_plans.add(signature)

        if not actions:
            break
        inspections = [action for action in actions if action.tool in inspection_tools]
        deferred = [action for action in actions if action.tool not in inspection_tools]
        if deferred:
            pending_actions.extend(actions)
            break
        for action in inspections:
            if inspection_count >= max_tool_calls:
                raise HTTPException(409, {
                    'code': 'AGENT_LOOP_LIMIT',
                    'message': 'Planning reached the maximum number of tool calls.',
                    'iteration': iteration + 1, 'tool_calls': inspection_count,
                    'last_tool_result': observations[-1] if observations else None,
                    'intervention_required': True,
                })
            result = gateway.execute(action.tool, action.arguments, approved=False)
            inspection_count += 1
            observations.append({
                'tool': action.tool, 'arguments': action.arguments,
                'ok': result.ok, 'output': result.output,
            })
    else:
        raise HTTPException(409, {
            'code': 'AGENT_LOOP_LIMIT',
            'message': 'Planning reached the maximum number of reasoning iterations.',
            'iteration': max_iterations, 'tool_calls': inspection_count,
            'last_tool_result': observations[-1] if observations else None,
            'intervention_required': True,
        })

    return {
        'ok': True,
        'needs_tools': bool(pending_actions),
        'actions': [public_action(action) for action in pending_actions],
        'provider': completion['provider'] if completion else None,
        'model': completion['model'] if completion else None,
        'estimated_cost': completion['estimated_cost'] if completion else 0.0,
        'iterations': len(seen_plans),
        'tool_calls': len(pending_actions),
        'inspection_tool_calls': inspection_count,
        'project_files': [item['path'] for item in context['files']],
    }


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


@app.post('/api/task')
async def task(body: TaskRequest):
    started = perf_counter()
    prompt = redact(body.prompt)
    try:
        processed_attachments = [
            process_attachment(item.name, item.media_type, item.data_base64)
            for item in body.attachments
        ]
    except ValueError as error:
        raise HTTPException(400, {'code': 'INVALID_ATTACHMENT', 'message': str(error)})
    attachment_metadata = [item.metadata() for item in processed_attachments]
    images = [
        {'media_type': item.media_type, 'data_base64': item.image_base64}
        for item in processed_attachments if item.kind == 'image'
    ]
    attachment_reference = attachment_context(processed_attachments)
    attachment_hash = ''.join(item.content_hash for item in processed_attachments)
    project_hash = ''
    project_reference = ''
    project_files_used: list[str] = []
    project_discovery = None
    agent_trace = None
    root = None
    if not body.project and (body.actions or _requires_workspace_agent(prompt)):
        raise HTTPException(400, {
            'code': 'PROJECT_REQUIRED',
            'message': (
                'Select or open the target project folder before asking ZEVORA to '
                'read, create, edit, or run files. Tool access is scoped to that folder.'
            ),
        })
    if body.project:
        root = Path(body.project).resolve()
        if not root.is_dir():
            raise HTTPException(400, 'Project directory not found')

        # The browser is only a client.  Keep planning on the gateway so every
        # client gets the same agent behavior, including API/CLI callers.
        if not body.actions and _requires_workspace_agent(prompt):
            project = workspace_manager.load(root)
            plan = await plan_agent_actions(PlanRequest(
                prompt=body.prompt, project_id=project['id'],
            ))
            body.actions = [AgentActionRequest(
                tool=item['tool'], arguments=item.get('arguments', {}),
                purpose=item.get('purpose', ''), approved=False,
            ) for item in plan.get('actions', [])]

        context = project_context(root, prompt)
        store.replace_project_files(str(root), context['rows'])
        project_hash = context['context_hash']
        project_reference = format_project_context(context)
        project_files_used = [item['path'] for item in context['files']]
        project_discovery = context['discovery']
        if body.actions:
            project = workspace_manager.load(root)
            executor = ProjectAgentExecutor(root, preferences=project.get('permissions'))
            agent_trace = executor.execute(
                prompt,
                [AgentAction(
                    **{
                        **action.model_dump(),
                        # Approval must be explicit for each action. The client is
                        # never allowed to turn an unapproved action into an approved one.
                        'approved': action.approved,
                    },
                ) for action in body.actions],
                project_files_used,
            )
            if agent_trace.pending_approvals:
                raise HTTPException(403, {
                    'code': 'APPROVAL_REQUIRED',
                    'message': 'Explicit approval is required before executing requested actions.',
                    'pending_approvals': agent_trace.pending_approvals,
                    'agent_trace': agent_trace.to_dict(),
                })
            failed_actions = [
                item for item in agent_trace.observations if not item.get('ok')
            ]
            if failed_actions:
                raise HTTPException(409, {
                    'code': 'ACTION_FAILED',
                    'message': 'One or more workspace actions failed. No success was reported.',
                    'failed_actions': failed_actions,
                    'agent_trace': agent_trace.to_dict(),
                })
            # Approved writes may have changed project state; rebuild authoritative context.
            context = project_context(root, prompt)
            store.replace_project_files(str(root), context['rows'])
            project_hash = context['context_hash']
            project_reference = format_project_context(context)
            project_files_used = [item['path'] for item in context['files']]
            project_discovery = context['discovery']

            mutation_tools = {
                'create_file', 'write_file', 'edit_file', 'delete_file',
                'move_file', 'copy_file',
            }
            if any(action.tool in mutation_tools for action in body.actions):
                agent_trace.stage('FINAL_RESPONSE', detail={
                    'source': 'authoritative_tool_results',
                })
                elapsed = int((perf_counter() - started) * 1000)
                task_type = router.classify(prompt)
                response = _action_receipt(root, agent_trace)
                intelligence_engine.extract_knowledge(
                    prompt, response, task_type.value, 'local', 'mcp-tools', body.project
                )
                store.add_memory('conversation', prompt, body.project, task_type.value)
                return {
                    'response': response, 'provider': 'local', 'model': 'mcp-tools',
                    'task_type': task_type.value, 'skills_used': [], 'route': 'LOCAL',
                    'reason': 'TOOLS_EXECUTED',
                    'tools': [action.tool for action in body.actions],
                    'estimated_cost': 0.0, 'quality_score': 1.0, 'cache_hit': False,
                    'execution_ms': elapsed, 'context_hash': project_hash,
                    'project_files': project_files_used,
                    'project_discovery': project_discovery,
                    'context_status': 'RETRIEVAL_ENRICHED',
                    'flow': _flow_status(
                        workspace='SELECTED', discovery='COMPLETE', context='RETRIEVAL_ENRICHED',
                        route='LOCAL', action='EXECUTED',
                        verification=(
                            'COMPLETE' if agent_trace.verified is True else
                            'FAILED' if agent_trace.verified is False else 'SKIPPED'
                        ),
                        knowledge='EXTRACTED',
                    ),
                    'attachments': attachment_metadata,
                    'agent_trace': agent_trace.to_dict(),
                }

    context_hash = Store.key(project_hash, attachment_hash) if attachment_hash else project_hash
    # Action-bearing requests are never replayed through the response cache.
    cached = None if body.actions else store.get_cache(prompt, context_hash)
    if cached:
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO usage_events(provider,model,task_type,cache_hit,created_at) VALUES(?,?,?,?,datetime('now'))",
                (cached['provider'], cached['model'], cached['task_type'], 1),
            )
        return {
            'response': cached['response'], 'provider': cached['provider'],
            'model': cached['model'], 'task_type': cached['task_type'],
            'route': 'CACHE', 'reason': 'EXACT_CACHE_HIT', 'tools': [], 'cache_hit': True,
            'context_hash': context_hash, 'project_files': project_files_used,
            'project_discovery': project_discovery,
            'context_status': 'CACHE_SUFFICIENT',
            'flow': _flow_status(
                workspace='SELECTED' if body.project else 'NOT_SELECTED',
                discovery='COMPLETE' if body.project else 'SKIPPED',
                context='CACHE_SUFFICIENT', route='CACHE', action='SKIPPED',
                verification='SKIPPED', knowledge='RETRIEVED',
            ),
            'attachments': attachment_metadata,
            'fallback_trace': [{'source': 'local', 'status': 'success', 'kind': 'exact_cache'}],
        }

    routing_prompt = f'{prompt}\n[image attachment]' if images else prompt
    task_type = router.classify(routing_prompt)
    skill_context, skills_used = basic_skills.context_for(prompt)

    local_context = intelligence_engine.build_context(prompt, task_type.value, body.project, store)
    observation_context = ''
    if agent_trace and agent_trace.observations:
        observation_context = 'Tool observations:\n' + json.dumps(
            agent_trace.observations, ensure_ascii=True
        )[:20_000]
    context_parts = [
        part for part in (
            local_context, project_reference, attachment_reference, observation_context
        ) if part
    ]
    combined_context = '\n\n'.join(context_parts)
    context_status = 'RETRIEVAL_ENRICHED' if combined_context else 'ROUTER_REQUIRED'

    system_prompt = body.system + (
        '\n\nUse the following approved reference skill as guidance. '
        'Never bypass the agent permission system.\n' + skill_context if skill_context else ''
    ) + (f"\n\nContext:\n{combined_context}" if combined_context else "")

    # Novel generation exhausts the router's local/cloud sequence through one provider contract.
    available_models = model_registry.list()
    candidates = _cloud_candidates(routing_prompt, available_models)
    fallback_trace = []
    if not candidates:
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': (
                'No capable local or cloud AI provider is currently available. '
                'Check the local runtime or configure a cloud provider.'
            ),
            'fallback_trace': fallback_trace,
        })

    response = usage = decision = None
    provider_name = selected_model = None
    selected_metadata = None
    attempt_started = perf_counter()
    for candidate in candidates:
        candidate_started = perf_counter()
        try:
            candidate_response, candidate_usage = await _provider_completion(
                candidate, prompt, system_prompt, images
            )
            if not validate(candidate_response)['accepted']:
                raise RuntimeError('Quality gate rejected response')
            response, usage, decision = candidate_response, candidate_usage, candidate
            provider_name, selected_model = candidate.provider, candidate.model_id
            selected_metadata = _model_metadata(
                available_models, provider_name, selected_model
            )
            attempt_started = candidate_started
            fallback_trace.append(_attempt_record(candidate, 'success'))
            break
        except Exception as error:
            latency = int((perf_counter() - candidate_started) * 1000)
            store.add_routing_experience(
                candidate.route.value, candidate.provider, candidate.model_id or '',
                ','.join(candidate.task_type), False, 0.0, latency, candidate.tools,
            )
            fallback_trace.append(_attempt_record(candidate, 'failed', error))

    if response is None or usage is None or decision is None:
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': 'All capable local and cloud model alternatives failed.',
            'fallback_trace': fallback_trace,
        })

    # Default model fallback for providers that don't expose model_id via discovery
    cloud_defaults = {
        'local': settings.local_model_name,
        'openai': settings.openai_model, 'gemini': settings.gemini_model,
        'anthropic': settings.anthropic_model, 'xai': '', 'nvidia': '', 'deepseek': '',
    }
    response = redact(response)
    model = selected_model or cloud_defaults.get(provider_name, '')
    input_tokens, output_tokens = _usage_tokens(usage)
    estimated_cost = _estimated_cost(selected_metadata, input_tokens, output_tokens)

    intelligence_engine.extract_knowledge(prompt, response, task_type.value, provider_name, model, body.project)

    if not body.actions:
        store.put_cache(
            prompt, response, provider_name, model, task_type.value,
            body.project, context_hash=context_hash,
        )
    store.add_memory('conversation', prompt, body.project, task_type.value)
    elapsed = int((perf_counter() - started) * 1000)
    attempt_latency = int((perf_counter() - attempt_started) * 1000)

    with store.connection() as conn:
        conn.execute(
            "INSERT INTO usage_events(provider,model,task_type,input_tokens,output_tokens,estimated_cost,cache_hit,created_at) VALUES(?,?,?,?,?,?,?,datetime('now'))",
            (provider_name, model, task_type.value,
             input_tokens, output_tokens, estimated_cost, 0),
        )
        conn.execute(
            "INSERT INTO experiences(task,provider,model,outcome,execution_ms,metadata_json,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
            (prompt, provider_name, model, 'success', elapsed, '{}'),
        )

    quality = validate(response)['quality_score']
    store.add_routing_experience(
        decision.route.value, provider_name, model, ','.join(decision.task_type),
        True, quality, attempt_latency, decision.tools,
    )
    if agent_trace:
        if agent_trace.verified is False and settings.max_repair_attempts > 0:
            agent_trace.stage(
                'FIX', status='not_executed',
                detail='Verification failed; a new approved repair action is required.',
            )
            agent_trace.stage('VERIFY_AGAIN', status='skipped')
        else:
            agent_trace.stage('FIX', status='skipped')
            agent_trace.stage('VERIFY_AGAIN', status='skipped')
        agent_trace.stage('FINAL_RESPONSE')

    return {
        'response': response, 'provider': provider_name, 'model': model,
        'task_type': task_type.value, 'skills_used': skills_used,
        'route': decision.route.value, 'reason': decision.reason,
        'tools': decision.tools, 'estimated_cost': estimated_cost,
        'quality_score': quality, 'cache_hit': False, 'execution_ms': elapsed,
        'context_hash': context_hash, 'project_files': project_files_used,
        'project_discovery': project_discovery,
        'context_status': context_status,
        'flow': _flow_status(
            workspace='SELECTED' if body.project else 'NOT_SELECTED',
            discovery='COMPLETE' if body.project else 'SKIPPED',
            context=context_status, route=decision.route.value,
            action='EXECUTED' if agent_trace else 'SKIPPED',
            verification=(
                'COMPLETE' if agent_trace and agent_trace.verified is True else
                'FAILED' if agent_trace and agent_trace.verified is False else 'SKIPPED'
            ),
            knowledge='EXTRACTED',
        ),
        'attachments': attachment_metadata, 'fallback_trace': fallback_trace,
        'agent_trace': agent_trace.to_dict() if agent_trace else None,
    }

def _flow_status(*, workspace: str, discovery: str, context: str, route: str,
                 action: str, verification: str, knowledge: str) -> dict:
    return {
        'workspace': workspace, 'discovery': discovery, 'context': context,
        'route': route, 'action': action, 'verification': verification,
        'knowledge': knowledge,
    }


def _action_receipt(root: Path, trace) -> str:
    """Build a factual user response solely from successful MCP observations."""
    lines = []
    for item in trace.observations:
        output = item.get('output')
        relative = None
        if isinstance(output, dict):
            relative = output.get('path') or output.get('destination')
        if relative:
            target = (root / str(relative)).resolve()
            lines.append(f"- {item['tool']}: {target}")
        else:
            lines.append(f"- {item['tool']}: completed")
    return 'Workspace actions completed successfully.\n' + '\n'.join(lines)


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


# ── SPA fallback — MUST be the very last route registered ───────────────────
# Any GET that isn't /api/... or /static/... serves index.html so the
# client-side router handles /settings, /providers, /chats, etc.
@app.get('/{full_path:path}')
def spa_fallback(full_path: str):
    if full_path.startswith('api/') or full_path.startswith('static/'):
        raise HTTPException(404, 'Not found')
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / 'static' / 'index.html')
