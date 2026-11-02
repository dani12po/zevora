"""Tests for chat export endpoint and rate limiting on expensive endpoints."""

import json

import pytest
from fastapi.testclient import TestClient

import main
from agent.core.workspace import WorkspaceManager


@pytest.fixture()
def client(monkeypatch, tmp_path):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)
    with TestClient(main.app) as test_client:
        yield test_client, manager


def test_export_chat_markdown(client):
    test_client, manager = client
    chat = manager.create_chat('Export me', None)
    manager.add_message(chat['id'], 'user', 'hello world')
    manager.add_message(chat['id'], 'assistant', 'hi! how can I help?')

    response = test_client.get(f"/api/chats/{chat['id']}/export?format=markdown")
    assert response.status_code == 200
    body = response.json()
    assert '# Export me' in body['markdown']
    assert '## User' in body['markdown']
    assert 'hello world' in body['markdown']
    assert '## Assistant' in body['markdown']
    assert 'hi! how can I help?' in body['markdown']
    assert 'attachment' in response.headers.get('content-disposition', '')


def test_export_chat_json_returns_full_transcript(client):
    test_client, manager = client
    chat = manager.create_chat('Json please', None)
    manager.add_message(chat['id'], 'user', 'ping')

    response = test_client.get(f"/api/chats/{chat['id']}/export")
    assert response.status_code == 200
    body = response.json()
    assert body['title'] == 'Json please'
    assert body['messages'][0]['content'] == 'ping'


def test_export_missing_chat_returns_404(client):
    test_client, _ = client
    assert test_client.get('/api/chats/does-not-exist/export').status_code == 404


def test_export_rejects_unknown_format(client):
    test_client, manager = client
    chat = manager.create_chat('bad fmt', None)
    response = test_client.get(f"/api/chats/{chat['id']}/export?format=xml")
    assert response.status_code == 422


def test_rate_limiter_blocks_flooded_chat_endpoint(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(main, 'RATE_LIMIT_MAX_REQUESTS', 3)
    monkeypatch.setattr(main, 'RATE_LIMIT_PATH_PREFIXES', ('/api/chats',))
    main._rate_limit_events.clear()

    codes = [test_client.post('/api/chats', json={'title': f'c{i}'}).status_code
             for i in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429 and codes[4] == 429
    limited = test_client.post('/api/chats', json={'title': 'x'})
    assert limited.json()['code'] == 'RATE_LIMITED'
    assert 'Retry-After' in limited.headers
    main._rate_limit_events.clear()


def test_rate_limiter_does_not_touch_cheap_endpoints(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(main, 'RATE_LIMIT_MAX_REQUESTS', 1)
    monkeypatch.setattr(main, 'RATE_LIMIT_PATH_PREFIXES', ('/api/chats',))
    main._rate_limit_events.clear()
    for _ in range(6):
        assert test_client.get('/api/health').status_code == 200
    main._rate_limit_events.clear()
