import asyncio
import json

import pytest

import main
from agent.core.planning import parse_action_plan, planning_system_prompt, public_action
from agent.memory.store import Store
from agent.routing.hybrid_router import Route, RoutingDecision
from agent.core.workspace import WorkspaceManager


def decision(provider, model):
    return RoutingDecision(
        route=Route.CLOUD,
        provider=provider,
        model_id=model,
        reason='BEST_CLOUD_MATCH',
        task_type=['coding'],
        complexity_score=0.5,
        tools=[],
        estimated_cost=None,
    )


def test_plan_parser_rejects_prose_unknown_tools_and_self_approval():
    with pytest.raises(ValueError):
        parse_action_plan('I would read package.json first.')
    with pytest.raises(ValueError):
        parse_action_plan(json.dumps({
            'needs_tools': True,
            'actions': [{'tool': 'run_anything', 'arguments': {}, 'purpose': 'unsafe'}],
        }))

    actions = parse_action_plan(json.dumps({
        'needs_tools': True,
        'actions': [{
            'tool': 'write_file',
            'arguments': {'path': 'result.txt', 'content': 'done'},
            'purpose': 'Create requested output',
            'approved': True,
        }],
    }))
    assert actions[0].approved is False
    assert public_action(actions[0])['requires_approval'] is False


def test_planner_prompt_requires_real_file_actions_for_creation():
    prompt = planning_system_prompt(5, {'create_file', 'write_file'})
    assert 'generate its complete requested content' in prompt
    assert 'do not answer with a code sample instead of an action' in prompt


def test_planner_prompt_and_parser_exclude_disabled_tools():
    enabled = {'read_file', 'file_exists'}
    prompt = planning_system_prompt(5, enabled)
    assert 'read_file' in prompt
    assert 'write_file' not in prompt
    with pytest.raises(ValueError, match='disabled'):
        parse_action_plan(json.dumps({
            'needs_tools': True,
            'actions': [{'tool': 'write_file', 'arguments': {
                'path': 'blocked.txt', 'content': 'no'}, 'purpose': 'Blocked'}],
        }), allowed_tools=enabled)


def test_public_action_uses_real_command_risk_policy():
    safe = parse_action_plan(json.dumps({
        'needs_tools': True,
        'actions': [{'tool': 'execute_command', 'arguments': {
            'command': 'python --version'}, 'purpose': 'Inspect Python'}],
    }))[0]
    restricted = parse_action_plan(json.dumps({
        'needs_tools': True,
        'actions': [{'tool': 'execute_command', 'arguments': {
            'command': 'npm install'}, 'purpose': 'Install packages'}],
    }))[0]
    assert public_action(safe)['requires_approval'] is False
    assert public_action(restricted)['requires_approval'] is True


def test_planner_resolves_persisted_project_and_never_accepts_provider_approval(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'package.json').write_text('{"scripts":{"test":"node --test"}}', encoding='utf-8')
    project = manager.load(root)
    captured = {}

    responses = iter([
        {'needs_tools': True, 'actions': [
            {'tool': 'read_file', 'arguments': {'path': 'package.json'},
             'purpose': 'Inspect manifest', 'approved': True}]},
        {'needs_tools': False, 'actions': []},
    ])

    async def fake_completion(prompt, system, requested_format='', response_validator=None, **_kwargs):
        captured.update(prompt=prompt, system=system, requested_format=requested_format)
        response = json.dumps(next(responses))
        if response_validator:
            response_validator(response)
        return {'response': response, 'provider': 'openai', 'model': 'test-model',
                'estimated_cost': 0.001}

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, '_cloud_completion', fake_completion)
    result = asyncio.run(main.plan_agent_actions(main.PlanRequest(
        prompt='inspect the project', project_id=project['id']
    )))

    assert result['actions'] == []
    assert 'package.json' in captured['prompt']
    assert captured['requested_format'] == 'json'
    assert result['iterations'] == 2
    assert result['tool_calls'] == 0
    assert result['inspection_tool_calls'] == 1


def test_planner_observes_reads_then_defers_mutation_for_approval(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'notes.txt').write_text('before', encoding='utf-8')
    project = manager.load(root)
    prompts = []
    responses = iter([
        {'needs_tools': True, 'actions': [
            {'tool': 'read_file', 'arguments': {'path': 'notes.txt'}, 'purpose': 'Inspect'}]},
        {'needs_tools': True, 'actions': [
            {'tool': 'edit_file', 'arguments': {
                'path': 'notes.txt', 'old_text': 'before', 'new_text': 'after'},
             'purpose': 'Apply requested change'}]},
    ])

    async def fake_completion(prompt, _system, requested_format='', response_validator=None, **_kwargs):
        prompts.append(prompt)
        response = json.dumps(next(responses))
        if response_validator:
            response_validator(response)
        return {'response': response, 'provider': 'openai', 'model': 'model',
                'estimated_cost': 0.0}

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, '_cloud_completion', fake_completion)
    result = asyncio.run(main.plan_agent_actions(main.PlanRequest(
        prompt='change before to after', project_id=project['id']
    )))

    assert '"content": "before"' in prompts[1]
    assert [action['tool'] for action in result['actions']] == ['edit_file']
    assert result['actions'][0]['requires_approval'] is False
    assert result['inspection_tool_calls'] == 1
    assert (root / 'notes.txt').read_text(encoding='utf-8') == 'before'


def test_planner_stops_repeated_inspection_plan(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'notes.txt').write_text('value', encoding='utf-8')
    project = manager.load(root)
    repeated = json.dumps({'needs_tools': True, 'actions': [
        {'tool': 'read_file', 'arguments': {'path': 'notes.txt'}, 'purpose': 'Inspect'}]})

    async def fake_completion(_prompt, _system, requested_format='', response_validator=None, **_kwargs):
        if response_validator:
            response_validator(repeated)
        return {'response': repeated, 'provider': 'openai', 'model': 'model',
                'estimated_cost': 0.0}

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, '_cloud_completion', fake_completion)
    with pytest.raises(main.HTTPException) as caught:
        asyncio.run(main.plan_agent_actions(main.PlanRequest(
            prompt='inspect repeatedly', project_id=project['id']
        )))
    assert caught.value.status_code == 409
    assert caught.value.detail['code'] == 'AGENT_LOOP_LIMIT'
    assert caught.value.detail['intervention_required'] is True


def test_cloud_planner_falls_back_when_primary_plan_is_schema_invalid(tmp_path, monkeypatch):
    models = [
        {'provider': 'first', 'model_id': 'model-a', 'input_price': 0, 'output_price': 0},
        {'provider': 'second', 'model_id': 'model-b', 'input_price': 0, 'output_price': 0},
    ]

    class Registry:
        def list(self):
            return models

    class Router:
        def decide(self, _prompt, _models, exclude_providers=None, **_kwargs):
            return decision('second', 'model-b') if exclude_providers else decision('first', 'model-a')

    class Provider:
        def __init__(self, response):
            self.response = response

        async def complete_for_model(self, _prompt, _system, _model):
            return self.response, {'input_tokens': 2, 'output_tokens': 3}

    providers = {
        'first': Provider(json.dumps({'needs_tools': True, 'actions': [
            {'tool': 'unknown', 'arguments': {}, 'purpose': 'invalid'}]})),
        'second': Provider(json.dumps({'needs_tools': True, 'actions': [
            {'tool': 'read_file', 'arguments': {'path': 'README.md'}, 'purpose': 'Inspect'}]})),
    }
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'agent.db'))
    monkeypatch.setattr(main, 'model_registry', Registry())
    monkeypatch.setattr(main, 'hybrid_router', Router())
    monkeypatch.setattr(main, 'get_provider', lambda name: providers[name])
    monkeypatch.setattr(main.settings, 'cloud_fallback', True)

    result = asyncio.run(main._cloud_completion(
        'inspect', 'return json', 'json', parse_action_plan
    ))
    assert result['provider'] == 'second'
    assert result['model'] == 'model-b'


def test_planner_uses_enabled_gateway_tools_for_provider_validation(tmp_path, monkeypatch):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    root = tmp_path / 'project'
    root.mkdir()
    project = manager.load(root)
    config_path = tmp_path / 'mcp.json'
    # New format: only disabled tools are listed; absent key means all on.
    config_path.write_text(json.dumps({
        'disabled': {'read_file': True},
    }), encoding='utf-8')
    original_gateway = main.LocalMCPGateway
    systems = []

    def configured_gateway(path):
        return original_gateway(path, config_path)

    async def fake_completion(_prompt, system, requested_format='', response_validator=None, **_kwargs):
        systems.append(system)
        response = json.dumps({'needs_tools': True, 'actions': [
            {'tool': 'read_file', 'arguments': {'path': 'README.md'}, 'purpose': 'Inspect'},
        ]})
        if response_validator:
            response_validator(response)
        return {'response': response, 'provider': 'openai', 'model': 'model',
                'estimated_cost': 0.0}

    monkeypatch.setattr(main, 'workspace_manager', manager)
    monkeypatch.setattr(main, 'LocalMCPGateway', configured_gateway)
    monkeypatch.setattr(main, '_cloud_completion', fake_completion)
    with pytest.raises(ValueError, match='disabled'):
        asyncio.run(main.plan_agent_actions(main.PlanRequest(
            prompt='read the readme', project_id=project['id']
        )))
    assert 'read_file' not in systems[0]
    assert 'file_exists' in systems[0]


def test_planner_routing_uses_user_intent_not_project_context_noise(tmp_path, monkeypatch):
    models = [{
        'provider': 'nvidia', 'model_id': 'planner-model',
        'capabilities': ['general', 'coding', 'reasoning'],
        'availability': 'verified', 'health_status': 'healthy',
        'supports_tools': None, 'context_window': 4096,
        'input_price': 0, 'output_price': 0,
    }]
    monkeypatch.setattr(main, 'model_registry', type('Registry', (), {
        'list': lambda self: models,
    })())
    monkeypatch.setattr(main.settings, 'cloud_fallback', True)
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )
    monkeypatch.setattr(
        main, 'get_provider',
        lambda _name: type('Provider', (), {
            'complete_for_model': lambda self, prompt, system, model_id: asyncio.sleep(
                0, result=(json.dumps({'needs_tools': False, 'actions': []}), {})
            ),
        })(),
    )
    provider_prompt = (
        'User request: inspect README.md\n\nProject context:\n'
        'artifacts/screenshot.png\narchitecture error migration command\n'
        + ('ordinary indexed content ' * 300)
    )
    result = asyncio.run(main._cloud_completion(
        provider_prompt, 'return JSON', 'json', parse_action_plan,
        require_native_tools=False, routing_prompt='inspect README.md',
    ))
    assert result['provider'] == 'nvidia'


def test_workspace_request_detection_covers_indonesian_file_creation():
    assert main._requires_workspace_agent(
        'buatkan script html dan tulis langsung ke penyimpanan disk E'
    ) is True
    assert main._requires_workspace_agent('jelaskan apa itu HTML') is False


def test_planner_rejects_unknown_project(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'workspace_manager', WorkspaceManager(tmp_path / 'workspace.db'))
    with pytest.raises(main.HTTPException) as caught:
        asyncio.run(main.plan_agent_actions(main.PlanRequest(prompt='inspect', project_id=999)))
    assert caught.value.status_code == 404
