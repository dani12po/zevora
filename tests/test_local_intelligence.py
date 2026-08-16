import pytest
import sqlite3
from agent.intelligence.engine import LocalIntelligenceEngine

@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / 'agent.db'
    return LocalIntelligenceEngine(db_path)

def test_extract_knowledge_creates_record(engine):
    prompt = "How do I reverse a string in Python?"
    response = "You can use slicing. For example: `s[::-1]`"

    record = engine.extract_knowledge(prompt, response, "coding", "openai", "gpt-4o")

    assert record is not None
    assert record['task_type'] == 'coding'
    assert record['problem'] == prompt
    assert record['solution_pattern'] == response
    assert record['provider'] == 'openai'
    assert record['model'] == 'gpt-4o'
    assert record['hit_count'] == 0

def test_extract_knowledge_updates_duplicate(engine):
    prompt = "How do I reverse a string in Python?"
    response1 = "Use slicing: `s[::-1]`"
    response2 = "Alternative: `s[::-1]`"

    record1 = engine.extract_knowledge(prompt, response1, "coding", "openai", "gpt-4o")
    record2 = engine.extract_knowledge(prompt, response2, "coding", "anthropic", "claude-3")

    assert record1['id'] == record2['id']
    assert record2['solution_pattern'] == response2
    assert record2['provider'] == 'anthropic'
    assert record2['model'] == 'claude-3'
    assert record2['hit_count'] == 1

def test_retrieve_knowledge_returns_matches(engine):
    engine.extract_knowledge("How do I reverse a string in Python?", "s[::-1]", "coding", "openai", "gpt-4o")
    engine.extract_knowledge("How to sort a list?", "list.sort()", "coding", "openai", "gpt-4o")

    results = engine.retrieve_knowledge("reverse a string")
    assert len(results) == 1
    assert results[0]['problem'] == "How do I reverse a string in Python?"
    assert results[0]['hit_count'] == 1 # Retrieving increments hit_count

def test_build_context(engine):
    engine.extract_knowledge("reverse string", "s[::-1]", "coding", "openai", "gpt-4o")

    context = engine.build_context("reverse string", "coding")

    assert "Relevant knowledge:" in context
    assert "[coding] reverse string: s[::-1]" in context


def test_normalized_duplicate_merges_whitespace_and_case(engine):
    first = engine.extract_knowledge(
        "Fix   TOKEN validation", "Use strict comparison", "debugging", "openai", "model"
    )
    second = engine.extract_knowledge(
        "  fix token VALIDATION  ", "Validate expiry too", "debugging", "anthropic", "model"
    )

    assert first['id'] == second['id']
    assert second['solution_pattern'] == 'Validate expiry too'
    assert second['hit_count'] == 1


def test_retrieval_prefers_matching_project(engine):
    engine.extract_knowledge(
        "repair token validation", "project alpha fix", "debugging", "openai", "model", "alpha"
    )
    engine.extract_knowledge(
        "debug token validator", "project beta fix", "debugging", "openai", "model", "beta"
    )

    results = engine.retrieve_knowledge(
        "token validation debugging", "debugging", project="alpha"
    )

    assert results[0]['context'] == 'alpha'
    assert results[0]['last_accessed'] is not None


def test_prune_removes_only_old_low_value_unused_knowledge(engine):
    old = engine.extract_knowledge("old trivial issue", "short answer", "general", "openai", "model")
    valuable = engine.extract_knowledge(
        "old important project issue", "`code` " + "x" * 450,
        "coding", "openai", "model", "project"
    )
    with engine.connection() as conn:
        conn.execute(
            "UPDATE knowledge SET updated_at='2020-01-01T00:00:00+00:00',last_accessed='2020-01-01T00:00:00+00:00'"
        )

    result = engine.prune(knowledge_days=30)

    assert result['knowledge_removed'] == 1
    with engine.connection() as conn:
        ids = {row['id'] for row in conn.execute('SELECT id FROM knowledge')}
    assert old['id'] not in ids
    assert valuable['id'] in ids
