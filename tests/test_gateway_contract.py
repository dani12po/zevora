import asyncio
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from agent.core.workspace import WorkspaceManager
from zevora import core

def test_api_health_contract():
    client = TestClient(main.app)
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert body['service'] == 'zevora'
    assert body['gateway'] == 'running'
    assert body['ok'] is True
    # Local runtime status replaces the old Ollama flag and remains lazy.
    assert 'ollama_available' not in body
    assert 'local_resource' in body
    assert 'local_model' in body
    assert {'configured', 'loaded', 'process_rss_mb'} <= set(body['local_model'])
    assert 'local_model' in body['local_resource']

def test_shutdown_requires_controller_token(monkeypatch):
    scheduled = []

    monkeypatch.setenv('ZEVORA_SHUTDOWN_TOKEN', 'controller-secret')
    monkeypatch.setattr(main, '_schedule_shutdown', lambda: scheduled.append(True))
    client = TestClient(main.app)

    assert client.post('/shutdown').status_code == 403
    assert client.post(
        '/shutdown', headers={'X-ZEVORA-Shutdown-Token': 'wrong'}
    ).status_code == 403

    response = client.post(
        '/shutdown',
        headers={'X-ZEVORA-Shutdown-Token': 'controller-secret'},
    )
    assert response.status_code == 200
    assert response.json() == {'status': 'stopping'}
    assert scheduled == [True]


def test_core_import_does_not_depend_on_cwd(monkeypatch, tmp_path):
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert str(core.ROOT) in __import__('sys').path or Path(core.ROOT).is_dir()
    finally:
        os.chdir(original)

def test_chat_contract_uses_existing_task_engine(monkeypatch):
    chat = main.workspace_manager.create_chat('New chat')
    async def fake_task(request):
        return {
            'response': 'real-core-result', 'route': 'CLOUD', 'reason': 'BEST_CLOUD_MATCH',
            'provider': 'openai', 'model': 'gpt-4o-mini', 'tools': [], 'quality_score': .9
        }
    monkeypatch.setattr(main, 'task', fake_task)
    result = asyncio.run(main.chat(main.ChatRequest(message='hello', conversation_id=chat['id'])))
    assert result['ok'] is True
    assert result['response'] == 'real-core-result'
    assert result['conversation_id'] == chat['id']
    assert result['request_id'].startswith('zv-')

def test_chat_connects_existing_conversation_to_selected_project(monkeypatch, tmp_path):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    root.mkdir()
    project = manager.load(root)
    chat = manager.create_chat('New chat')
    captured = {}

    async def fake_task(request):
        captured['project'] = request.project
        return {
            'response': 'connected', 'route': 'CLOUD', 'reason': 'BEST_CLOUD_MATCH',
            'provider': 'openai', 'model': 'test-model', 'tools': [], 'quality_score': .9,
        }

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'task', fake_task)
    asyncio.run(main.chat(main.ChatRequest(
        message='buat file html', conversation_id=chat['id'], project_id=project['id'],
    )))

    assert manager.get_chat(chat['id'])['project_id'] == project['id']
    assert captured['project'] == str(root.resolve())


def test_chat_failure_does_not_persist_half_exchange(monkeypatch, tmp_path):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    chat = manager.create_chat('New chat')

    async def failed_task(_request):
        raise main.HTTPException(503, {'code': 'AI_EXECUTION_ERROR', 'message': 'Provider unavailable'})

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'task', failed_task)
    try:
        asyncio.run(main.chat(main.ChatRequest(message='retry me', conversation_id=chat['id'])))
    except main.HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError('Expected the simulated provider failure')
    assert manager.get_chat(chat['id'])['messages'] == []


def test_chat_success_persists_complete_exchange(monkeypatch, tmp_path):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    chat = manager.create_chat('New chat')

    async def fake_task(_request):
        return {
            'response': 'done', 'route': 'CLOUD', 'reason': 'BEST_CLOUD_MATCH',
            'provider': 'openai', 'model': 'test-model', 'tools': [], 'quality_score': .9,
        }

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'task', fake_task)
    asyncio.run(main.chat(main.ChatRequest(message='hello', conversation_id=chat['id'])))
    messages = manager.get_chat(chat['id'])['messages']
    assert [(item['role'], item['content']) for item in messages] == [
        ('user', 'hello'), ('assistant', 'done'),
    ]


def test_chat_forwards_actions_and_persists_safe_trace_metadata(monkeypatch, tmp_path):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    project = manager.load(tmp_path)
    chat = manager.create_chat('New chat', project['id'])
    captured = {}

    async def fake_task(request):
        captured['request'] = request
        return {
            'response': 'inspected', 'route': 'CLOUD', 'reason': 'BEST_CLOUD_MATCH',
            'provider': 'openai', 'model': 'test-model', 'tools': ['read_file'],
            'quality_score': .9, 'estimated_cost': .001, 'context_hash': 'abc123',
            'project_files': ['main.py'], 'execution_ms': 12,
            'attachments': [{'name': 'notes.txt', 'kind': 'text'}],
            'agent_trace': {'stages': [{'stage': 'ACT', 'status': 'completed'}],
                            'observations': [], 'pending_approvals': [], 'verified': None},
        }

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'task', fake_task)
    request = main.ChatRequest(
        message='inspect it', conversation_id=chat['id'], project_id=project['id'],
        attachments=[main.AttachmentRequest(
            name='notes.txt', media_type='text/plain', data_base64='c2VjcmV0'
        )],
        actions=[main.AgentActionRequest(
            tool='read_file', arguments={'path': 'main.py'}, purpose='Inspect source'
        )],
    )
    asyncio.run(main.chat(request))

    assert captured['request'].actions[0].tool == 'read_file'
    assert captured['request'].attachments[0].data_base64 == 'c2VjcmV0'
    metadata = manager.get_chat(chat['id'])['messages'][-1]['metadata']
    assert 'agent_trace' in metadata and 'estimated_cost' in metadata
    assert 'c2VjcmV0' not in metadata
    assert 'Inspect source' not in metadata


def test_api_error_contract_is_json_and_gateway_shaped(monkeypatch):
    async def unavailable(_request):
        raise main.HTTPException(503, 'No capable cloud model is available')

    monkeypatch.setattr(main, 'task', unavailable)
    client = TestClient(main.app)
    response = client.post('/api/chat', json={'message': 'no configured model'})
    assert response.status_code == 503
    body = response.json()
    assert body['ok'] is False
    assert body['error']['code'] == 'AI_EXECUTION_ERROR'
    # Error message must NOT contain API key hints or internal paths
    assert 'api_key' not in body['error']['message'].lower()
    assert 'ollama' not in body['error']['message'].lower()

def test_api_intelligence_contract():
    client = TestClient(main.app)
    response = client.get('/api/intelligence')
    assert response.status_code == 200
    body = response.json()
    assert 'memory_count' in body
    assert 'knowledge_count' in body
    assert 'cache_hit_rate' in body
    assert 'api_calls_avoided' in body


def test_filesystem_endpoints_preserve_gateway_contract(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    (root / 'src').mkdir(parents=True)
    (root / 'src' / 'main.py').write_text('print("ok")', encoding='utf-8')
    (root / '.git').mkdir()
    project = manager.load(root)
    monkeypatch.setattr(main, 'workspace_manager', manager)
    client = TestClient(main.app)

    tree_response = client.get('/api/filesystem/tree', params={'project_id': project['id']})
    assert tree_response.status_code == 200
    tree = tree_response.json()['tree']
    assert tree == [{
        'name': 'src', 'path': 'src', 'type': 'dir',
        'children': [{'name': 'main.py', 'path': 'src/main.py', 'type': 'file'}],
    }]

    listing = client.get(f"/api/projects/{project['id']}/files").json()['entries']
    assert listing == [{'name': '.git', 'path': '.git', 'type': 'directory'},
                       {'name': 'src', 'path': 'src', 'type': 'directory'}]

    preview = client.get('/api/filesystem/file', params={
        'project_id': project['id'], 'path': 'src/main.py',
    })
    assert preview.status_code == 200
    assert preview.json() == {
        'path': 'src/main.py', 'content': 'print("ok")', 'offset': 0,
        'bytes_read': 11, 'next_offset': None, 'truncated': False,
    }

    project_read = client.get(f"/api/projects/{project['id']}/files/read", params={
        'path': 'src/main.py',
    })
    assert project_read.json()['content'] == 'print("ok")'
    assert project_read.json()['next_offset'] is None


def test_filesystem_endpoint_blocks_path_escape(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    root.mkdir()
    project = manager.load(root)
    (tmp_path / 'outside.txt').write_text('secret', encoding='utf-8')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    response = TestClient(main.app).get('/api/filesystem/file', params={
        'project_id': project['id'], 'path': '../outside.txt',
    })

    assert response.status_code == 400
    assert 'outside' not in str(response.json()).lower() or 'secret' not in str(response.json())


def test_request_validation_errors_use_gateway_json_contract():
    client = TestClient(main.app)

    responses = [
        client.get('/api/chats', params={'limit': 0}),
        client.get('/api/usage/history', params={'days': 366}),
        client.get('/api/route', params={'prompt': 'x' * 20_001}),
        client.get('/api/filesystem/file', params={'project_id': 1, 'path': ''}),
        client.post('/api/chat', json={'message': 'x' * 20_001}),
    ]

    for response in responses:
        assert response.status_code == 422
        assert response.json()['ok'] is False
        assert response.json()['error']['code'] == 'VALIDATION_ERROR'
        assert 'input' not in str(response.json()['error']['details'])


def test_index_endpoint_requires_registered_workspace(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    project_root = tmp_path / 'unregistered'
    project_root.mkdir()
    (project_root / 'app.py').write_text('VALUE = 1\n', encoding='utf-8')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    response = TestClient(main.app).post('/api/index', json={'path': str(project_root)})

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'PROJECT_NOT_REGISTERED'


def test_index_endpoint_accepts_registered_workspace(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    project_root = tmp_path / 'registered'
    project_root.mkdir()
    (project_root / 'app.py').write_text('VALUE = 1\n', encoding='utf-8')
    manager.load(project_root)
    project_store = main.Store(tmp_path / 'agent.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'store', project_store)

    response = TestClient(main.app).post('/api/index', json={'path': str(project_root)})

    assert response.status_code == 200
    assert response.json()['files_indexed'] == 1


def test_create_chat_rejects_unknown_project_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'workspace_manager', WorkspaceManager(tmp_path / 'workspace.db'))

    response = TestClient(main.app).post('/api/chats', json={
        'title': 'Invalid project chat', 'project_id': 999,
    })

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'PROJECT_NOT_FOUND'


def test_usage_cost_uses_input_and_output_prices():
    model = {'input_price': 2.0, 'output_price': 8.0}
    assert main._estimated_cost(model, 500_000, 250_000) == 3.0
    assert main._usage_tokens({'prompt_tokens': 12, 'completion_tokens': 7}) == (12, 7)


def test_static_chat_guidance_and_docs_contract():
    root = Path(__file__).resolve().parents[1]
    static = root / 'static'
    html = (static / 'index.html').read_text(encoding='utf-8')
    javascript = '\n'.join(path.read_text(encoding='utf-8') for path in static.glob('*.js'))
    app_javascript = (static / 'app.js').read_text(encoding='utf-8')
    css = (static / 'styles.css').read_text(encoding='utf-8')

    assert 'id="nav-docs"' in html
    assert 'Local Intelligence had no exact answer' in javascript
    assert 'href="/docs"' in html
    assert 'id="workspace-access"' in html
    assert 'id="composer-open-project"' in html
    assert re.search(r"'/docs':\s*renderDocs", app_javascript)
    assert 'export function renderDocs()' in javascript
    assert "meta.error ? ' message-error'" in javascript
    assert re.search(r"error\.code\s*===\s*'PROJECT_REQUIRED'", javascript)
    assert '.workspace-access' in css
    assert '.docs-layout' in css
    assert '.message-error' in css


def test_static_frontend_module_and_theme_contract():
    root = Path(__file__).resolve().parents[1]
    static = root / 'static'
    required_modules = {
        'app.js', 'core.js', 'chat.js', 'chats.js', 'docs.js', 'providers.js',
        'local-ai.js', 'model-router.js', 'mcp.js', 'terminal.js', 'filesystem.js',
        'memory.js', 'cache.js', 'usage.js', 'settings.js',
    }
    module_paths = {path.name: path for path in static.glob('*.js')}
    assert required_modules <= module_paths.keys()
    assert all(len(path.read_text(encoding='utf-8').splitlines()) <= 300 for path in module_paths.values())

    html = (static / 'index.html').read_text(encoding='utf-8')
    app_javascript = (static / 'app.js').read_text(encoding='utf-8')
    css = (static / 'styles.css').read_text(encoding='utf-8')
    assert re.search(r'<script\s+type="module"\s+src="/static/app\.js', html)
    assert 'family=Inter' in html and 'family=JetBrains+Mono' in html
    assert 'onclick=' not in html

    routes = {
        '/': 'renderChat', '/chats': 'renderChatVault', '/docs': 'renderDocs',
        '/providers': 'renderProviders', '/local-ai': 'renderLocalAI',
        '/model-router': 'renderModelRouter', '/mcp': 'renderMCP',
        '/terminal': 'renderTerminal', '/filesystem': 'renderFilesystem',
        '/memory': 'renderMemory', '/cache': 'renderCache', '/usage': 'renderUsage',
        '/settings': 'renderSettings',
    }
    for route, renderer in routes.items():
        assert re.search(rf"'{re.escape(route)}':\s*{renderer}", app_javascript)

    tokens = {
        '--bg': '#151718', '--surface': '#1b1e20', '--surface2': '#222628',
        '--surface3': '#2a2f31', '--border': '#373d3f', '--border2': '#4a5254',
        '--text': '#edf0ed', '--text2': '#adb3b0', '--text3': '#7d8582',
        '--accent': '#b9825a', '--accent-hover': '#c9956d', '--purple': '#9b8fa8',
        '--red': '#c87368', '--yellow': '#c5a15b', '--blue': '#7896aa',
        '--cyan': '#70a3a0', '--green': '#829b82', '--radius': '6px',
        '--radius-sm': '4px',
    }
    masters = [
        (root / 'design-system' / 'zevora-workspace' / 'MASTER.md').read_text(encoding='utf-8'),
        (root / 'design-system' / 'hybrid-ai-agent' / 'MASTER.md').read_text(encoding='utf-8'),
    ]
    for token, value in tokens.items():
        assert re.search(rf'{re.escape(token)}\s*:\s*{re.escape(value)}', css)
        assert all(f'`{token}`' in master and f'`{value}`' in master for master in masters)
    assert "--font-body:Inter" in css and "--font-mono:'JetBrains Mono'" in css
    assert '.route-enter{animation:route-enter 160ms ease-out both}' in css
    assert '.state-indicator-local' in css and '.state-indicator-cloud' in css
    assert '*::-webkit-scrollbar-thumb' in css


def test_provider_config_exposes_local_runtime_without_api_key():
    response = TestClient(main.app).get('/api/providers/config')
    assert response.status_code == 200
    local = next(item for item in response.json() if item['provider'] == 'local')
    assert local['key_set'] is False
    assert local['default_model'] == main.settings.local_model_name
    assert local['runtime_status']['display_name'] == 'Zevora Local AI'
    assert local['runtime_status']['loaded'] is False


def test_provider_config_rejects_newline_api_key_without_writing(
    monkeypatch, tmp_path
):
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    providers_file = config_dir / 'providers.json'
    env_file = tmp_path / '.env'
    original_providers = '{"providers": {"openai": {"enabled": false}}}\n'
    original_env = '# Keep this comment\nOPENAI_API_KEY=old-secret\n'
    providers_file.write_text(original_providers, encoding='utf-8')
    env_file.write_text(original_env, encoding='utf-8')
    monkeypatch.setattr(main, 'ROOT', tmp_path)

    with pytest.raises(main.HTTPException) as raised:
        asyncio.run(main.update_provider_config(main.ProviderConfigRequest(
            provider='openai', api_key='secret\nINJECTED'
        )))

    assert raised.value.status_code == 400
    assert env_file.read_text(encoding='utf-8') == original_env
    assert providers_file.read_text(encoding='utf-8') == original_providers
    assert not env_file.with_suffix('.env.tmp').exists()
    assert not providers_file.with_suffix('.json.tmp').exists()


def test_provider_config_writes_env_and_json_atomically(monkeypatch, tmp_path):
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    providers_file = config_dir / 'providers.json'
    env_file = tmp_path / '.env'
    providers_file.write_text(
        '{\n  "providers": {\n    "openai": {\n      "enabled": false\n    }\n  }\n}\n',
        encoding='utf-8',
    )
    env_file.write_text(
        '# Preserve this comment\nOPENAI_API_KEY=old-secret\nOTHER=value\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'reload_settings', lambda: None)

    async def fake_refresh(self, provider_name=None):
        return [{'health_status': 'healthy', 'models_discovered': 2}]

    monkeypatch.setattr(main.ProviderDiscovery, 'refresh', fake_refresh)
    result = asyncio.run(main.update_provider_config(main.ProviderConfigRequest(
        provider='openai',
        api_key='new-secret',
        base_url='https://example.test/v1',
        default_model='test-model',
        enabled=True,
        routing_priority=12,
        supports_vision=True,
    )))

    assert result == {
        'ok': True,
        'provider': 'openai',
        'key_updated': True,
        'status': 'healthy',
        'models_discovered': 2,
    }
    env_content = env_file.read_text(encoding='utf-8')
    assert env_content == (
        '# Preserve this comment\n'
        'OPENAI_API_KEY=new-secret\n'
        'OTHER=value\n'
        'OPENAI_BASE_URL=https://example.test/v1\n'
    )
    provider = __import__('json').loads(
        providers_file.read_text(encoding='utf-8')
    )['providers']['openai']
    assert provider == {
        'enabled': True,
        'default_model': 'test-model',
        'routing_priority': 12,
        'supports_vision': True,
    }
    assert not env_file.with_suffix('.env.tmp').exists()
    assert not providers_file.with_suffix('.json.tmp').exists()


def test_routing_performance_aggregates_failures(tmp_path):
    store = main.Store(tmp_path / 'routing.db')
    for success in (False, False, True):
        store.add_routing_experience(
            'CLOUD', 'openai', 'model-a', 'general', success,
            .9 if success else 0.0, 100 if success else 500, [],
        )
    performance = store.routing_performance()
    aggregate = performance[('openai', 'model-a')]
    assert aggregate['attempts'] == 3
    assert aggregate['success_rate'] == 1 / 3
    assert aggregate['latency_ms'] == (500 + 500 + 100) / 3
