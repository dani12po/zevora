from datetime import datetime, timedelta, timezone
from pathlib import Path
from agent.memory.store import Store
from agent.routing.router import ModelRouter, TaskType
from agent.security.redaction import redact
from agent.skills.openclaw import OpenClawSkillSource

def test_redacts_secret():
    synthetic_secret = 'sk' + '-' + ('synthetic' * 3)
    assert synthetic_secret not in redact(f'credential={synthetic_secret}')
def test_exact_cache(tmp_path: Path):
    store=Store(tmp_path/'agent.db'); store.put_cache('hello','world','test','model','simple')
    assert store.get_cache('hello')['response']=='world'
def test_classification():
    assert ModelRouter().classify('Please debug this error') == TaskType.DEBUGGING
def test_openclaw_router_matches_ai_skill():
    source=OpenClawSkillSource(); matches=source.route('Design an LLM agent with cache')
    assert matches[0].skill_id == 'm7'
    context, _ = source.context_for('Design an LLM agent with cache')
    assert len(context) <= 8000


def test_store_retention_supports_dry_run_and_execution(tmp_path: Path):
    store = Store(tmp_path / 'agent.db')
    old = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO memories(kind,content,created_at) VALUES('conversation','old',?)", (old,)
        )
        conn.execute(
            "INSERT INTO usage_events(cache_hit,created_at) VALUES(0,?)", (old,)
        )

    preview = store.retention(dry_run=True)
    assert preview['candidates']['memories'] == 1
    assert preview['candidates']['usage_events'] == 1
    with store.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0] == 1

    executed = store.retention(dry_run=False)
    assert executed['total'] == 2
    with store.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM usage_events').fetchone()[0] == 0
