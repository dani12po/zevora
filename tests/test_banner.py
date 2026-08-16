from zevora.banner import banner
def test_banner_has_full_name():
    output=banner()
    assert 'Z E V O R A' in output and 'Zero-External Vendor Oriented Reasoning Agent' in output
