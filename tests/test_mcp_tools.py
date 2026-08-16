import json

import pytest

import main
from agent.tools.mcp_gateway import LocalMCPGateway

def test_create_project_requires_approval(tmp_path):
    gateway=LocalMCPGateway(tmp_path)
    result=gateway.execute('create_project',{'name':'my-dashboard'})
    assert result.approval_required and not (tmp_path/'my-dashboard').exists()

def test_create_project_is_rooted_and_safe(tmp_path):
    gateway=LocalMCPGateway(tmp_path)
    result=gateway.execute('create_project',{'name':'my-dashboard'},approved=True)
    assert result.ok and (tmp_path/'my-dashboard').is_dir()
    assert not gateway.execute('create_project',{'name':'../outside'},approved=True).ok


def test_write_and_delete_require_approval(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    assert gateway.execute('write_file', {'path': 'note.txt', 'content': 'hello'}).approval_required
    written = gateway.execute('write_file', {'path': 'note.txt', 'content': 'hello'}, approved=True)
    assert written.ok and (tmp_path / 'note.txt').read_text() == 'hello'
    deleted = gateway.execute('delete_file', {'path': 'note.txt'}, approved=True)
    assert deleted.ok and not (tmp_path / 'note.txt').exists()


def test_terminal_is_allowlisted_and_rooted(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    denied = gateway.execute('terminal', {'command': 'whoami'}, approved=True)
    assert not denied.ok
    allowed = gateway.execute(
        'execute_command', {'command': 'python --version'}, approved=True
    )
    assert allowed.ok
    assert allowed.output['exit_code'] == 0
    assert allowed.output['risk'] == 'SAFE'


def test_git_allows_read_only_operations(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    assert gateway.execute('git', {'operation': 'status'}, approved=True).tool == 'git'
    denied = gateway.execute('git', {'operation': 'push'}, approved=True)
    assert not denied.ok


def test_complete_filesystem_surface_is_real_and_workspace_scoped(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    created = gateway.execute(
        'create_file', {'path': 'src/note.txt', 'content': 'Hello ZEVORA'}, approved=True
    )
    assert created.ok and (tmp_path / 'src' / 'note.txt').is_file()

    listed = gateway.execute('list_directory', {'path': 'src'})
    assert listed.output[0]['path'] == 'src/note.txt'
    assert gateway.execute('file_exists', {'path': 'src/note.txt'}).output['exists']
    assert gateway.execute('get_file_info', {'path': 'src/note.txt'}).output['size_bytes'] == 12

    edited = gateway.execute('edit_file', {
        'path': 'src/note.txt', 'old_text': 'ZEVORA', 'new_text': 'World'
    }, approved=True)
    assert edited.ok and (tmp_path / 'src' / 'note.txt').read_text() == 'Hello World'

    copied = gateway.execute('copy_file', {
        'source': 'src/note.txt', 'destination': 'src/copy.txt'
    }, approved=True)
    moved = gateway.execute('move_file', {
        'source': 'src/copy.txt', 'destination': 'archive/copy.txt'
    }, approved=True)
    assert copied.ok and moved.ok and (tmp_path / 'archive' / 'copy.txt').is_file()

    escaped = gateway.execute('write_file', {
        'path': '../outside.txt', 'content': 'blocked'
    }, approved=True)
    assert not escaped.ok or not (tmp_path.parent / 'outside.txt').exists()


def test_read_file_is_chunked_and_search_excludes_noise(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.ts').write_text('abcdefghij', encoding='utf-8')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'hidden.ts').write_text('ignored', encoding='utf-8')

    first = gateway.execute('read_file', {'path': 'src/main.ts', 'limit': 4})
    second = gateway.execute('read_file', {
        'path': 'src/main.ts', 'offset': first.output['next_offset'], 'limit': 6
    })
    assert first.output['content'] == 'abcd'
    assert second.output['content'] == 'efghij' and second.output['next_offset'] is None

    found = gateway.execute('search_files', {'pattern': '*.ts'}).output
    assert found == ['src/main.ts']


def test_edit_requires_one_exact_match_and_mutations_require_approval(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    (tmp_path / 'note.txt').write_text('same same', encoding='utf-8')
    ambiguous = gateway.execute('edit_file', {
        'path': 'note.txt', 'old_text': 'same', 'new_text': 'changed'
    }, approved=True)
    assert not ambiguous.ok and (tmp_path / 'note.txt').read_text() == 'same same'

    pending = gateway.execute('delete_file', {'path': 'note.txt'})
    assert pending.approval_required and (tmp_path / 'note.txt').exists()


def test_command_risk_policy_requires_approval_or_rejects(tmp_path):
    gateway = LocalMCPGateway(tmp_path)
    restricted = gateway.execute('execute_command', {'command': 'git checkout main'})
    assert restricted.approval_required
    assert restricted.output['risk'] == 'RESTRICTED'

    dangerous = gateway.execute('execute_command', {'command': 'format C:'}, approved=True)
    assert not dangerous.ok
    assert 'allowlist' in str(dangerous.output).lower() or 'registered' not in str(dangerous.output).lower()

    chained = gateway.execute('execute_command', {'command': 'python --version && whoami'}, approved=True)
    assert not chained.ok


def test_command_policy_rejects_arbitrary_python_modules(tmp_path):
    gateway = LocalMCPGateway(tmp_path)

    result = gateway.execute('execute_command', {'command': 'python -m http.server'}, approved=True)

    assert not result.ok
    assert 'allowlist' in str(result.output).lower()


def test_legacy_tool_config_is_migrated_on_read(tmp_path):
    config_path = tmp_path / 'mcp.json'
    config_path.write_text(json.dumps({
        'permissions': 'workspace-scoped',
        'tools': ['read_file', 'execute_command'],
        'enabled': {'read_file': True, 'execute_command': False},
    }), encoding='utf-8')

    gateway = LocalMCPGateway(tmp_path, config_path)

    assert 'read_file' in gateway.enabled_tools()
    assert 'execute_command' not in gateway.enabled_tools()
    migrated = json.loads(config_path.read_text(encoding='utf-8'))
    assert migrated == {
        'permissions': 'workspace-scoped',
        'disabled': {'execute_command': True},
    }
    assert not config_path.with_suffix('.json.tmp').exists()


def test_tool_enabled_state_persists_and_blocks_canonical_alias(tmp_path):
    config_path = tmp_path / 'mcp.json'
    # New behaviour: all tools are ON by default — no initial config needed.
    gateway = LocalMCPGateway(tmp_path, config_path)

    updated = gateway.set_tool_enabled('terminal', False)
    assert updated == {
        'name': 'execute_command', 'permission': 'allow', 'enabled': False,
    }
    assert not gateway.execute('execute_command', {'command': 'python --version'}).ok
    assert 'disabled' in gateway.execute('terminal', {'command': 'python --version'}).output.lower()

    reloaded = LocalMCPGateway(tmp_path, config_path)
    assert 'execute_command' not in reloaded.enabled_tools()
    reloaded.set_tool_enabled('execute_command', True)
    assert reloaded.execute(
        'execute_command', {'command': 'python --version'}, approved=True
    ).ok


def test_disabled_mutation_stays_approval_gated_after_reenable(tmp_path):
    config_path = tmp_path / 'mcp.json'
    gateway = LocalMCPGateway(tmp_path, config_path)
    gateway.set_tool_enabled('write_file', False)
    disabled = gateway.execute('write_file', {'path': 'note.txt', 'content': 'blocked'}, approved=True)
    assert not disabled.ok and not (tmp_path / 'note.txt').exists()

    gateway.set_tool_enabled('write_file', True)
    pending = gateway.execute('write_file', {'path': 'note.txt', 'content': 'pending'})
    assert pending.approval_required and not (tmp_path / 'note.txt').exists()


def test_tool_update_api_persists_and_rejects_unknown_tool(tmp_path, monkeypatch):
    gateway = LocalMCPGateway(tmp_path, tmp_path / 'mcp.json')
    monkeypatch.setattr(main, 'mcp_gateway', gateway)

    updated = main.update_tool('read_file', main.MCPToolUpdateRequest(enabled=False))
    assert updated['enabled'] is False
    assert main.tools()[1] == {
        'name': 'read_file', 'permission': 'allow', 'enabled': False,
    }
    with pytest.raises(main.HTTPException) as caught:
        main.update_tool('not_registered', main.MCPToolUpdateRequest(enabled=False))
    assert caught.value.status_code == 404
    assert caught.value.detail['code'] == 'MCP_TOOL_NOT_FOUND'
