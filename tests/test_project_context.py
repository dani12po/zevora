from agent.core.project_index import format_project_context, index_project, project_context
from agent.memory.store import Store


def test_project_context_is_deterministic_and_relevance_ranked(tmp_path):
    root = tmp_path / 'demo'
    root.mkdir()
    (root / 'auth.py').write_text('def validate_token(token):\n    return token == "valid"\n', encoding='utf-8')
    (root / 'billing.py').write_text('def create_invoice():\n    return "invoice"\n', encoding='utf-8')
    (root / 'README.md').write_text('Demo application', encoding='utf-8')

    first = project_context(root, 'fix validate_token in auth.py')
    second = project_context(root, 'fix validate_token in auth.py')

    assert first['context_hash'] == second['context_hash']
    assert first['files'][0]['path'] == 'auth.py'
    assert 'validate_token' in format_project_context(first)
    assert len(first['files']) < first['files_indexed']


def test_project_hash_changes_when_a_tracked_file_changes(tmp_path):
    root = tmp_path / 'demo'
    root.mkdir()
    source = root / 'app.py'
    source.write_text('VALUE = 1\n', encoding='utf-8')
    before = project_context(root, 'VALUE')

    source.write_text('VALUE = 2\n', encoding='utf-8')
    after = project_context(root, 'VALUE')

    assert before['context_hash'] != after['context_hash']


def test_index_ignores_noise_and_does_not_decode_binary_files(tmp_path):
    root = tmp_path / 'demo'
    root.mkdir()
    ignored = root / 'node_modules'
    ignored.mkdir()
    (ignored / 'dependency.js').write_text('secret dependency text', encoding='utf-8')
    (root / 'image.png').write_bytes(b'\x89PNG\x00binary')
    (root / 'app.py').write_text('print("hello")', encoding='utf-8')

    rows = index_project(root)
    indexed = {row['path']: row for row in rows}

    assert 'node_modules/dependency.js' not in indexed
    assert indexed['image.png']['search_text'] == ''
    assert indexed['app.py']['search_text'] == 'print("hello")'


def test_project_index_replacement_removes_deleted_files(tmp_path):
    root = tmp_path / 'demo'
    root.mkdir()
    old_file = root / 'old.py'
    old_file.write_text('old = True', encoding='utf-8')
    store = Store(tmp_path / 'agent.db')

    first = project_context(root, 'old')
    store.replace_project_files(str(root.resolve()), first['rows'])
    old_file.unlink()
    (root / 'new.py').write_text('new = True', encoding='utf-8')
    second = project_context(root, 'new')
    store.replace_project_files(str(root.resolve()), second['rows'])

    assert [row['path'] for row in store.project_files(str(root.resolve()))] == ['new.py']


def test_exact_cache_is_invalidated_by_project_fingerprint(tmp_path):
    root = tmp_path / 'demo'
    root.mkdir()
    source = root / 'app.py'
    source.write_text('VALUE = 1\n', encoding='utf-8')
    store = Store(tmp_path / 'agent.db')
    before = project_context(root, 'VALUE')['context_hash']
    store.put_cache('explain VALUE', 'one', 'test', 'model', 'coding', str(root), before)

    assert store.get_cache('explain VALUE', before)['response'] == 'one'
    source.write_text('VALUE = 2\n', encoding='utf-8')
    after = project_context(root, 'VALUE')['context_hash']

    assert after != before
    assert store.get_cache('explain VALUE', after) is None


def test_project_discovery_is_always_in_provider_context(tmp_path):
    root = tmp_path / 'webapp'
    root.mkdir()
    (root / 'package.json').write_text('{"scripts":{"build":"next build"}}', encoding='utf-8')
    (root / 'package-lock.json').write_text('{}', encoding='utf-8')
    (root / 'next.config.js').write_text('module.exports = {}', encoding='utf-8')
    (root / 'src').mkdir()
    (root / 'src' / 'page.tsx').write_text('export default function Page() {}', encoding='utf-8')

    context = project_context(root, 'describe the architecture')
    formatted = format_project_context(context)

    assert context['discovery']['package_manager'] == 'npm'
    assert 'Next.js' in context['discovery']['frameworks']
    assert 'TypeScript' in context['discovery']['languages']
    assert 'src/page.tsx' in context['discovery']['file_tree']
    assert 'Project discovery' in formatted
    assert 'Package manager: npm' in formatted
