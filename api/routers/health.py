"""Health, status, local-model, settings, storage, and maintenance endpoints."""
import asyncio
import json

from fastapi import HTTPException
from pydantic import BaseModel
import main
from agent.config import ROOT
from agent.security.redaction import redact
from agent.storage.cleanup import CleanupManager
from agent.storage.maintenance import MaintenanceScheduler
from zevora.version import __version__

from main import app
from api.schemas import ApprovalRequest, SettingsUpdateRequest
from api.helpers import _atomic_write_text

@app.get('/api/health')
async def health():
    resource = main.local_manager.resource_state()
    configured = [p['provider'] for p in main.ProviderDiscovery(main.model_registry).configured_list()
                  if p['configured'] and p['enabled']]
    return {
        'ok': True, 'status': 'ok', 'service': 'zevora', 'version': __version__,
        'gateway': 'running', 'ready': True,
        'providers_configured': configured,
        'local_resource': resource,
        'local_model': main.local_runtime_status(),
        'semantic_cache_enabled': main.settings.semantic_cache_enabled,
        'main.basic_skills': {
            'enabled': main.settings.basic_skills_enabled,
            'source_available': main.basic_skills.directory.is_dir(),
            'allowed': sorted(main.settings.allowed_basic_skills),
        },
    }
@app.get('/api/stats')
def stats(): return {'today':main.store.usage(), 'resources':main.local_manager.resource_state()}
@app.get('/api/memory')
def memory(): return {'categories':main.store.memory_categories()}
@app.get('/api/intelligence')
def intelligence_stats(): return main.intelligence_engine.stats(main.settings.database_file).__dict__

@app.get('/api/evolution/status')
def evolution_status():
    skills = main.skill_registry.list()
    return {
        'version': __version__,
        'local_intelligence': {
            'runtime': main.settings.active_local_model_profile.runtime,
            'enabled': main.settings.local_model_enabled,
            'package_directory': str(main.settings.local_model_package_dir),
            'configured_model': main.settings.active_local_model_profile.model_id,
            'display_name': main.settings.active_local_model_profile.display_name,
            'repository': main.settings.active_local_model_profile.repository,
            'filename': main.settings.active_local_model_profile.filename,
            'quantization': main.settings.active_local_model_profile.quantization,
            'context_length': main.settings.active_local_model_profile.context_length,
            'deployments': {
                'embedded': main.local_runtime_status(),
                'remote': main.remote_endpoint_status(),
            },
            'resources': {
                'ram_available_mb': resource['ram_available_mb'] if (resource := main.local_manager.resource_state()) else None,
            },
            'installed_packages': main.model_registry.installed_local_packages(),
            'discovered_models': main.local_manager.discover_models(),
            'installation_choices': main.local_manager.installation_choices(),
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
        'evolution': main.evolution_engine.status(),
        'collective_learning': main.contribution_queue.status(),
        'updates': {
            'channel': main.settings.update_channel,
            'manifest_configured': bool(main.settings.update_manifest_url),
            'verification': 'sha256_required',
            'activation': 'staged_atomic_with_rollback',
        },
    }

@app.post('/api/local-intelligence/uninstall')
def uninstall_local_intelligence(body: ApprovalRequest):
    try:
        return main.local_manager.uninstall_package(approved=body.approved)
    except ValueError as error:
        raise HTTPException(400, {
            'code': 'UNINSTALL_PATH_REJECTED', 'message': str(error),
        }) from error


@app.get('/api/local-model/status')
async def local_model_status():
    """Embedded + remote Lexi status with resource state (Phase 17)."""
    from agent.providers.local_provider import LocalProvider
    provider = LocalProvider()
    return {
        'embedded': main.local_runtime_status(),
        'remote': main.remote_endpoint_status(),
        'resources': main.local_manager.resource_state(),
        'model': (await provider.list_models() or [None])[0],
    }


@app.post('/api/local-model/unload')
async def local_model_unload():
    from agent.providers.local_provider import LocalProvider
    return await LocalProvider().unload()


@app.post('/api/local-model/restart')
async def local_model_restart():
    from agent.providers.local_provider import LocalProvider
    return await LocalProvider().restart()


class LocalModelInstallRequest(BaseModel):
    approved: bool = False
    replace: bool = False
    repository: str | None = None
    filename: str | None = None


@app.post('/api/local-model/install')
async def local_model_install(body: LocalModelInstallRequest):
    """Download ONLY the selected GGUF file (never the whole repository).

    Requires explicit ``approved=true``. Never silently overwrites an existing
    model file; pass ``replace=true`` for explicit replacement.
    """
    if not body.approved:
        raise HTTPException(400, {
            'code': 'INSTALL_APPROVAL_REQUIRED',
            'message': 'Set approved=true to download the Lexi GGUF file.',
        })
    try:
        return await asyncio.to_thread(
            main.local_manager.install_model,
            repository=body.repository,
            filename=body.filename,
            replace=body.replace,
        )
    except Exception as error:
        raise HTTPException(400, {
            'code': type(error).__name__.upper(),
            'message': redact(str(error))[:300],
        }) from error
@app.get('/api/settings')
def ui_settings():
    return {
        'gateway_url': 'http://127.0.0.1:7432',
        'routing_mode': main.settings.routing_mode,
        'cloud_fallback': main.settings.cloud_fallback,
        'cost_optimization': main.settings.cost_optimization,
    }
@app.post('/api/settings')
def update_ui_settings(body:SettingsUpdateRequest):
    if body.routing_mode and body.routing_mode.upper() not in {'AUTO','LOCAL_ONLY','REMOTE_LOCAL_ONLY','CLOUD_ONLY'}:
        raise HTTPException(400,'routing_mode must be AUTO, LOCAL_ONLY, REMOTE_LOCAL_ONLY, or CLOUD_ONLY')
    config_file=ROOT/'config'/'ui_main.settings.json'; config_file.parent.mkdir(parents=True,exist_ok=True)
    try: saved=json.loads(config_file.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): saved={}
    if body.routing_mode is not None: saved['routing_mode']=body.routing_mode.upper()
    if body.cloud_fallback is not None: saved['cloud_fallback']=body.cloud_fallback
    if body.cost_optimization is not None: saved['cost_optimization']=body.cost_optimization
    try:
        _atomic_write_text(config_file, json.dumps(saved, indent=2) + '\n')
        main.reload_settings()
    except OSError as error:
        raise HTTPException(500, {
            'code': 'SETTINGS_WRITE_FAILED',
            'message': f'Unable to persist settings: {type(error).__name__}',
        }) from error
    return {'ok':True,**saved}
@app.get('/api/storage')
def storage(): return main.storage_manager.report()
@app.post('/api/maintenance/cleanup-plan')
def cleanup_plan(): return CleanupManager(ROOT).run(dry_run=True)
@app.post('/api/maintenance/intelligence')
def intelligence_cleanup(execute: bool = False):
    store_result = main.store.retention(dry_run=not execute)
    knowledge_result = {'knowledge_removed': 0}
    if execute:
        knowledge_result = main.intelligence_engine.prune()
    else:
        with main.intelligence_engine.connection() as conn:
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
