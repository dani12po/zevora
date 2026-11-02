import pytest

import main
from agent.core.workspace import WorkspaceManager


@pytest.fixture(autouse=True)
def isolate_workspace_persistence(monkeypatch, tmp_path):
    """Keep tests from writing projects or chats to the user database."""
    manager = WorkspaceManager(tmp_path / 'workspace.db')
    monkeypatch.setattr(main, 'workspace_manager', manager)
    return manager
