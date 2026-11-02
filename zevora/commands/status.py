from agent.config import ROOT, settings
from agent.evolution.contribution import ContributionQueue
from agent.evolution.engine import EvolutionEngine
from agent.memory.store import Store
from agent.models.manager import LocalIntelligenceManager
from agent.models.registry import ModelRegistry
from agent.skills.registry import SkillRegistry
from agent.storage.storage_manager import StorageManager


def status():
    store = Store(settings.database_file)
    manager = LocalIntelligenceManager()
    resources = manager.resource_state()
    storage = StorageManager(ROOT).report()
    registry = ModelRegistry(settings.local_model_registry_file)
    models = registry.list()
    skills = SkillRegistry()
    return {
        'agent_core': 'READY',
        'memory': 'ENABLED' if settings.memory_enabled else 'DISABLED',
        'semantic_cache': 'ENABLED' if settings.semantic_cache_enabled else 'DISABLED',
        'experience': 'ENABLED' if settings.experience_logging else 'DISABLED',
        'storage_manager': 'READY',
        'routing': settings.routing_mode,
        'ram_available_mb': resources['ram_available_mb'],
        'storage_root': str(ROOT),
        'managed_storage_bytes': storage['managed_bytes'],
        'cache_entries': _count(store, 'exact_cache'),
        'memory_entries': _count(store, 'memories'),
        'models': len(models),
        'installed_local_packages': len(registry.installed_local_packages()),
        'discovered_local_models': len(resources['local_models']),
        'local_runtime': settings.local_model_runtime,
        'skills': len(skills.list()),
        'evolution': EvolutionEngine(store, skills).status(),
        'collective_learning': ContributionQueue(store).status(),
        'updates': {
            'channel': settings.update_channel,
            'manifest_configured': bool(settings.update_manifest_url),
            'verification': 'sha256_required',
        },
    }
def _count(store, table):
    with store.connection() as conn:
        return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
