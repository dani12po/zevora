from agent.storage.storage_manager import StorageManager
from agent.storage.maintenance import MaintenanceScheduler
from agent.storage.cleanup import CleanupManager
def test_storage_report_has_safe_categories(tmp_path):
    report=StorageManager(tmp_path).report()
    assert report['managed_bytes']==0 and 'curated' in report['categories'] and report['budget_bytes']>0

def test_maintenance_is_plan_only(tmp_path):
    plan=MaintenanceScheduler(tmp_path).plan()
    assert 'weekly' in plan['schedule'] and plan['daily_cleanup_preview']['dry_run'] is True


def test_cleanup_removes_ephemeral_cache_but_preserves_provider_config(tmp_path):
    cache = tmp_path / "data" / "cache"
    ephemeral = cache / "ephemeral_cache" / "response.json"
    provider = cache / "provider_config_cache" / "local-provider.json"
    ephemeral.parent.mkdir(parents=True)
    provider.parent.mkdir(parents=True)
    ephemeral.write_text("old response")
    provider.write_text("provider path and credential reference")

    import os
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(ephemeral, (old, old))
    os.utime(provider, (old, old))

    result = CleanupManager(tmp_path).run(dry_run=False)

    assert not ephemeral.exists()
    assert provider.exists()
    assert str(ephemeral) in result["deleted"]
    assert not result["failures"]
