from agent.storage.storage_manager import StorageManager
from agent.storage.maintenance import MaintenanceScheduler
def test_storage_report_has_safe_categories(tmp_path):
    report=StorageManager(tmp_path).report()
    assert report['managed_bytes']==0 and 'curated' in report['categories'] and report['budget_bytes']>0

def test_maintenance_is_plan_only(tmp_path):
    plan=MaintenanceScheduler(tmp_path).plan()
    assert 'weekly' in plan['schedule'] and plan['daily_cleanup_preview']['dry_run'] is True
