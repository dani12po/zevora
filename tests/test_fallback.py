import asyncio

import pytest

import main
from agent.memory.store import Store
from agent.providers.errors import ProviderUnavailableError
from agent.routing.fallback import with_fallback
from agent.routing.hybrid_router import Route, RoutingDecision
from agent.routing.model_selector import Selection

def test_fallback_tries_next_capable_candidate():
    candidates=[Selection('first','a',1,'test'),Selection('second','b',1,'test')]
    async def execute(candidate):
        if candidate.provider=='first': raise ProviderUnavailableError('offline')
        return 'ok'
    result,errors=asyncio.run(with_fallback(candidates,execute))
    assert result=='ok' and errors[0]['provider']=='first'


def _model(provider, model_id):
    return {
        'provider': provider, 'model_id': model_id,
        'capabilities': ['general', 'coding', 'reasoning'],
        'capability_profile': {
            'instruction_score': .9, 'coding_score': .9, 'reasoning_score': .9,
        },
        'availability': 'verified', 'health_status': 'healthy',
        'input_price': 0, 'output_price': 0, 'supports_tools': True,
    }


def test_cloud_completion_tries_another_model_from_same_provider(tmp_path, monkeypatch):
    models = [_model('first', 'model-a'), _model('first', 'model-b')]

    class Registry:
        def list(self):
            return models

    class Provider:
        async def complete_for_model(self, _prompt, _system, model_id):
            if model_id == 'model-a':
                raise RuntimeError('primary unavailable')
            return 'recovered response', {'input_tokens': 2, 'output_tokens': 3}

    monkeypatch.setattr(main, 'store', Store(tmp_path / 'agent.db'))
    monkeypatch.setattr(main, 'model_registry', Registry())
    monkeypatch.setattr(main, 'get_provider', lambda _name: Provider())
    monkeypatch.setattr(main.settings, 'cloud_fallback', True)
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': 'model-a'},
    )

    result = asyncio.run(main._cloud_completion('explain this', 'be concise'))

    assert result['model'] == 'model-b'
    assert [item['status'] for item in result['fallback_trace']] == ['failed', 'success']
    assert result['fallback_trace'][0]['error'] == 'RuntimeError'


def test_cloud_completion_reports_local_and_all_failed_alternatives(tmp_path, monkeypatch):
    models = [_model('first', 'model-a'), _model('second', 'model-b')]

    class Registry:
        def list(self):
            return models

    class Provider:
        async def complete_for_model(self, _prompt, _system, _model_id):
            raise ConnectionError('secret provider detail')

    monkeypatch.setattr(main, 'store', Store(tmp_path / 'agent.db'))
    monkeypatch.setattr(main, 'model_registry', Registry())
    monkeypatch.setattr(main, 'get_provider', lambda _name: Provider())
    monkeypatch.setattr(main.settings, 'cloud_fallback', True)
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )

    with pytest.raises(main.HTTPException) as caught:
        asyncio.run(main._cloud_completion('explain this', 'be concise'))

    detail = caught.value.detail
    assert detail['code'] == 'AI_EXECUTION_ERROR'
    assert len(detail['fallback_trace']) == 2
    assert all(item['route'] == 'CLOUD' for item in detail['fallback_trace'])
    assert all(item['source'] == 'cloud_provider' for item in detail['fallback_trace'])
    assert all(item['status'] == 'failed' for item in detail['fallback_trace'])
    assert 'secret provider detail' not in str(detail)


def test_local_to_cloud_fallback_after_quality_rejection(tmp_path, monkeypatch):
    models = [_model('local', 'zevora'), _model('cloud', 'cloud-model')]

    class Registry:
        def list(self):
            return models

    calls = []

    class Provider:
        async def complete_for_model(self, _prompt, _system, model_id):
            calls.append(model_id)
            if model_id == 'zevora':
                return '', {}
            return 'cloud recovery', {'input_tokens': 1, 'output_tokens': 2}

    monkeypatch.setattr(main, 'store', Store(tmp_path / 'agent.db'))
    monkeypatch.setattr(main, 'model_registry', Registry())
    monkeypatch.setattr(main, 'get_provider', lambda _name: Provider())
    monkeypatch.setattr(main.settings, 'cloud_fallback', True)
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )

    result = asyncio.run(main._cloud_completion('explain this', 'be concise'))

    assert result['response'] == 'cloud recovery'
    assert calls == ['zevora', 'cloud-model']
    assert [item['route'] for item in result['fallback_trace']] == ['LOCAL', 'CLOUD']
    assert [item['status'] for item in result['fallback_trace']] == ['failed', 'success']


def test_cloud_to_local_fallback_after_cloud_failure(tmp_path, monkeypatch):
    models = [_model('local', 'zevora'), _model('cloud', 'cloud-model')]

    class Registry:
        def list(self):
            return models

    calls = []

    class Provider:
        async def complete_for_model(self, _prompt, _system, model_id):
            calls.append(model_id)
            if model_id == 'cloud-model':
                raise ConnectionError('offline')
            return 'local recovery', {'input_tokens': 1, 'output_tokens': 2}

    monkeypatch.setattr(main, 'store', Store(tmp_path / 'agent.db'))
    monkeypatch.setattr(main, 'model_registry', Registry())
    monkeypatch.setattr(main, 'get_provider', lambda _name: Provider())
    monkeypatch.setattr(main.settings, 'cloud_fallback', True)
    monkeypatch.setattr(main.settings, 'routing_mode', 'AUTO')
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )

    result = asyncio.run(main._cloud_completion(
        'migrate and redesign the whole project architecture', 'be concise'
    ))

    assert result['response'] == 'local recovery'
    assert calls == ['cloud-model', 'zevora']
    assert [item['route'] for item in result['fallback_trace']] == ['CLOUD', 'LOCAL']
    assert [item['status'] for item in result['fallback_trace']] == ['failed', 'success']


def test_task_exact_cache_resolves_locally_without_provider(tmp_path, monkeypatch):
    isolated_store = Store(tmp_path / 'agent.db')
    isolated_store.put_cache(
        'cached question', 'cached answer', 'openai', 'model-a', 'general'
    )
    monkeypatch.setattr(main, 'store', isolated_store)
    monkeypatch.setattr(
        main, 'get_provider',
        lambda _name: (_ for _ in ()).throw(AssertionError('provider must not run')),
    )

    result = asyncio.run(main.task(main.TaskRequest(prompt='cached question')))

    assert result['route'] == 'CACHE'
    assert result['response'] == 'cached answer'
    assert result['context_status'] == 'CACHE_SUFFICIENT'
    assert result['project_discovery'] is None
    assert result['flow'] == {
        'workspace': 'NOT_SELECTED', 'discovery': 'SKIPPED',
        'context': 'CACHE_SUFFICIENT', 'route': 'CACHE',
        'action': 'SKIPPED', 'verification': 'SKIPPED',
        'knowledge': 'RETRIEVED',
    }
    assert result['fallback_trace'] == [
        {'source': 'local', 'status': 'success', 'kind': 'exact_cache'}
    ]


def test_task_generation_reports_discovery_context_and_flow(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "flow-test"\n', encoding='utf-8'
    )
    (tmp_path / 'app.py').write_text('print("hello")\n', encoding='utf-8')
    isolated_store = Store(tmp_path / 'agent.db')
    extracted = []
    provider_systems = []
    model = _model('local', 'zevora')
    decision = RoutingDecision(
        Route.LOCAL, 'local', 'zevora', 'BEST_LOCAL_MATCH',
        ['general'], 0.1, [], 0.0,
    )

    class Registry:
        def list(self):
            return [model]

    class Intelligence:
        def build_context(self, *_args, **_kwargs):
            return 'Relevant knowledge:\n- Use the project manifest.'

        def extract_knowledge(self, *args):
            extracted.append(args)

    async def complete(_candidate, _prompt, system, _images):
        provider_systems.append(system)
        return 'The project manifest defines the application package.', {
            'input_tokens': 4, 'output_tokens': 7,
        }

    monkeypatch.setattr(main, 'store', isolated_store)
    monkeypatch.setattr(main, 'model_registry', Registry())
    monkeypatch.setattr(main, 'intelligence_engine', Intelligence())
    monkeypatch.setattr(main, '_cloud_candidates', lambda *_args: [decision])
    monkeypatch.setattr(main, '_provider_completion', complete)

    result = asyncio.run(main.task(main.TaskRequest(
        prompt='Explain this project setup', project=str(tmp_path),
    )))

    assert result['route'] == 'LOCAL'
    assert result['context_status'] == 'RETRIEVAL_ENRICHED'
    assert result['project_discovery']['languages'] == ['Python']
    assert 'pyproject.toml' in result['project_discovery']['manifests']
    assert result['flow'] == {
        'workspace': 'SELECTED', 'discovery': 'COMPLETE',
        'context': 'RETRIEVAL_ENRICHED', 'route': 'LOCAL',
        'action': 'SKIPPED', 'verification': 'SKIPPED',
        'knowledge': 'EXTRACTED',
    }
    assert 'Relevant knowledge' in provider_systems[0]
    assert 'Project discovery (authoritative local index):' in provider_systems[0]
    assert 'Languages: Python' in provider_systems[0]
    assert extracted[0][3:5] == ('local', 'zevora')
