import pytest

from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.providers.ssrf import assert_provider_base_url


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
    'ftp://example.com',
    'file:///etc/passwd',
    'http:///no-host',
])
def test_abusive_base_urls_rejected(bad):
    with pytest.raises(ValueError):
        assert_provider_base_url(bad)


def test_openai_compatible_provider_blocks_loopback_cloud_endpoint():
    with pytest.raises(ValueError):
        OpenAICompatibleProvider('custom', 'key', 'http://127.0.0.1:8000', 'model')


def test_openai_compatible_provider_accepts_public_endpoint():
    provider = OpenAICompatibleProvider('custom', 'key', 'https://api.example.com/v1', 'model')
    assert provider.base_url == 'https://api.example.com/v1'
    assert provider.api_key == 'key'
