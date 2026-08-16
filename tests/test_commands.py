from zevora.commands.status import status
def test_status_is_safe_without_provider_keys():
    report=status()
    assert report['agent_core']=='READY' and 'ram_available_mb' in report
