import json

import pytest

from zevora.cli import main


def test_version_command(capsys):
    main(['version'])
    assert 'Zero-External Vendor Oriented Reasoning Agent' in capsys.readouterr().out


def test_help_command(capsys):
    main(['help'])
    output = capsys.readouterr().out
    assert 'background' in output
    assert 'provider' in output


class FakeProviderService:
    instances = []

    def __init__(self):
        self.calls = []
        self.__class__.instances.append(self)

    def list(self):
        self.calls.append(('list',))
        return [{'provider_id': 'example', 'credential': {'configured': True, 'masked': '***'}}]

    def save(self, payload, *, script=None):
        self.calls.append(('save', payload, script))
        return payload

    def import_manifest(self, payload, *, script=None):
        self.calls.append(('import', payload, script))
        return payload

    def export_manifest(self, provider_id):
        self.calls.append(('export', provider_id))
        return {'provider_id': provider_id, 'credential': {'source': 'environment', 'name': 'TEST_KEY'}}

    def remove(self, provider_id):
        self.calls.append(('remove', provider_id))
        return True

    async def test(self, provider_id, *, runtime_approved=False):
        self.calls.append(('test', provider_id, runtime_approved))
        return {'provider': provider_id, 'success': True}


@pytest.fixture
def provider_service(monkeypatch):
    FakeProviderService.instances.clear()
    monkeypatch.setattr('zevora.cli.ProviderService', FakeProviderService)
    return FakeProviderService


def test_provider_list_is_json_and_secret_free(provider_service, capsys):
    main(['provider', 'list'])
    result = json.loads(capsys.readouterr().out)
    assert result[0]['provider_id'] == 'example'
    assert 'value' not in result[0]['credential']


def test_provider_add_builds_manifest(provider_service, capsys):
    main([
        'provider', 'add', '--id', 'example', '--name', 'Example',
        '--protocol', 'openai-compatible', '--base-url', 'https://example.test/v1',
        '--model', 'example-model', '--credential-env', 'EXAMPLE_API_KEY',
    ])
    service = provider_service.instances[-1]
    payload = service.calls[0][1]
    assert payload['provider_id'] == 'example'
    assert payload['credential']['name'] == 'EXAMPLE_API_KEY'
    assert 'credential_value' not in payload
    assert json.loads(capsys.readouterr().out)['default_model'] == 'example-model'


def test_provider_import_and_export(provider_service, tmp_path, capsys):
    source = tmp_path / 'provider.json'
    source.write_text(json.dumps({'provider_id': 'imported'}), encoding='utf-8')
    output = tmp_path / 'exported.json'
    main(['provider', 'import', str(source)])
    capsys.readouterr()
    main(['provider', 'export', 'imported', '--output', str(output)])
    report = json.loads(capsys.readouterr().out)
    assert report['secret_free'] is True
    assert json.loads(output.read_text(encoding='utf-8'))['provider_id'] == 'imported'


def test_provider_test_and_remove(provider_service, capsys):
    main(['provider', 'test', 'example'])
    assert json.loads(capsys.readouterr().out)['success'] is True
    main(['provider', 'remove', 'example'])
    assert json.loads(capsys.readouterr().out)['removed'] is True


def test_runtime_test_requires_explicit_approval(provider_service):
    with pytest.raises(SystemExit):
        main(['provider', 'runtime-test', 'runtime-provider'])


def test_runtime_test_passes_approval(provider_service, capsys):
    main(['provider', 'runtime-test', 'runtime-provider', '--approve'])
    service = provider_service.instances[-1]
    assert service.calls == [('test', 'runtime-provider', True)]
    assert json.loads(capsys.readouterr().out)['success'] is True
