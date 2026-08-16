from pathlib import Path
from ..config import settings
from .retention import expired_files
from .storage_manager import StorageManager

class CleanupManager:
    """Plans safe cleanup. Curated, dataset, project, and model paths are never candidates."""
    def __init__(self, root: Path): self.root=root; self.storage=StorageManager(root)
    def plan(self):
        candidates=[]
        candidates += expired_files(self.root/'data'/'cache', settings.cache_default_ttl_hours/24)
        candidates += expired_files(self.root/'data'/'raw', settings.raw_retention_days)
        candidates += expired_files(self.root/'logs'/'active', settings.log_retention_days)
        return candidates
    def run(self, dry_run=True):
        plan=self.plan(); saved=sum(item.size_bytes for item in plan)
        if not dry_run:
            for item in plan: item.path.unlink(missing_ok=True)
        return {'dry_run':dry_run,'would_delete':[{'path':str(x.path),'reason':x.reason,'size_bytes':x.size_bytes} for x in plan],'estimated_bytes_saved':saved,'storage':self.storage.report()}
