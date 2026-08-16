from pathlib import Path
from .cleanup import CleanupManager
from .storage_manager import StorageManager

class MaintenanceScheduler:
    """A scheduler plan, deliberately inert until an operator schedules it."""
    SCHEDULE={'daily':['cache_cleanup','log_rotation','temporary_cleanup'],'weekly':['experience_deduplication','memory_consolidation','archive_compression'],'monthly':['dataset_curation','stale_embedding_cleanup','archive_optimization']}
    def __init__(self, root: Path): self.root=root; self.storage=StorageManager(root); self.cleanup=CleanupManager(root)
    def plan(self):
        report=self.storage.report(); heavy=report['heavy_maintenance_allowed'] and report['state']=='normal'
        return {'schedule':self.SCHEDULE,'heavy_work_allowed':heavy,'blocked_heavy_jobs':[] if heavy else self.SCHEDULE['weekly']+self.SCHEDULE['monthly'],'daily_cleanup_preview':self.cleanup.run(dry_run=True)}
