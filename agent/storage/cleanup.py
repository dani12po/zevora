import logging
from pathlib import Path

from ..config import settings
from .retention import expired_cache_files, expired_files
from .storage_manager import StorageManager

logger = logging.getLogger(__name__)


class CleanupManager:
    """Plan and execute cleanup without touching persistent or curated data."""

    def __init__(self, root: Path):
        self.root = root
        self.storage = StorageManager(root)

    def plan(self):
        candidates = []
        candidates += expired_cache_files(
            self.root / "data" / "cache", settings.cache_default_ttl_hours / 24
        )
        candidates += expired_files(self.root / "data" / "raw", settings.raw_retention_days)
        candidates += expired_files(self.root / "logs" / "active", settings.log_retention_days)
        return candidates

    def run(self, dry_run=True):
        plan = self.plan()
        deleted = []
        failures = []
        if not dry_run:
            for item in plan:
                try:
                    item.path.unlink(missing_ok=True)
                    deleted.append(str(item.path))
                except OSError as error:
                    logger.warning("Unable to delete cleanup candidate %s: %s", item.path, error)
                    failures.append({"path": str(item.path), "error": str(error)})
        saved = sum(item.size_bytes for item in plan if dry_run or str(item.path) in deleted)
        return {
            "dry_run": dry_run,
            "would_delete": [
                {"path": str(item.path), "reason": item.reason, "size_bytes": item.size_bytes}
                for item in plan
            ],
            "deleted": deleted,
            "failures": failures,
            "estimated_bytes_saved": saved,
            "storage": self.storage.report(),
        }
