from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent.core.workspace import WorkspaceManager

def test_workspace_load_audit_and_chats(tmp_path):
    root=tmp_path/'projects'; project=root/'demo'; project.mkdir(parents=True); (project/'package.json').write_text('{}')
    manager=WorkspaceManager(tmp_path/'workspace.db',root); loaded=manager.load(project)
    assert loaded['name']=='demo' and 'Node.js' in loaded['metadata']['frameworks']
    audit=manager.audit(loaded['id']); assert audit['files_indexed']==1
    chat=manager.create_chat('Demo',loaded['id']); manager.add_message(chat['id'],'user','hello',{'route':'LOCAL'})
    assert manager.get_chat(chat['id'])['messages'][0]['content']=='hello'
def test_workspace_blocks_paths_outside_selected_root(tmp_path):
    root=tmp_path/'projects'; root.mkdir(); outside=tmp_path/'outside'; outside.mkdir()
    manager=WorkspaceManager(tmp_path/'workspace.db',root)
    try: manager.load(outside)
    except ValueError as error: assert 'Workspace must be inside' in str(error)
    else: raise AssertionError('outside workspace must be blocked')


def test_parallel_project_audits_keep_project_identity(tmp_path):
    root = tmp_path / 'projects'
    project_a = root / 'a'
    project_b = root / 'b'
    project_a.mkdir(parents=True)
    project_b.mkdir()
    (project_a / 'a.py').write_text('A = 1')
    (project_b / 'b.js').write_text('const B = 1')
    manager = WorkspaceManager(tmp_path / 'workspace.db', root)
    loaded_a = manager.load(project_a)
    loaded_b = manager.load(project_b)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(manager.audit, loaded_a['id'])
        future_b = executor.submit(manager.audit, loaded_b['id'])
        audit_a = future_a.result()
        audit_b = future_b.result()

    assert audit_a['project_id'] == loaded_a['id']
    assert audit_b['project_id'] == loaded_b['id']
    assert audit_a['languages'] == ['Python']
    assert audit_b['languages'] == ['JavaScript']


def test_parallel_workspace_writes_wait_for_sqlite_lock(tmp_path):
    root = tmp_path / 'projects'
    root.mkdir()
    manager = WorkspaceManager(tmp_path / 'workspace.db', root)

    def create(index):
        chat = manager.create_chat(f'Chat {index}')
        manager.add_exchange(chat['id'], f'user {index}', f'assistant {index}')
        return chat['id']

    with ThreadPoolExecutor(max_workers=8) as executor:
        chat_ids = list(executor.map(create, range(40)))

    assert len(set(chat_ids)) == 40
    assert all(len(manager.get_chat(chat_id)['messages']) == 2 for chat_id in chat_ids)


def test_projects_exclude_missing_directories(tmp_path):
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    existing = tmp_path / 'existing'
    existing.mkdir()
    manager.load(existing)
    with manager.connection() as conn:
        conn.execute(
            'INSERT INTO workspace_projects'
            '(name, path, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            ('missing', str(tmp_path / 'missing'), '{}', '1', '2'),
        )

    projects = manager.projects()

    assert [project['path'] for project in projects] == [str(existing.resolve())]


def test_rapid_project_switching_has_stale_response_guard():
    source = (Path(__file__).parents[1] / 'static' / 'chat.js').read_text(encoding='utf-8')

    assert 'projectSelectionGeneration' in source
    assert source.count('isCurrentProjectSelection(generation)') >= 4
    assert "$('project-select').onchange=()=>{beginProjectSelection()" in source
