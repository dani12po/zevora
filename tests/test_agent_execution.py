import asyncio
import json

import pytest
from fastapi import HTTPException

import main
from agent.core.execution import AgentAction, ProjectAgentExecutor
from agent.intelligence.engine import LocalIntelligenceEngine
from agent.memory.store import Store


def stage_names(trace):
    return [stage['stage'] for stage in trace.stages]


def test_selected_workspace_authorizes_write_without_separate_approval(tmp_path):
    executor = ProjectAgentExecutor(tmp_path)

    trace = executor.execute(
        'write a note',
        [AgentAction('write_file', {'path': 'note.txt', 'content': 'hello'})],
    )

    assert (tmp_path / 'note.txt').read_text(encoding='utf-8') == 'hello'
    assert trace.pending_approvals == []
    assert trace.observations[0]['ok'] is True
    assert stage_names(trace)[:5] == [
        'UNDERSTAND', 'PLAN', 'INSPECT', 'RETRIEVE', 'REASON'
    ]


def test_executor_progress_callback_is_safe_and_secret_free(tmp_path):
    events = []
    trace = ProjectAgentExecutor(tmp_path).execute(
        'inspect workspace',
        [AgentAction('write_file', {'path': 'note.txt', 'content': 'hello'})],
        progress_callback=lambda stage, status, detail: events.append((stage, status, detail)),
    )

    assert trace.observations[0]['ok'] is True
    assert any(stage == 'ACT' and status == 'running' for stage, status, _ in events)
    assert any(stage == 'ACT' and status == 'completed' for stage, status, _ in events)
    assert all(len(detail) < 240 for _, _, detail in events)
    assert all('content' not in detail for _, _, detail in events)


def test_executor_structured_events_are_bounded_and_grounded(tmp_path):
    events = []
    trace = ProjectAgentExecutor(tmp_path).execute(
        'write and verify',
        [AgentAction('write_file', {'path': 'note.txt', 'content': 'hello'})],
        event_callback=events.append,
    )

    assert trace.observations[0]['ok'] is True
    assert [item['event'] for item in events[:2]] == ['tool_started', 'file_modified']
    assert events[0]['stage'] == 'EXECUTION'
    assert events[1]['data']['path'] == 'note.txt'
    assert 'content' not in json.dumps(events)
    assert all(len(item.get('message', '')) <= 240 for item in events)


def test_approved_write_and_read_are_observed(tmp_path):
    executor = ProjectAgentExecutor(tmp_path)

    trace = executor.execute('write and inspect', [
        AgentAction(
            'write_file', {'path': 'note.txt', 'content': 'hello'},
            approved=True, purpose='Create requested note',
        ),
        AgentAction('read_file', {'path': 'note.txt'}),
    ])

    assert (tmp_path / 'note.txt').read_text(encoding='utf-8') == 'hello'
    assert [item['ok'] for item in trace.observations] == [True, True]
    assert trace.observations[1]['output']['content'] == 'hello'
    assert trace.observations[1]['output']['next_offset'] is None
    assert trace.verified is None


def test_failed_verification_is_reported(tmp_path):
    executor = ProjectAgentExecutor(tmp_path)

    trace = executor.execute('run verification', [
        AgentAction('terminal', {'command': 'whoami'}, approved=True),
    ])

    assert trace.verified is False
    verify = next(stage for stage in trace.stages if stage['stage'] == 'VERIFY')
    assert verify['status'] == 'failed'
    assert 'FIX' not in stage_names(trace)
    assert 'VERIFY_AGAIN' not in stage_names(trace)


def test_task_rejects_actions_without_project():
    request = main.TaskRequest(
        prompt='write a file',
        actions=[main.AgentActionRequest(
            tool='write_file', arguments={'path': 'note.txt', 'content': 'hello'}
        )],
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.task(request))

    assert raised.value.status_code == 400
    assert raised.value.detail['code'] == 'PROJECT_REQUIRED'


def test_indonesian_workspace_request_without_project_never_falls_back_to_chat():
    request = main.TaskRequest(
        prompt='coba buatkan script html dan tulis langsung di penyimpanan disk E'
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.task(request))

    assert raised.value.status_code == 400
    assert raised.value.detail['code'] == 'PROJECT_REQUIRED'
    assert 'Select or open' in raised.value.detail['message']


def test_task_executes_selected_workspace_write_before_provider_call(tmp_path, monkeypatch):
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError('provider should not run after a successful mutation')

    monkeypatch.setattr(main.hybrid_router, 'decide', provider_must_not_run)
    result = asyncio.run(main.task(main.TaskRequest(
        prompt='write a file', project=str(tmp_path),
        actions=[main.AgentActionRequest(
            tool='write_file', arguments={'path': 'note.txt', 'content': 'hello'}
        )],
    )))

    assert (tmp_path / 'note.txt').read_text(encoding='utf-8') == 'hello'
    assert result['reason'] == 'TOOLS_EXECUTED'
    assert result['agent_trace']['pending_approvals'] == []


def test_dashboard_chat_may_write_inside_selected_workspace_without_approval(
    tmp_path, monkeypatch
):
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    result = asyncio.run(main.task(main.TaskRequest(
        prompt='save a note from dashboard chat',
        project=str(tmp_path),
        actions=[main.AgentActionRequest(
            tool='write_file',
            arguments={'path': 'note.txt', 'content': 'saved'},
            approved=False,
        )],
    )))

    assert (tmp_path / 'note.txt').read_text(encoding='utf-8') == 'saved'
    assert result['reason'] == 'TOOLS_EXECUTED'



def test_action_still_blocks_path_escape_without_approval(tmp_path, monkeypatch):
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.task(main.TaskRequest(
            prompt='write outside the project',
            project=str(tmp_path),
            actions=[main.AgentActionRequest(
                tool='write_file',
                arguments={'path': '../outside.txt', 'content': 'blocked'},
                approved=False,
            )],
        )))

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'ACTION_FAILED'
    assert not (tmp_path.parent / 'outside.txt').exists()


def test_absolute_path_into_another_workspace_is_blocked(tmp_path, monkeypatch):
    selected = tmp_path / 'workspace-a'
    other = tmp_path / 'workspace-b'
    selected.mkdir()
    other.mkdir()
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.task(main.TaskRequest(
            prompt='write into another workspace',
            project=str(selected),
            actions=[main.AgentActionRequest(
                tool='write_file',
                arguments={'path': str(other / 'outside.txt'), 'content': 'blocked'},
                approved=True,
            )],
        )))

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'ACTION_FAILED'
    assert not (other / 'outside.txt').exists()


def test_approved_action_still_blocks_dangerous_command(tmp_path, monkeypatch):
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.task(main.TaskRequest(
            prompt='format the system drive',
            project=str(tmp_path),
            actions=[main.AgentActionRequest(
                tool='execute_command', arguments={'command': 'format C:'}, approved=True,
            )],
        )))

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'ACTION_FAILED'
    failed = raised.value.detail['failed_actions'][0]
    assert failed.get('approval_required', False) is False
    assert 'blocked' in str(failed['output']).lower()


def test_approved_html_write_returns_authoritative_local_receipt(tmp_path, monkeypatch):
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    intelligence = LocalIntelligenceEngine(tmp_path / 'intelligence.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'agent.db'))
    monkeypatch.setattr(main, 'intelligence_engine', intelligence)

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError('provider should not run after a successful mutation')

    monkeypatch.setattr(main.hybrid_router, 'decide', provider_must_not_run)
    html = '<!doctype html><html><body><h1>Hello</h1></body></html>'
    result = asyncio.run(main.task(main.TaskRequest(
        prompt='buatkan contoh.html', project=str(tmp_path),
        actions=[main.AgentActionRequest(
            tool='write_file',
            arguments={'path': 'contoh.html', 'content': html},
            approved=True,
            purpose='Create the requested HTML file',
        )],
    )))

    target = tmp_path / 'contoh.html'
    assert target.read_text(encoding='utf-8') == html
    assert result['route'] == 'LOCAL'
    assert result['reason'] == 'TOOLS_EXECUTED'
    assert result['provider'] == 'local'
    assert result['context_status'] == 'RETRIEVAL_ENRICHED'
    assert result['project_discovery']['languages'] == ['HTML']
    assert result['flow'] == {
        'workspace': 'SELECTED', 'discovery': 'COMPLETE',
        'context': 'RETRIEVAL_ENRICHED', 'route': 'LOCAL',
        'action': 'EXECUTED', 'verification': 'SKIPPED',
        'knowledge': 'EXTRACTED',
    }
    assert str(target.resolve()) in result['response']
    assert 'write_file' in result['response']
    assert html in result['response']
    assert '1 lines' in result['response']
    assert f'{len(html.encode("utf-8"))} bytes' in result['response']
    with intelligence.connection() as conn:
        knowledge = conn.execute('SELECT provider, model FROM knowledge').fetchone()
    assert dict(knowledge) == {'provider': 'local', 'model': 'mcp-tools'}


def test_failed_workspace_action_never_reaches_response_generation(tmp_path, monkeypatch):
    manager = main.WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError('provider should not run after a failed action')

    monkeypatch.setattr(main.hybrid_router, 'decide', provider_must_not_run)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.task(main.TaskRequest(
            prompt='tulis file di luar project', project=str(tmp_path),
            actions=[main.AgentActionRequest(
                tool='write_file',
                arguments={'path': '../outside.html', 'content': '<p>blocked</p>'},
                approved=True,
            )],
        )))

    assert raised.value.status_code == 409
    assert raised.value.detail['code'] == 'ACTION_FAILED'
    assert not (tmp_path.parent / 'outside.html').exists()


def test_workspace_permission_preferences_are_enforced(tmp_path):
    executor = ProjectAgentExecutor(tmp_path, preferences={'terminal': 'deny', 'git': 'deny'})

    trace = executor.execute('inspect project', [
        AgentAction('execute_command', {'command': 'python --version'}, approved=True),
        AgentAction('git', {'operation': 'status'}, approved=True),
    ])

    assert [item['ok'] for item in trace.observations] == [False, False]
    assert 'denied' in trace.observations[0]['output']['message'].lower()
    assert 'denied' in trace.observations[1]['output']['message'].lower()



def test_executor_enforces_tool_call_limit(tmp_path, monkeypatch):
    monkeypatch.setattr('agent.core.execution.settings.max_agent_tool_calls', 2)
    executor = ProjectAgentExecutor(tmp_path)
    trace = executor.execute('inspect repeatedly', [
        AgentAction('file_exists', {'path': f'{index}.txt'}) for index in range(4)
    ])

    assert len(trace.observations) == 2
    act = next(stage for stage in trace.stages if stage['stage'] == 'ACT')
    assert act['status'] == 'failed'
    assert act['detail']['limit_reached'] is True
    understand = trace.stages[0]['detail']
    assert understand['max_iterations'] == 12
    assert understand['timeout_seconds'] == 300
