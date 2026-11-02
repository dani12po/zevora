from zevora.gateway import status
def test_gateway_status_is_lightweight():
    current=status()
    assert 'running' in current and 'port' in current
