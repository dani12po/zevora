from pathlib import Path
from ..config import settings
from .storage_monitor import StorageMonitor

CATEGORIES=('raw','processed','curated','memory','cache','embeddings','datasets','archive','evaluation','logs','models')

def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob('*') if item.is_file()) if path.exists() else 0

class StorageManager:
    def __init__(self, root: Path): self.root=root; self.monitor=StorageMonitor(root)
    def category_path(self, name):
        return self.root / ('logs' if name=='logs' else 'data') / name if name not in ('logs','models') else self.root / name
    def report(self):
        snapshot=self.monitor.snapshot(); categories={name:directory_size(self.category_path(name)) for name in CATEGORIES}
        managed=sum(categories.values()); limit=settings.max_total_storage_gb*1024**3
        state='normal' if managed < settings.warning_storage_gb*1024**3 else ('warning' if managed < settings.critical_storage_gb*1024**3 else 'critical')
        return {'managed_bytes':managed,'budget_bytes':limit,'disk_free_bytes':snapshot.free_bytes,'disk_total_bytes':snapshot.total_bytes,'state':state,'categories':categories,'heavy_maintenance_allowed':self.monitor.heavy_work_allowed()}
