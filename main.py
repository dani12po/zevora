import asyncio
import os
from collections import deque
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent.config import ROOT, reload_settings, settings
from agent.memory.store import Store
from agent.models.manager import LocalIntelligenceManager
from agent.models.registry import ModelRegistry
from agent.providers.discovery import ProviderDiscovery
from agent.providers.local_endpoint_provider import remote_endpoint_status
from agent.providers.local_provider import local_runtime_status
from agent.providers.registry import get_provider
from agent.providers.service import ProviderService
from agent.routing.hybrid_router import AdaptiveHybridRouter
from agent.routing.router import ModelRouter
from agent.core.workspace import WorkspaceManager
from agent.intelligence.engine import LocalIntelligenceEngine
from agent.evolution.contribution import ContributionQueue
from agent.evolution.engine import EvolutionEngine
from agent.skills.openclaw import OpenClawSkillSource
from agent.skills.registry import SkillRegistry
from agent.skills.security_research import build_security_research_skill
from agent.storage.storage_manager import StorageManager
from agent.tools.mcp_gateway import LocalMCPGateway
from agent.tools.terminal_sessions import TerminalSessionManager
from zevora.version import __version__

# Workflow progress state lives in api.progress; re-exported here so callers
# (tests, routers) address it as main.*. The stream-event mapper turns provider
# attempts into 'provider_selected' / 'provider_fallback' workflow events.
from api.progress import (  # noqa: E402
    _progress_lock, _progress_events, _stream_event_callback, _workflow_request_id,
    _stream_subscribers,
)  # noqa: F401  re-exported for backward compatibility  # re-exported for backward compatibility

# ── Singletons ────────────────────────────────────────────────────────────────
store         = Store(settings.database_file)
_chat_runs: dict[str, asyncio.Task] = {}
router        = ModelRouter()
local_manager = LocalIntelligenceManager()
intelligence_engine = LocalIntelligenceEngine(settings.database_file)
basic_skills  = OpenClawSkillSource()
skill_registry = SkillRegistry()
# Register the bundled, defensive security-research skill so it is available to
# the dynamic skill router. replace=True keeps startup idempotent across restarts.
skill_registry.register(build_security_research_skill(), replace=True)
evolution_engine = EvolutionEngine(store, skill_registry)
contribution_queue = ContributionQueue(store)
storage_manager   = StorageManager(ROOT)
model_registry    = ModelRegistry(ROOT / 'data' / 'database' / 'model_registry.db')
provider_service  = ProviderService()
mcp_gateway       = LocalMCPGateway()
terminal_sessions = TerminalSessionManager()
hybrid_router     = AdaptiveHybridRouter()
workspace_manager = WorkspaceManager(ROOT / 'data' / 'database' / 'workspace.db')
from agent.core.scheduler import ScheduledTaskStore, TaskScheduler
scheduled_task_store = ScheduledTaskStore(ROOT / 'data' / 'database' / 'scheduler.db')


def _run_scheduled_task(task: dict) -> str:
    """Execute a scheduled task prompt through the cloud-completion fallback loop."""
    import asyncio

    from api.routing import _cloud_completion

    async def _run():
        return await _cloud_completion(
            task['prompt'],
            'You are ZEVORA, a scheduled automation assistant. '
            'Answer the scheduled prompt concisely and actionably.',
            require_native_tools=False,
        )

    response = asyncio.run(_run())
    return str(response.get('response', ''))[:4_000]


scheduler = TaskScheduler(scheduled_task_store, _run_scheduled_task)
_PROVIDER_CONFIG_LOCK = asyncio.Lock()


# Re-exported request models and helpers (implementation lives in the api package).
from api.schemas import (  # re-exported for backward compatibility
    AttachmentRequest, AgentActionRequest, TaskRequest, PlanRequest, MCPToolUpdateRequest,
    TerminalSessionRequest, FileWriteRequest, IndexRequest, ProjectCreateRequest,
    ProjectLoadRequest, SettingsUpdateRequest, ChatCreateRequest, ChatMessageRequest,
    ChatRequest, ChatRenameRequest, ChatFeedbackRequest, ApprovalRequest,
    ProviderConfigRequest, ProviderManifestRequest, ProviderAnalysisRequest,
    ProviderTestRequest, ProviderTrustRequest, ProviderEnabledRequest, ProviderExampleRequest,
    LocalModelInstallRequest,
)  # noqa: F401
from api.helpers import (  # re-exported for backward compatibility
    _AGENTIC_LOG_INSTRUCTION, _parse_agentic_response, _atomic_write_text,
    _provider_service_error, _chat_metadata, _sse_frame, _stream_error,
    _utc_timestamp, _failure_reason, _attempt_record,
    _fallback_failure_message, _usage_tokens, _estimated_cost, _model_metadata,
    _flow_status, _action_receipt, _requires_workspace_agent,
)  # noqa: F401


# ── App + lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app):
    # One bounded startup refresh; requests never trigger repeated model discovery.
    await ProviderDiscovery(model_registry).refresh()
    # Start the scheduled-task scheduler; a no-op unless tasks exist.
    scheduler.start()
    yield
    scheduler.stop()

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
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
    allow_headers=['Content-Type', 'X-ZEVORA-Shutdown-Token'],
)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

# ── Lightweight in-process rate limiter ────────────────────────────────────
# Protects expensive endpoints (chat, agent planning, provider calls) from
# runaway client loops. Localhost-first tool: generous budget, sliding window
# per client IP, no external dependency. Health/static endpoints exempt.
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get('ZEVORA_RATE_LIMIT', '60'))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get('ZEVORA_RATE_LIMIT_WINDOW', '60'))
RATE_LIMIT_PATH_PREFIXES = ('/api/chat', '/api/agent')
_rate_limit_events: dict[str, deque] = {}
_rate_limit_lock = Lock()

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




# Names re-exported for backward compatibility (tests, CLI, and external callers
# address these as main.* attributes).
__all__ = [
    'app', 'settings', 'ROOT', 'store', 'workspace_manager', 'hybrid_router',
    'model_registry', 'provider_service', 'mcp_gateway', 'intelligence_engine',
    'skill_registry', 'evolution_engine', 'contribution_queue', 'storage_manager',
    'terminal_sessions', 'local_manager', 'basic_skills', 'router',
    'AttachmentRequest', 'AgentActionRequest', 'TaskRequest', 'PlanRequest',
    'MCPToolUpdateRequest', 'TerminalSessionRequest', 'FileWriteRequest',
    'IndexRequest', 'ProjectCreateRequest', 'ProjectLoadRequest',
    'SettingsUpdateRequest', 'ChatCreateRequest', 'ChatMessageRequest',
    'ChatRequest', 'ChatRenameRequest', 'ChatFeedbackRequest', 'ApprovalRequest',
    'ProviderConfigRequest', 'ProviderManifestRequest', 'ProviderAnalysisRequest',
    'ProviderTestRequest', 'ProviderTrustRequest', 'ProviderEnabledRequest',
    'ProviderExampleRequest', 'LocalModelInstallRequest',
    '_AGENTIC_LOG_INSTRUCTION', '_parse_agentic_response', '_atomic_write_text',
    '_provider_service_error', '_chat_metadata', '_sse_frame', '_stream_error',
    '_utc_timestamp', '_failure_reason', '_attempt_record',
    '_fallback_failure_message', '_usage_tokens', '_estimated_cost',
    '_model_metadata', '_flow_status', '_action_receipt', '_requires_workspace_agent',
    'task', 'plan_agent_actions', 'chat_message', 'regenerate_message',
    'message_feedback', 'chat', 'chat_stream', 'cancel_chat_request',
    '_chat_request', '_execute_chat_request', 'tools', 'update_tool',
    'evolution_status', 'update_provider_config', 'test_builtin_provider',
    '_cloud_completion', '_routing_candidates', '_cloud_candidates',
    '_provider_completion', '_emit_stream_event', '_progress_start',
    '_progress_update', '_progress_finish', '_progress_snapshot',
    '_workflow_record', '_progress_lock', '_progress_events',
    '_stream_event_callback', '_workflow_request_id', '_stream_subscribers',
    '_chat_runs', 'reload_settings', 'get_provider', 'estimate_tokens',
    'local_runtime_status', 'remote_endpoint_status', 'ProviderDiscovery',
    'RATE_LIMIT_MAX_REQUESTS', 'RATE_LIMIT_WINDOW_SECONDS', 'RATE_LIMIT_PATH_PREFIXES',
    '_rate_limit_events', '_rate_limit_lock', '_schedule_shutdown',
    'telegram_status', 'telegram_gateway_heartbeat', 'telegram_gateway_disconnect',
    'gateway_heartbeat', 'gateway_disconnect', '_gateway_state',
    '_routing', '_core_router', '_health_router', '_providers_router',
    '_workspace_router', '_chats_router', '_chatflow_router', '_planning_router',
    '_tasks_router', '_spa_router',
]

def _schedule_shutdown():
    asyncio.get_running_loop().call_later(
        .2, lambda: os.kill(os.getpid(), __import__('signal').SIGINT)
    )


# ── Register routers (they import main back for state) ──────────────────────
from api.orchestrators import task, plan_agent_actions  # noqa: E402,F401
from api import routing as _routing  # noqa: E402,F401

from api.routers import (  # noqa: E402,F401
    core as _core_router,
    health as _health_router,
    providers as _providers_router,
    workspace as _workspace_router,
    chats as _chats_router,
    chatflow as _chatflow_router,
    planning as _planning_router,
    tasks as _tasks_router,
    schedules as _schedules_router,
    telegram as _telegram_router,
    spa as _spa_router,
)

# Re-export endpoint handlers and routing internals so callers (tests, CLI,
# zevora.core) can address them as main.* attributes.
_ = _schedules_router  # referenced so the import is not unused
_ = _telegram_router
from api.routers.telegram import (  # noqa: E402,F401
    telegram_status, telegram_gateway_heartbeat, telegram_gateway_disconnect,
    gateway_heartbeat, gateway_disconnect, _gateway_state,
)  # noqa: F401  re-exported for backward compatibility
from api.routers.chats import chat_message, regenerate_message, message_feedback  # noqa: E402,F401
from api.routers.chatflow import (  # noqa: E402,F401
    chat, chat_stream, cancel_chat_request, _chat_request, _execute_chat_request,
)
from api.routers.workspace import tools, update_tool  # noqa: E402,F401
from api.routers.health import evolution_status  # noqa: E402,F401
from api.routers.providers import update_provider_config, test_builtin_provider  # noqa: E402,F401
from agent.storage.context_economy import estimate_tokens  # noqa: F401
from api.routing import (  # noqa: E402,F401
    _cloud_completion, _routing_candidates, _cloud_candidates, _provider_completion,
)
from api.progress import (  # noqa: F401
    _emit_stream_event, _progress_start, _progress_update, _progress_finish,
    _progress_snapshot, _workflow_record,
)

