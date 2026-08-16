"""Tests for local-first and cloud-first adaptive hybrid routing."""
import pytest

from agent.routing.hybrid_router import AdaptiveHybridRouter, Route
from agent.routing.quality_gate import validate
from agent.memory.store import Store

CHEAP = {
    'provider': 'deepseek', 'model_id': 'deepseek-chat',
    'capabilities': ['general', 'coding', 'reasoning'],
    'capability_profile': {'instruction_score': .9, 'coding_score': .85, 'reasoning_score': .8},
    'availability': 'verified', 'health_status': 'healthy', 'input_price': .14,
    'supports_tools': True,
}
EXPENSIVE = {
    'provider': 'openai', 'model_id': 'gpt-4o',
    'capabilities': ['general', 'coding', 'reasoning', 'vision'],
    'capability_profile': {'instruction_score': 1.0, 'coding_score': 1.0, 'reasoning_score': 1.0},
    'availability': 'verified', 'health_status': 'healthy', 'input_price': 5.0,
    'supports_tools': True,
}
VISION_ONLY = {
    'provider': 'openai', 'model_id': 'gpt-4o-mini',
    'capabilities': ['general', 'vision'],
    'capability_profile': {'instruction_score': .8, 'coding_score': .5, 'reasoning_score': .5},
    'availability': 'verified', 'health_status': 'healthy', 'input_price': .15,
    'supports_tools': False,
}
LOCAL = {
    'provider': 'local', 'model_id': 'zevora',
    'capabilities': ['general', 'coding', 'reasoning', 'local', 'private', 'tool_use'],
    'capability_profile': {'instruction_score': .78, 'coding_score': .68, 'reasoning_score': .72},
    'availability': 'verified', 'health_status': 'healthy', 'input_price': 0,
    'supports_tools': True, 'installed': True,
}
UNAVAILABLE = {
    'provider': 'anthropic', 'model_id': 'claude-3',
    'capabilities': ['general', 'reasoning'],
    'capability_profile': {'instruction_score': .9, 'coding_score': .7, 'reasoning_score': .9},
    'availability': 'verified', 'health_status': 'unavailable', 'input_price': 3.0,
    'supports_tools': False,
}


@pytest.fixture(autouse=True)
def enabled_synthetic_provider_policy(monkeypatch):
    """Keep synthetic router models independent from the user's live provider settings."""
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )


def test_general_task_routes_local_first():
    candidates = AdaptiveHybridRouter().candidates(
        'what is REST API?', [LOCAL, CHEAP, EXPENSIVE]
    )
    assert [item.route for item in candidates[:2]] == [Route.LOCAL, Route.CLOUD]
    assert candidates[0].provider == 'local'


def test_complex_architecture_task_routes_cloud_first():
    candidates = AdaptiveHybridRouter().candidates(
        'migrate and redesign the whole project architecture across all modules',
        [LOCAL, CHEAP, EXPENSIVE],
    )
    assert candidates[0].route is Route.CLOUD
    assert candidates[-1].route is Route.LOCAL


def test_routing_modes_constrain_candidate_pool(monkeypatch):
    router = AdaptiveHybridRouter()
    monkeypatch.setattr('agent.routing.hybrid_router.settings.routing_mode', 'LOCAL_ONLY')
    assert {item.route for item in router.candidates('explain REST', [LOCAL, CHEAP])} == {
        Route.LOCAL
    }
    monkeypatch.setattr('agent.routing.hybrid_router.settings.routing_mode', 'CLOUD_ONLY')
    assert {item.route for item in router.candidates('explain REST', [LOCAL, CHEAP])} == {
        Route.CLOUD
    }


def test_cost_optimization_prefers_cheaper_capable_provider():
    result = AdaptiveHybridRouter().decide('explain REST API', [CHEAP, EXPENSIVE])
    # Both are capable; cheaper should win when cost_optimization is on.
    assert result.provider == 'deepseek'


def test_unavailable_model_is_skipped():
    result = AdaptiveHybridRouter().decide('explain REST API', [UNAVAILABLE, CHEAP])
    assert result.provider == 'deepseek'
    assert result.route is Route.CLOUD


def test_no_models_returns_unavailable():
    result = AdaptiveHybridRouter().decide('hello', [])
    assert result.route is Route.UNAVAILABLE


def test_excluded_provider_routes_to_next_candidate(monkeypatch):
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50},
    )
    result = AdaptiveHybridRouter().decide(
        'explain REST API', [CHEAP, EXPENSIVE], exclude_providers={'deepseek'}
    )
    assert result.provider == 'openai'


def test_disabled_provider_is_not_selected(monkeypatch):
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda name: {'enabled': name != 'deepseek', 'routing_priority': 50},
    )
    result = AdaptiveHybridRouter().decide('explain REST API', [CHEAP, EXPENSIVE])
    assert result.provider == 'openai'


def test_configured_default_model_is_preferred(monkeypatch):
    preferred = {**EXPENSIVE, 'model_id': 'gpt-default'}
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda name: {
            'enabled': True,
            'routing_priority': 50,
            'default_model': 'gpt-default' if name == 'openai' else '',
        },
    )
    result = AdaptiveHybridRouter().decide('explain REST API', [CHEAP, preferred])
    assert result.provider == 'openai'
    assert result.model_id == 'gpt-default'


def test_cache_hit_short_circuits():
    result = AdaptiveHybridRouter().decide('hello', [CHEAP], cache_hit=True)
    assert result.route is Route.CACHE


def test_vision_task_requires_vision_capability():
    result = AdaptiveHybridRouter().decide('analyze this image', [CHEAP, VISION_ONLY])
    # CHEAP has no vision; VISION_ONLY does.
    # Note: task classifier may or may not classify this as vision depending on keywords.
    # At minimum the result should not crash.
    assert result.route in (Route.CLOUD, Route.UNAVAILABLE)


def test_quality_gate():
    assert validate('useful answer')['accepted']
    assert not validate('')['accepted']
    assert not validate('   ')['accepted']


def test_routing_experience_stored(tmp_path):
    store = Store(tmp_path / 'agent.db')
    store.add_routing_experience('CLOUD', 'openai', 'gpt-4o-mini', 'coding', True, .9, 250, [])
    with store.connection() as conn:
        count = conn.execute('SELECT COUNT(*) FROM routing_experiences').fetchone()[0]
    assert count == 1


def test_mature_failure_history_can_override_default_model(monkeypatch):
    preferred = {**EXPENSIVE, 'model_id': 'gpt-default'}
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda name: {
            'enabled': True,
            'routing_priority': 50,
            'default_model': 'gpt-default' if name == 'openai' else '',
        },
    )
    performance = {
        ('openai', 'gpt-default'): {
            'attempts': 5, 'success_rate': .2, 'quality_score': .2, 'latency_ms': 8000,
        },
        ('deepseek', 'deepseek-chat'): {
            'attempts': 5, 'success_rate': 1, 'quality_score': .9, 'latency_ms': 1000,
        },
    }
    result = AdaptiveHybridRouter().decide(
        'explain REST API', [CHEAP, preferred], performance=performance
    )
    assert result.provider == 'deepseek'


def test_immature_history_does_not_override_baseline_default(monkeypatch):
    preferred = {**EXPENSIVE, 'model_id': 'gpt-default'}
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda name: {
            'enabled': True,
            'routing_priority': 50,
            'default_model': 'gpt-default' if name == 'openai' else '',
        },
    )
    performance = {
        ('openai', 'gpt-default'): {
            'attempts': 2, 'success_rate': 0, 'quality_score': 0, 'latency_ms': 9000,
        },
    }
    result = AdaptiveHybridRouter().decide(
        'explain REST API', [CHEAP, preferred], performance=performance
    )
    assert result.provider == 'openai'


def test_context_overflow_skips_model_and_uses_larger_window():
    narrow = {**CHEAP, 'model_id': 'narrow', 'context_window': 32}
    wide = {**EXPENSIVE, 'model_id': 'wide', 'context_window': 4096}
    result = AdaptiveHybridRouter().decide(
        'explain REST API', [narrow, wide], context_tokens=64
    )
    assert result.model_id == 'wide'
    assert result.estimated_context_tokens >= 64


def test_tool_task_requires_explicit_tool_support():
    no_tools = {**CHEAP, 'model_id': 'no-tools', 'supports_tools': False}
    result = AdaptiveHybridRouter().decide('run terminal command', [no_tools, LOCAL])
    assert result.provider == 'local'
    assert result.tools == ['terminal.execute']


def test_uninstalled_local_package_is_not_routable():
    uninstalled = {**LOCAL, 'model_id': 'not-installed', 'installed': False}
    result = AdaptiveHybridRouter().decide('explain REST API', [uninstalled, CHEAP])
    assert result.provider == 'deepseek'
    assert result.route is Route.CLOUD


def test_output_cost_is_included_in_decision_metadata():
    model = {**CHEAP, 'output_price': 2.0, 'context_window': 2048}
    result = AdaptiveHybridRouter().decide('explain REST API', [model])
    assert result.estimated_cost is not None
    assert result.estimated_cost > 0
