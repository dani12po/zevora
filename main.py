from pathlib import Path
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
import asyncio
import uuid
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent.config import ROOT, reload_settings, settings
from zevora.version import __version__
from agent.memory.store import Store
from agent.models.manager import LocalIntelligenceManager
from agent.models.registry import ModelRegistry
from agent.providers.discovery import ProviderDiscovery
from agent.providers.errors import (
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    failure_details,
)
from agent.providers.local_provider import local_runtime_status
from agent.providers.registry import get_provider
from agent.providers.service import ProviderService
from agent.routing.hybrid_router import AdaptiveHybridRouter, Route
from agent.routing.model_selector import ModelSelector
from agent.routing.quality_gate import validate
from agent.routing.router import ModelRouter
from agent.routing.task_classifier import TaskClassifier
from agent.security.redaction import redact
from agent.core.attachments import attachment_context, process_attachment
from agent.core.execution import AgentAction, ProjectAgentExecutor
from agent.core.persona import ZEVORA_PERSONA
from agent.core.planning import parse_action_plan, planning_system_prompt, public_action
from agent.core.project_index import format_project_context, index_project, project_context
from agent.core.workspace import WorkspaceManager
from agent.intelligence.engine import LocalIntelligenceEngine
from agent.evolution.contribution import ContributionQueue
from agent.evolution.engine import EvolutionEngine
from agent.skills.openclaw import OpenClawSkillSource
from agent.skills.registry import SkillRegistry
from agent.storage.cleanup import CleanupManager
from agent.storage.context_economy import (
    build_context as build_economic_context,
    estimate_tokens,
)
from agent.storage.maintenance import MaintenanceScheduler
from agent.storage.storage_manager import StorageManager
from agent.tools.mcp_gateway import LocalMCPGateway
from agent.tools.terminal_sessions import TerminalSessionManager

# ── Singletons ────────────────────────────────────────────────────────────────
store         = Store(settings.database_file)
_progress_lock = Lock()
_progress_events: dict[str, dict] = {}
_stream_event_callback: ContextVar = ContextVar('stream_event_callback', default=None)
_workflow_request_id: ContextVar = ContextVar('workflow_request_id', default=None)
_stream_subscribers: dict[str, set[asyncio.Queue]] = {}
_chat_runs: dict[str, asyncio.Task] = {}
router        = ModelRouter()
local_manager = LocalIntelligenceManager()
intelligence_engine = LocalIntelligenceEngine(settings.database_file)
basic_skills  = OpenClawSkillSource()
skill_registry = SkillRegistry()
evolution_engine = EvolutionEngine(store, skill_registry)
contribution_queue = ContributionQueue(store)
storage_manager   = StorageManager(ROOT)
model_registry    = ModelRegistry(ROOT / 'data' / 'database' / 'model_registry.db')
provider_service  = ProviderService()
mcp_gateway       = LocalMCPGateway()
terminal_sessions = TerminalSessionManager()
hybrid_router     = AdaptiveHybridRouter()
workspace_manager = WorkspaceManager(ROOT / 'data' / 'database' / 'workspace.db')
_PROVIDER_CONFIG_LOCK = Lock()

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

# ── App + lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app):
    # One bounded startup refresh; requests never trigger repeated model discovery.
    await ProviderDiscovery(model_registry).refresh()
    yield

app = FastAPI(
    title='ZEVORA — Zero-External Vendor Oriented Reasoning Agent',
        version=__version__,
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

@app.exception_handler(RequestValidationError)
async def api_validation_error(_: Request, error: RequestValidationError):
    details = [
        {key: value for key, value in item.items() if key not in {'ctx', 'input'}}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={
        'ok': False,
        'error': {
            'code': 'VALIDATION_ERROR',
            'message': 'Request validation failed.',
            'details': details,
        },
    })


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
    data_base64: str = Field(min_length=1, max_length=14_000_000)

class AgentActionRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)
    approved: bool = False
    purpose: str = Field(default='', max_length=500)

class TaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    progress_id: str | None = Field(default=None, max_length=80)
    project: str | None = Field(default=None, max_length=4096)
    system: str = Field(
        default=ZEVORA_PERSONA, max_length=20_000
    )
    mode: str = Field(default='auto', max_length=32)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    project_id: int = Field(gt=0)
class MCPToolUpdateRequest(BaseModel):
    enabled: bool
class TerminalSessionRequest(BaseModel):
    project_id: int = Field(gt=0)
    command: str = Field(min_length=1, max_length=4096)
    cwd: str = Field(default='', max_length=4096)
    timeout: int = Field(default=120, ge=1, le=600)
    approved: bool = False
class FileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=2_000_000)
class IndexRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    approved: bool = False
class ProjectLoadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
class SettingsUpdateRequest(BaseModel):
    routing_mode: str | None = None
    cloud_fallback: bool | None = None
    cost_optimization: bool | None = None
class ChatCreateRequest(BaseModel):
    title: str = Field(default='New chat', min_length=1, max_length=120)
    project_id: int | None = Field(default=None, gt=0)
class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1,max_length=20000)
    progress_id: str | None = Field(default=None, max_length=80)
    mode: str = Field(default='auto', max_length=32)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
class ChatRequest(BaseModel):
    message: str = Field(min_length=1,max_length=20000)
    request_id: str | None = Field(default=None, max_length=80)
    conversation_id: str | None = Field(default=None, max_length=128)
    project_id: int | None = Field(default=None, gt=0)
    project_context: str | None = Field(default=None, max_length=20_000)
    mode: str = Field(default='auto', max_length=32)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
class ChatRenameRequest(BaseModel): title: str = Field(min_length=1, max_length=120)
class ChatFeedbackRequest(BaseModel):
    rating: str | None = Field(default=None, pattern='^(up|down)$')
class ApprovalRequest(BaseModel):
    approved: bool = False
class ProviderConfigRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    routing_priority: int | None = Field(default=None, ge=0, le=100)
    supports_vision: bool | None = None
class ProviderManifestRequest(BaseModel):
    manifest: dict
    credential_value: str | None = Field(default=None, max_length=4096)
    script: str | None = Field(default=None, max_length=524288)
class ProviderAnalysisRequest(BaseModel):
    source: str = Field(min_length=1, max_length=524288)
    language: str = Field(default='auto', max_length=32)
class ProviderTestRequest(BaseModel):
    runtime_approved: bool = False
class ProviderTrustRequest(BaseModel):
    approved: bool = False
class ProviderEnabledRequest(BaseModel):
    enabled: bool
class ProviderExampleRequest(BaseModel):
    language: str = Field(default='python', max_length=32)

def _dashboard_response():
    from fastapi.responses import FileResponse
    return FileResponse(
        ROOT / 'static' / 'index.html',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        },
    )


@app.get('/')
def dashboard():
    return _dashboard_response()
@app.get('/health')
def gateway_health(): return {'ok':True,'status':'ok','service':'zevora','version':__version__,'gateway':'running'}
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
        'ok': True, 'status': 'ok', 'service': 'zevora', 'version': __version__,
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

@app.get('/api/evolution/status')
def evolution_status():
    skills = skill_registry.list()
    return {
        'version': __version__,
        'local_intelligence': {
            'runtime': settings.local_model_runtime,
            'enabled': settings.local_model_enabled,
            'package_directory': str(settings.local_model_package_dir),
            'configured_model': settings.local_model_name,
            'installed_packages': model_registry.installed_local_packages(),
            'discovered_models': local_manager.discover_models(),
            'installation_choices': local_manager.installation_choices(),
        },
        'skills': [{
            'skill_id': item.skill_id,
            'name': item.name,
            'version': item.version,
            'capabilities': list(item.capabilities),
            'tool_requirements': list(item.tool_requirements),
            'confidence': item.confidence,
            'usage_count': item.usage_count,
            'success_count': item.success_count,
            'failure_count': item.failure_count,
            'source': item.source,
            'trust_state': item.trust_state,
        } for item in skills],
        'evolution': evolution_engine.status(),
        'collective_learning': contribution_queue.status(),
        'updates': {
            'channel': settings.update_channel,
            'manifest_configured': bool(settings.update_manifest_url),
            'verification': 'sha256_required',
            'activation': 'staged_atomic_with_rollback',
        },
    }

@app.post('/api/local-intelligence/uninstall')
def uninstall_local_intelligence(body: ApprovalRequest):
    try:
        return local_manager.uninstall_package(approved=body.approved)
    except ValueError as error:
        raise HTTPException(400, {
            'code': 'UNINSTALL_PATH_REJECTED', 'message': str(error),
        }) from error
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
    try:
        _atomic_write_text(config_file, json.dumps(saved, indent=2) + '\n')
        reload_settings()
    except OSError as error:
        raise HTTPException(500, {
            'code': 'SETTINGS_WRITE_FAILED',
            'message': f'Unable to persist settings: {type(error).__name__}',
        }) from error
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
    verification = refresh[0] if refresh else {
        'health_status': 'disabled' if body.enabled is False else 'unconfigured',
        'models_discovered': 0,
        'failure_reason': 'PROVIDER_DISABLED' if body.enabled is False else 'PROVIDER_UNCONFIGURED',
        'failure_message': (
            'The provider is disabled.' if body.enabled is False
            else 'The provider credential is not configured.'
        ),
    }
    return {
        'ok': True,
        'provider': provider_name,
        'key_updated': body.api_key is not None,
        'status': verification['health_status'],
        'models_discovered': verification['models_discovered'],
        'failure_reason': verification.get('failure_reason'),
        'failure_message': verification.get('failure_message'),
    }


@app.post('/api/providers/{provider_name}/test')
async def test_builtin_provider(provider_name: str):
    """Verify a built-in provider without changing its saved configuration."""
    normalized = provider_name.strip().lower()
    allowed = {'openai', 'xai', 'nvidia', 'deepseek', 'gemini', 'anthropic'}
    if normalized not in allowed:
        raise HTTPException(404, {
            'code': 'PROVIDER_NOT_FOUND', 'message': 'Provider was not found.',
        })
    refresh = await ProviderDiscovery(model_registry).refresh(normalized)
    verification = refresh[0]
    return {
        'ok': (
            verification['health_status'] == 'healthy'
            and verification['models_discovered'] > 0
        ),
        'provider': normalized,
        'status': verification['health_status'],
        'models_discovered': verification['models_discovered'],
        'failure_reason': verification.get('failure_reason'),
        'failure_message': verification.get('failure_message'),
    }


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


@app.get('/api/provider-manifests')
def provider_manifests():
    return {
        'providers': provider_service.list(),
        'runtime_availability': provider_service.runtime_availability(),
    }


@app.get('/api/provider-manifests/{provider_id}')
def provider_manifest(provider_id: str):
    try:
        return provider_service.get(provider_id)
    except (KeyError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests')
async def save_provider_manifest(body: ProviderManifestRequest):
    try:
        saved = provider_service.save(
            body.manifest, credential_value=body.credential_value, script=body.script,
        )
        refresh = await ProviderDiscovery(model_registry).refresh(saved['provider_id'])
        return {'ok': True, 'provider': saved, 'discovery': refresh}
    except (KeyError, PermissionError, TypeError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/import')
async def import_provider_manifest(body: ProviderManifestRequest):
    try:
        saved = provider_service.import_manifest(
            body.manifest, credential_value=body.credential_value, script=body.script,
        )
        refresh = await ProviderDiscovery(model_registry).refresh(saved['provider_id'])
        return {'ok': True, 'provider': saved, 'discovery': refresh}
    except (json.JSONDecodeError, KeyError, PermissionError, TypeError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/analyze')
def analyze_provider_script(body: ProviderAnalysisRequest):
    try:
        return {'ok': True, 'analysis': provider_service.analyze(body.source, body.language)}
    except ValueError as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/test')
async def test_provider_manifest(provider_id: str, body: ProviderTestRequest):
    try:
        result = await provider_service.test(
            provider_id, runtime_approved=body.runtime_approved,
        )
        return {'ok': bool(result.get('success')), 'result': result}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/runtime-test')
async def test_provider_runtime(provider_id: str, body: ProviderTestRequest):
    if not body.runtime_approved:
        raise HTTPException(403, {
            'code': 'PROVIDER_RUNTIME_APPROVAL_REQUIRED',
            'message': 'Explicit one-time runtime approval is required.',
        })
    try:
        result = await provider_service.test(provider_id, runtime_approved=True)
        return {'ok': bool(result.get('success')), 'result': result}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/trust')
def trust_provider_runtime(provider_id: str, body: ProviderTrustRequest):
    try:
        return {'ok': True, 'provider': provider_service.trust_runtime(
            provider_id, approved=body.approved,
        )}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/enabled')
def enable_provider_manifest(provider_id: str, body: ProviderEnabledRequest):
    try:
        return {'ok': True, 'provider': provider_service.set_enabled(provider_id, body.enabled)}
    except (KeyError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/models/refresh')
async def refresh_provider_models(provider_id: str):
    try:
        result = await provider_service.refresh_models(provider_id)
        await ProviderDiscovery(model_registry).refresh(provider_id)
        return {'ok': True, **result}
    except (KeyError, PermissionError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.post('/api/provider-manifests/{provider_id}/example')
def generate_provider_example(provider_id: str, body: ProviderExampleRequest):
    try:
        return {'ok': True, **provider_service.generate_example(provider_id, body.language)}
    except (KeyError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.get('/api/provider-manifests/{provider_id}/export')
def export_provider_manifest(provider_id: str):
    try:
        return provider_service.export_manifest(provider_id)
    except KeyError as error:
        raise _provider_service_error(error) from error


@app.get('/api/provider-manifests/{provider_id}/source')
def provider_runtime_source(provider_id: str):
    try:
        return {'provider_id': provider_id, 'source': provider_service.runtime_source(provider_id)}
    except (KeyError, OSError, ValueError) as error:
        raise _provider_service_error(error) from error


@app.delete('/api/provider-manifests/{provider_id}')
def delete_provider_manifest(provider_id: str):
    try:
        removed = provider_service.remove(provider_id)
    except ValueError as error:
        raise _provider_service_error(error) from error
    if not removed:
        raise _provider_service_error(KeyError(provider_id))
    return {'ok': True, 'provider_id': provider_id}


@app.get('/api/usage/history')
def usage_history(
    provider: str | None = Query(default=None, max_length=80),
    days: int = Query(default=30, ge=1, le=365),
):
    """Per-day, per-provider breakdown from usage_events table."""
    with store.connection() as conn:
        sql = '''SELECT date(created_at) day, provider, model,
                    COUNT(*) requests, COALESCE(SUM(cache_hit),0) cache_hits,
                    COALESCE(SUM(input_tokens),0) input_tokens,
                    COALESCE(SUM(output_tokens),0) output_tokens,
                    COALESCE(SUM(estimated_cost),0) estimated_cost
                 FROM usage_events
                 WHERE date(created_at) >= date('now', ?)'''
        args: list = [f'-{days} days']
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
    project = workspace_manager.get(body.project_id)
    if not project:
        raise HTTPException(404, {'code': 'PROJECT_NOT_FOUND', 'message': 'Selected project was not found.'})
    try:
        result = terminal_sessions.start(
            Path(project['path']), body.command, approved=body.approved,
            timeout=body.timeout, cwd=body.cwd,
            preferences=workspace_manager.permissions(body.project_id),
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
    result = terminal_sessions.get(session_id, after)
    if result is None:
        raise HTTPException(404, {'code': 'TERMINAL_SESSION_NOT_FOUND', 'message': 'Terminal session was not found.'})
    return result

@app.post('/api/terminal/sessions/{session_id}/kill')
def kill_terminal_session(session_id: str):
    result = terminal_sessions.kill(session_id)
    if result is None:
        raise HTTPException(404, {'code': 'TERMINAL_SESSION_NOT_FOUND', 'message': 'Terminal session was not found.'})
    return {'ok': True, **result}

@app.delete('/api/terminal/sessions/{session_id}')
def clear_terminal_session(session_id: str):
    if not terminal_sessions.clear(session_id):
        raise HTTPException(404, {'code': 'TERMINAL_SESSION_NOT_FOUND', 'message': 'Terminal session was not found.'})
    return {'ok': True, 'session_id': session_id}

@app.get('/api/models')
def models(provider: str | None = None): return model_registry.list(provider)
@app.post('/api/models/refresh')
async def refresh_models(provider: str | None = None): return await ProviderDiscovery(model_registry).refresh(provider)
@app.get('/api/route')
def route(prompt: str = Query(min_length=1, max_length=20_000)):
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
    try: return workspace_manager.audit(project_id)
    except ValueError as error: raise HTTPException(404,str(error))
@app.get('/api/chats')
def chats(
    limit: int = Query(default=100, ge=1, le=500),
    query: str | None = Query(default=None, max_length=120),
):
    with workspace_manager.connection() as conn:
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
    if body.project_id is not None and not workspace_manager.get(body.project_id):
        raise HTTPException(404, {
            'code': 'PROJECT_NOT_FOUND', 'message': 'Selected project was not found.',
        })
    return workspace_manager.create_chat(body.title,body.project_id)
@app.get('/api/chats/{chat_id}')
def get_chat(chat_id:str):
    chat=workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    return chat
@app.delete('/api/chats')
def delete_all_chats():
    with workspace_manager.connection() as conn:
        count = conn.execute('SELECT COUNT(*) FROM chats').fetchone()[0]
        conn.execute('DELETE FROM message_feedback')
        conn.execute('DELETE FROM chat_messages')
        conn.execute('DELETE FROM chats')
    return {'ok':True,'deleted':count}
@app.delete('/api/chats/{chat_id}')
def delete_chat(chat_id:str):
    with workspace_manager.connection() as conn:
        row=conn.execute('SELECT id FROM chats WHERE id=?',(chat_id,)).fetchone()
        if not row: raise HTTPException(404,'Chat not found')
        conn.execute('DELETE FROM message_feedback WHERE chat_id=?',(chat_id,))
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
_CHAT_METADATA_KEYS = (
    'route','reason','provider','model','tools','quality_score','attachments',
    'agent_trace','agentic_log','fallback_trace','estimated_cost','context_hash','project_files',
    'project_discovery','context_status','flow','execution_ms','workflow',
)

def _chat_metadata(result):
    return {key:result.get(key) for key in _CHAT_METADATA_KEYS}

async def _complete_chat_turn(chat, content, body):
    project=workspace_manager.get(chat['project_id']) if chat['project_id'] else None
    result = await task(TaskRequest(
        prompt=content, project=project['path'] if project else None,
        mode=body.mode, provider=body.provider, model=body.model,
        attachments=body.attachments, actions=body.actions, progress_id=body.progress_id,
    ))
    if body.progress_id:
        result['workflow'] = _progress_snapshot(body.progress_id)
    return result

@app.post('/api/chats/{chat_id}/messages')
async def chat_message(chat_id:str,body:ChatMessageRequest):
    chat=workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    result=await _complete_chat_turn(chat, body.content, body)
    message_id=workspace_manager.add_exchange(chat_id,redact(body.content),result['response'],_chat_metadata(result))
    return {**result,'message_id':message_id,'chat_id':chat_id,'feedback':None}

@app.post('/api/chats/{chat_id}/messages/{message_id}/regenerate')
async def regenerate_message(chat_id:str,message_id:int,body:ChatMessageRequest):
    chat=workspace_manager.get_chat(chat_id)
    if not chat: raise HTTPException(404,'Chat not found')
    content=workspace_manager.previous_user_message(chat_id,message_id)
    if content is None:
        raise HTTPException(404,'Original user message not found for this answer')
    result=await _complete_chat_turn(chat, content, body)
    workspace_manager.update_assistant_message(
        chat_id, message_id, result['response'], _chat_metadata(result),
    )
    return {**result,'message_id':message_id,'chat_id':chat_id,'feedback':None,'regenerated':True}

@app.post('/api/chats/{chat_id}/messages/{message_id}/feedback')
def message_feedback(chat_id: str, message_id: int, body: ChatFeedbackRequest):
    chat = workspace_manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, 'Chat not found')
    try:
        rating = workspace_manager.set_feedback(chat_id, message_id, body.rating)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {'ok': True, 'chat_id': chat_id, 'message_id': message_id, 'rating': rating}
@app.get('/api/chat/progress/{request_id}')
def chat_progress(request_id: str, after: int = Query(default=0, ge=0)):
    # FastAPI injects an integer for HTTP calls; direct callers see the Query
    # marker when omitting the optional argument.
    if not isinstance(after, int):
        after = 0
    with _progress_lock:
        progress = _progress_events.get(request_id)
        snapshot = dict(progress) if progress else None
        if snapshot is not None:
            snapshot['events'] = [
                dict(item) for item in progress.get('events', [])
                if item.get('sequence', 0) > after
            ]
            snapshot['stages'] = [dict(item) for item in progress.get('stages', [])]
            if progress.get('current'):
                snapshot['current'] = dict(progress['current'])
    if snapshot is None:
        raise HTTPException(404, 'Chat progress not found')
    return snapshot


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


def _sse_frame(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=True, separators=(',', ':'))}\n\n"


async def _execute_chat_request(body: ChatRequest, request_id: str) -> dict:
    _progress_start(request_id)
    request_token = _workflow_request_id.set(request_id)
    _progress_update(request_id, 'RECEIVED', 'Request received')
    _progress_update(request_id, 'UNDERSTANDING', 'Understanding the request', 'running')
    chat_id = body.conversation_id
    if not chat_id:
        chat_id = workspace_manager.create_chat(body.message[:80], body.project_id)['id']
    existing = workspace_manager.get_chat(chat_id)
    if not existing:
        raise HTTPException(404, 'Conversation not found')
    if body.project_id is not None and existing['project_id'] != body.project_id:
        project = workspace_manager.get(body.project_id)
        if not project:
            raise HTTPException(404, 'Project not found')
        with workspace_manager.connection() as conn:
            conn.execute('UPDATE chats SET project_id=? WHERE id=?', (body.project_id, chat_id))
        existing = workspace_manager.get_chat(chat_id)
    if existing['title'] == 'New chat':
        workspace_manager.set_title(chat_id, body.message[:80])
    try:
        result = await chat_message(
            chat_id,
            ChatMessageRequest(
                content=body.message, mode=body.mode, provider=body.provider,
                model=body.model, attachments=body.attachments, actions=body.actions,
                progress_id=request_id,
            ),
        )
        _progress_update(request_id, 'COMPLETED', 'Workflow completed')
        _progress_finish(request_id)
        workflow = _progress_snapshot(request_id)
        result['workflow'] = workflow
        workspace_manager.update_assistant_message(
            chat_id, result['message_id'], result['response'], _chat_metadata(result),
        )
        return {'ok': True, **result, 'conversation_id': chat_id, 'request_id': request_id}
    except asyncio.CancelledError:
        snapshot = _progress_snapshot(request_id) or {}
        if snapshot.get('status') != 'cancelled':
            _progress_update(request_id, 'CANCELLED', 'Request cancelled', 'cancelled')
            _progress_finish(request_id, 'cancelled')
        raise
    except Exception as error:
        _progress_update(request_id, 'FAILED', f'Request failed: {type(error).__name__}', 'failed')
        _progress_finish(request_id, 'failed')
        raise
    finally:
        _workflow_request_id.reset(request_token)


async def _chat_request(body: ChatRequest) -> dict:
    request_id = body.request_id or 'zv-' + uuid.uuid4().hex[:12]
    current = _chat_runs.get(request_id)
    if current is None:
        current = asyncio.create_task(_execute_chat_request(body, request_id))
        _chat_runs[request_id] = current
        if len(_chat_runs) > 128:
            for key, run in list(_chat_runs.items()):
                if key != request_id and run.done():
                    _chat_runs.pop(key, None)
                if len(_chat_runs) <= 128:
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
    return {'code': 'INTERNAL_ERROR', 'message': f'Unexpected gateway error: {type(error).__name__}'}


@app.post('/api/chat/stream')
async def chat_stream(body: ChatRequest, request: Request):
    request_id = body.request_id or 'zv-' + uuid.uuid4().hex[:12]
    body.request_id = request_id
    queue: asyncio.Queue = asyncio.Queue()
    with _progress_lock:
        _stream_subscribers.setdefault(request_id, set()).add(queue)
        snapshot = _progress_events.get(request_id)
        replay = [dict(item) for item in (snapshot or {}).get('events', [])]

    async def run() -> None:
        try:
            result = await _chat_request(body)
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
                    snapshot = _progress_snapshot(request_id)
                    yield _sse_frame({
                        'type': 'heartbeat', 'request_id': request_id,
                        'sequence': snapshot.get('sequence', 0) if snapshot else 0,
                        'timestamp': _utc_timestamp(),
                    })
                    continue
                yield _sse_frame(event)
                if event.get('type') in {'final', 'error'}:
                    break
        finally:
            with _progress_lock:
                subscribers = _stream_subscribers.get(request_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        _stream_subscribers.pop(request_id, None)
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
    run = _chat_runs.get(request_id)
    if run is None:
        raise HTTPException(404, 'Chat request not found')
    snapshot = _progress_snapshot(request_id) or {}
    if not run.done() and snapshot.get('status') not in {'completed', 'failed', 'cancelled'}:
        _progress_update(request_id, 'CANCELLED', 'Cancellation requested', 'cancelled')
        _progress_finish(request_id, 'cancelled')
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
    elif not run.done():
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
    snapshot = _progress_snapshot(request_id) or {}
    return {
        'ok': True,
        'request_id': request_id,
        'status': snapshot.get('status', 'cancelled'),
    }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


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


@app.post('/api/chat')
async def chat(body: ChatRequest):
    return await _chat_request(body)
@app.post('/api/index')
def index(body: IndexRequest):
    root = Path(body.path).resolve()
    registered = next((
        project for project in workspace_manager.projects()
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
    store.replace_project_files(str(root), context['rows'])
    return {
        'project': str(root), 'files_indexed': context['files_indexed'],
        'context_hash': context['context_hash'],
    }


def _filter_routing_models(
    available_models: list[dict], mode: str = 'auto',
    provider: str | None = None, model: str | None = None,
) -> list[dict]:
    if mode == 'local':
        return [item for item in available_models if item.get('provider') == 'local']
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
        model_registry.list(), mode, provider, model
    )
    candidates = _cloud_candidates(
        prompt, available_models, context_tokens, require_native_tools
    )
    if candidates:
        return available_models, candidates

    refresh_provider = 'local' if mode == 'local' else provider
    try:
        await asyncio.wait_for(
            ProviderDiscovery(model_registry).refresh(refresh_provider),
            timeout=settings.discovery_timeout_seconds,
        )
    except asyncio.TimeoutError:
        # A slow health/model-list probe must not block response generation indefinitely.
        pass
    available_models = _filter_routing_models(
        model_registry.list(), mode, provider, model
    )
    return available_models, _cloud_candidates(
        prompt, available_models, context_tokens, require_native_tools
    )


def _cloud_candidates(
    prompt: str, available_models: list[dict], context_tokens: int = 0,
    require_native_tools: bool = True,
) -> list:
    """Build the hybrid provider/model fallback sequence.

    The legacy name is retained for planner and extension compatibility.
    """
    performance = store.routing_performance()
    if hasattr(hybrid_router, 'candidates'):
        candidates = hybrid_router.candidates(
            prompt,
            available_models,
            performance=performance,
            context_tokens=context_tokens,
            require_native_tools=require_native_tools,
        )
        if not settings.cloud_fallback:
            return candidates[:1]
        return candidates[:max(1, settings.routing_max_attempts)]

    primary = hybrid_router.decide(
        prompt,
        available_models,
        performance=performance,
        context_tokens=context_tokens,
        require_native_tools=require_native_tools,
    )
    if primary.route not in {Route.LOCAL, Route.CLOUD}:
        return []
    candidates = [primary]
    if settings.cloud_fallback:
        fallback = hybrid_router.decide(
            prompt, available_models, exclude_providers={primary.provider},
            performance=performance, context_tokens=context_tokens,
            require_native_tools=require_native_tools,
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


def _failure_reason(candidate, error: Exception) -> tuple[str, str]:
    """Return a stable, secret-free failure classification for the chat UI."""
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


async def _cloud_completion(prompt: str, system: str, requested_format: str = '',
                            response_validator=None,
                            require_native_tools: bool = True,
                            routing_prompt: str | None = None) -> dict:
    """Run hybrid completion; legacy name retained for caller compatibility."""
    classification_prompt = routing_prompt if routing_prompt is not None else prompt
    extra_context_tokens = max(
        0, estimate_tokens(prompt) - estimate_tokens(classification_prompt)
    )
    available_models, candidates = await _routing_candidates(
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
        await _emit_stream_event({
            'type': 'attempt_start', **_attempt_record(candidate, 'running'),
        })
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
            success_record = _attempt_record(candidate, 'success')
            fallback_trace.append(success_record)
            await _emit_stream_event({'type': 'attempt_result', **success_record})
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
            failure_record = _attempt_record(candidate, 'failed', error)
            fallback_trace.append(failure_record)
            await _emit_stream_event({'type': 'attempt_result', **failure_record})

    raise HTTPException(503, {
        'code': 'AI_EXECUTION_ERROR',
        'message': _fallback_failure_message(fallback_trace),
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
            require_native_tools=False,
            routing_prompt=body.prompt,
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
    progress_id = body.progress_id

    def progress(stage: str, status: str = 'completed', detail: str = '') -> None:
        _progress_update(progress_id, stage, detail, status)

    progress('UNDERSTAND', detail='Request accepted and being classified')
    mode = body.mode.strip().lower()
    if mode not in {'auto', 'local', 'provider', 'model'}:
        raise HTTPException(400, {
            'code': 'INVALID_ROUTING_OVERRIDE',
            'message': 'mode must be auto, local, provider, or model',
        })
    requested_provider = body.provider.strip().lower() if body.provider else None
    requested_model = body.model.strip() if body.model else None
    if mode == 'provider' and not requested_provider:
        raise HTTPException(400, {
            'code': 'INVALID_ROUTING_OVERRIDE', 'message': 'provider mode requires provider',
        })
    if mode == 'model' and (not requested_provider or not requested_model):
        raise HTTPException(400, {
            'code': 'INVALID_ROUTING_OVERRIDE',
            'message': 'model mode requires both provider and model',
        })
    try:
        progress('ATTACHMENTS', 'running', 'Processing attachments')
        processed_attachments = [
            process_attachment(item.name, item.media_type, item.data_base64)
            for item in body.attachments
        ]
    except ValueError as error:
        raise HTTPException(400, {'code': 'INVALID_ATTACHMENT', 'message': str(error)})
    attachment_metadata = [item.metadata() for item in processed_attachments]
    progress('ATTACHMENTS', detail=f'Prepared {len(processed_attachments)} attachment(s)')
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
    agentic_log: list[str] | None = None
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
        progress('INSPECT', 'running', 'Inspecting selected project')
        root = Path(body.project).resolve()
        if not root.is_dir():
            raise HTTPException(400, 'Project directory not found')

        # The browser is only a client.  Keep planning on the gateway so every
        # client gets the same agent behavior, including API/CLI callers.
        if not body.actions and _requires_workspace_agent(prompt):
            progress('PLAN', 'running', 'Planning workspace actions')
            project = workspace_manager.load(root)
            plan = await plan_agent_actions(PlanRequest(
                prompt=body.prompt, project_id=project['id'],
            ))
            body.actions = [AgentActionRequest(
                tool=item['tool'], arguments=item.get('arguments', {}),
                purpose=item.get('purpose', ''), approved=False,
            ) for item in plan.get('actions', [])]
            progress('PLAN', detail=f'Prepared {len(body.actions)} workspace action(s)')

        progress('RETRIEVE', 'running', 'Reading project context')
        context = project_context(root, prompt)
        store.replace_project_files(str(root), context['rows'])
        project_hash = context['context_hash']
        project_reference = format_project_context(context)
        project_files_used = [item['path'] for item in context['files']]
        project_discovery = context['discovery']
        progress('RETRIEVE', detail=f'Loaded {len(project_files_used)} project file reference(s)')
        if body.actions:
            project = workspace_manager.load(root)
            executor = ProjectAgentExecutor(root, preferences=project.get('permissions'))
            agent_trace = executor.execute(
                prompt,
                [AgentAction(**action.model_dump()) for action in body.actions],
                project_files_used,
                progress_callback=progress,
                event_callback=lambda event: _workflow_record(
                    progress_id,
                    stage=event.get('stage', 'EXECUTION'),
                    event=event.get('event', 'tool_completed'),
                    status=event.get('status', 'completed'),
                    title=event.get('title', 'Agent activity'),
                    message=event.get('message', ''),
                    data=event.get('data'),
                ),
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
            # Workspace actions may have changed project state; rebuild authoritative context.
            progress('RETRIEVE', 'running', 'Refreshing context after workspace changes')
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
                progress('FINAL_RESPONSE', 'running', 'Assembling the workspace result')
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
                    'agentic_log': None,
                    'workflow': _progress_snapshot(progress_id),
                }

    context_hash = Store.key(project_hash, attachment_hash) if attachment_hash else project_hash
    progress('REASON', detail='Preparing the response context')
    # Action-bearing and explicitly routed requests are never replayed through Auto cache entries.
    cached = None if body.actions or mode != 'auto' else store.get_cache(prompt, context_hash)
    if cached:
        progress('FINAL_RESPONSE', detail='Using a verified local response')
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
            'agentic_log': None,
            'workflow': _progress_snapshot(progress_id),
        }

    routing_prompt = f'{prompt}\n[image attachment]' if images else prompt
    task_type = router.classify(routing_prompt)
    progress('REASON', detail='Classifying the request and preparing skills')
    skill_context, skills_used = basic_skills.context_for(prompt)
    dynamic_skill_context, dynamic_skills = skill_registry.context_for(
        prompt, capabilities=set(task_type.value.split(',')), max_chars=8_000
    )
    if dynamic_skill_context:
        skill_context = '\n\n'.join(filter(None, (skill_context, dynamic_skill_context)))
        skills_used = list(dict.fromkeys([*skills_used, *dynamic_skills]))

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
    context_economy = build_economic_context(
        context_parts,
        max_tokens=settings.context_max_tokens,
    )
    combined_context = context_economy.text
    context_status = 'RETRIEVAL_ENRICHED' if combined_context else 'ROUTER_REQUIRED'

    system_prompt = body.system + '\n\n' + _AGENTIC_LOG_INSTRUCTION + (
        '\n\nUse the following approved reference skill as guidance. '
        'Never bypass the agent permission system.\n' + skill_context if skill_context else ''
    ) + (f"\n\nContext:\n{combined_context}" if combined_context else "")

    # Explicit selection narrows the same capability-aware router pool; it never bypasses routing checks.
    progress('ROUTE', 'running', 'Selecting a provider and model')
    available_models, candidates = await _routing_candidates(
        routing_prompt, context_economy.compressed_tokens,
        mode, requested_provider, requested_model,
    )
    if mode != 'auto' and not available_models:
        raise HTTPException(400, {
            'code': 'ROUTING_OVERRIDE_UNAVAILABLE',
            'message': 'The selected provider or model is not available in the model registry.',
        })
    fallback_trace = []
    if not candidates:
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': _fallback_failure_message(fallback_trace),
            'fallback_trace': fallback_trace,
        })

    response = usage = decision = None
    provider_name = selected_model = None
    selected_metadata = None
    attempt_started = perf_counter()
    for candidate in candidates[:max(1, settings.routing_max_attempts)]:
        progress('GENERATE', 'running', f'Generating response with {candidate.provider}')
        await _emit_stream_event({
            'type': 'attempt_start', **_attempt_record(candidate, 'running'),
        })
        candidate_started = perf_counter()
        try:
            candidate_response, candidate_usage = await _provider_completion(
                candidate, prompt, system_prompt, images
            )
            clean_candidate, candidate_log = _parse_agentic_response(candidate_response)
            if not validate(clean_candidate)['accepted']:
                raise RuntimeError('Quality gate rejected response')
            response, usage, decision = clean_candidate, candidate_usage, candidate
            agentic_log = candidate_log
            provider_name, selected_model = candidate.provider, candidate.model_id
            selected_metadata = _model_metadata(
                available_models, provider_name, selected_model
            )
            attempt_started = candidate_started
            success_record = _attempt_record(candidate, 'success')
            fallback_trace.append(success_record)
            await _emit_stream_event({'type': 'attempt_result', **success_record})
            break
        except Exception as error:
            latency = int((perf_counter() - candidate_started) * 1000)
            store.add_routing_experience(
                candidate.route.value, candidate.provider, candidate.model_id or '',
                ','.join(candidate.task_type), False, 0.0, latency, candidate.tools,
            )
            failure_record = _attempt_record(candidate, 'failed', error)
            fallback_trace.append(failure_record)
            await _emit_stream_event({'type': 'attempt_result', **failure_record})

    if response is None or usage is None or decision is None:
        progress('GENERATE', 'failed', 'No provider could complete the response')
        raise HTTPException(503, {
            'code': 'AI_EXECUTION_ERROR',
            'message': _fallback_failure_message(fallback_trace),
            'fallback_trace': fallback_trace,
        })

    # Default model fallback for providers that don't expose model_id via discovery
    cloud_defaults = {
        'local': settings.local_model_name,
        'openai': settings.openai_model, 'gemini': settings.gemini_model,
        'anthropic': settings.anthropic_model, 'xai': '', 'nvidia': '', 'deepseek': '',
    }
    response = redact(response)
    if agentic_log:
        agentic_log = [redact(item) for item in agentic_log]
    model = selected_model or cloud_defaults.get(provider_name, '')
    input_tokens, output_tokens = _usage_tokens(usage)
    context_metrics = {
        **context_economy.metrics(),
        'provider_tokens': input_tokens,
    }
    estimated_cost = _estimated_cost(selected_metadata, input_tokens, output_tokens)
    quality = validate(response)['quality_score']

    intelligence_engine.extract_knowledge(prompt, response, task_type.value, provider_name, model, body.project)

    if not body.actions and mode == 'auto':
        store.put_cache(
            prompt, response, provider_name, model, task_type.value,
            body.project, context_hash=context_hash,
        )
    store.add_memory('conversation', prompt, body.project, task_type.value)
    elapsed = int((perf_counter() - started) * 1000)
    attempt_latency = int((perf_counter() - attempt_started) * 1000)
    verified_outcome = bool(quality >= .5 and (not agent_trace or agent_trace.verified is not False))
    store.add_context_metrics(task_type.value, provider_name, model, context_metrics)
    compact_experience = {
        'task_class': task_type.value,
        'route': decision.route.value.lower(),
        'result': 'success',
        'provider': provider_name,
        'model': model,
        'skill_ids': skills_used,
        'confidence': quality,
        'execution_time_ms': elapsed,
        'verified': verified_outcome,
    }
    store.add_structured_experience(compact_experience)
    evolution_result = evolution_engine.observe(compact_experience, quality)

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

    progress('FINAL_RESPONSE', detail='Response ready')
    return {
        'response': response, 'provider': provider_name, 'model': model,
        'task_type': task_type.value, 'skills_used': skills_used,
        'route': decision.route.value, 'reason': decision.reason,
        'tools': decision.tools, 'estimated_cost': estimated_cost,
        'quality_score': quality, 'cache_hit': False, 'execution_ms': elapsed,
        'context_hash': context_hash, 'context_economy': context_metrics,
        'evolution': evolution_result,
        'project_files': project_files_used,
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
        'agentic_log': agentic_log,
        'workflow': _progress_snapshot(progress_id),
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


# ── SPA fallback — MUST be the very last route registered ───────────────────
# Any GET that isn't /api/... or /static/... serves index.html so the
# client-side router handles /settings, /providers, /chats, etc.
@app.get('/{full_path:path}')
def spa_fallback(full_path: str):
    if full_path.startswith('api/') or full_path.startswith('static/'):
        raise HTTPException(404, 'Not found')
    return _dashboard_response()
