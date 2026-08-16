from agent.config import ROOT, settings
from agent.memory.store import Store
from agent.models.manager import LocalIntelligenceManager
from agent.models.registry import ModelRegistry
from agent.storage.storage_manager import StorageManager

def status():
    store=Store(settings.database_file); resources=LocalIntelligenceManager().resource_state(); storage=StorageManager(ROOT).report(); models=ModelRegistry(ROOT/'data'/'database'/'model_registry.db').list()
    return {'agent_core':'READY','memory':'ENABLED' if settings.memory_enabled else 'DISABLED','semantic_cache':'ENABLED' if settings.semantic_cache_enabled else 'DISABLED','experience':'ENABLED' if settings.experience_logging else 'DISABLED','storage_manager':'READY','routing':'AUTO','ram_available_mb':resources['ram_available_mb'],'storage_root':str(ROOT),'managed_storage_bytes':storage['managed_bytes'],'cache_entries':_count(store,'exact_cache'),'memory_entries':_count(store,'memories'),'models':len(models)}
def _count(store,table):
    with store.connection() as conn: return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
