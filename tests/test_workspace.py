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
