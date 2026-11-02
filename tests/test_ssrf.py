import pytest

from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.ssrf import (
    assert_local_endpoint_url,
    assert_provider_base_url,
    is_metadata_host,
)


def test_public_https_base_url_accepts():
    assert assert_provider_base_url('https://api.openai.com/v1') == 'https://api.openai.com/v1'
    assert assert_provider_base_url('http://api.example.com') == 'http://api.example.com'


@pytest.mark.parametrize('bad', [
    'http://169.254.169.254/latest/meta-data',
    'http://169.254.100.10/',
    'http://127.0.0.1:8000',
    'http://localhost:11434',
    'http://metadata.google.internal',
    'http://metadata',
    'http://10.0.0.5/v1',
    'http://192.168.1.10:8000',
    'http://172.16.0.9/',
    'http://100.64.0.1/',
    'http://[::1]:8000/',
    'http://[fc00::1]/',
    'http://2130706433/',
    'http://0x7f.0.0.1/',
    'http://0177.0.0.1/',
    'ftp://example.com',
    'file:///etc/passwd',
    'http:///no-host',
])
def test_abusive_base_urls_rejected(bad):
    with pytest.raises(ValueError):
        assert_provider_base_url(bad)


def test_local_endpoint_allows_loopback_and_lan_but_not_metadata():
    assert assert_local_endpoint_url('http://127.0.0.1:11434') == 'http://127.0.0.1:11434'
    assert assert_local_endpoint_url('http://192.168.1.20:8080/v1')
    with pytest.raises(ValueError):
        assert_local_endpoint_url('http://169.254.169.254/')
    with pytest.raises(ValueError):
        assert_local_endpoint_url('http://metadata.google.internal/')
    with pytest.raises(ValueError):
        assert_local_endpoint_url('ftp://192.168.1.20/')
    assert is_metadata_host('169.254.169.254')
    assert is_metadata_host('2130706433') is False  # loopback, not metadata range edge
    assert is_metadata_host('2852039166')  # 169.254.169.254 as integer


def test_openai_compatible_provider_blocks_loopback_cloud_endpoint():
    with pytest.raises(ValueError):
        OpenAICompatibleProvider('custom', 'key', 'http://127.0.0.1:8000', 'model')


def test_openai_compatible_provider_accepts_public_endpoint():
    provider = OpenAICompatibleProvider('custom', 'key', 'https://api.example.com/v1', 'model')
    assert provider.base_url == 'https://api.example.com/v1'
    assert provider.api_key == 'key'
