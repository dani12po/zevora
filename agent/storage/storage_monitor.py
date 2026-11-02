from dataclasses import dataclass
from pathlib import Path
import shutil
import psutil

@dataclass(frozen=True)
class StorageSnapshot:
    used_bytes: int; free_bytes: int; total_bytes: int; cpu_percent: float; ram_percent: float

class StorageMonitor:
    def __init__(self, root: Path): self.root = root
    def snapshot(self):
        disk=shutil.disk_usage(self.root); mem=psutil.virtual_memory()
        return StorageSnapshot(disk.used,disk.free,disk.total,psutil.cpu_percent(interval=None),mem.percent)
    def heavy_work_allowed(self):
        s=self.snapshot()
        return s.ram_percent < 80 and s.cpu_percent < 80
