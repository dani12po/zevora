import io
import subprocess
import threading
import time

import pytest

from agent.tools.terminal_sessions import TerminalSessionManager


class BlockingProcess:
    def __init__(self, *_args, **_kwargs):
        self.stdout = io.StringIO('')
        self.stderr = io.StringIO('')
        self.killed = False
        self.released = threading.Event()

    def wait(self, timeout=None):
        if timeout is not None and not self.released.wait(timeout):
            raise subprocess.TimeoutExpired('python --version', timeout)
        self.released.wait()
        return -9 if self.killed else 0

    def kill(self):
        self.killed = True
        self.released.set()


class ImmediateProcess:
    def __init__(self, *_args, **_kwargs):
        self.stdout = io.StringIO('Python test runtime\n')
        self.stderr = io.StringIO('')

    def wait(self, timeout=None):
        return 0

    def kill(self):
        raise AssertionError('completed process must not be killed')


def wait_for_status(manager, session_id, expected, timeout=2):
    deadline = time.monotonic() + timeout
    result = manager.get(session_id)
    while time.monotonic() < deadline and result['status'] != expected:
        time.sleep(0.01)
        result = manager.get(session_id)
    return result


def test_terminal_session_completes_and_supports_incremental_polling(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', ImmediateProcess)
    manager = TerminalSessionManager()

    started = manager.start(tmp_path, 'python --version', approved=True)
    final = wait_for_status(manager, started['session_id'], 'completed')

    assert final['exit_code'] == 0
    assert any(event.get('data') == 'Python test runtime\n' for event in final['events'])
    assert final['events'][-1] == {
        'type': 'status', 'status': 'completed', 'exit_code': 0,
    }
    incremental = manager.get(started['session_id'], after=final['next'] - 1)
    assert incremental['events'] == [final['events'][-1]]
    assert incremental['next'] == final['next']


def test_terminal_kill_remains_killed_and_emits_one_final_status(tmp_path, monkeypatch):
    process = BlockingProcess()
    monkeypatch.setattr(subprocess, 'Popen', lambda *_args, **_kwargs: process)
    manager = TerminalSessionManager()

    started = manager.start(tmp_path, 'python --version', approved=True)
    killed = manager.kill(started['session_id'])
    final = wait_for_status(manager, started['session_id'], 'killed')
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        statuses = [event for event in final['events'] if event.get('type') == 'status']
        if statuses:
            break
        time.sleep(0.01)
        final = manager.get(started['session_id'])

    statuses = [event for event in final['events'] if event.get('type') == 'status']
    assert killed['status'] == 'killed'
    assert final['status'] == 'killed'
    assert final['exit_code'] == -9
    assert statuses == [{'type': 'status', 'status': 'killed', 'exit_code': -9}]


def test_terminal_enforces_workspace_cwd_and_command_policy(tmp_path):
    manager = TerminalSessionManager()
    outside = tmp_path.parent / 'outside'
    outside.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match='cwd must stay inside the workspace'):
        manager.start(tmp_path, 'python --version', approved=True, cwd='../outside')

    restricted = manager.start(tmp_path, 'pip install demo')
    assert restricted['ok'] is False
    assert restricted['approval_required'] is True
    assert restricted['risk'] == 'RESTRICTED'

    dangerous = manager.start(tmp_path, 'powershell --version', approved=True)
    assert dangerous == {
        'ok': False,
        'approval_required': False,
        'error': 'Dangerous system commands are blocked',
        'risk': 'DANGEROUS',
    }

    with pytest.raises(ValueError, match='allowlist'):
        manager.start(tmp_path, 'python -c print(1)', approved=True)


def test_terminal_permission_preferences_can_allow_safe_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', ImmediateProcess)
    manager = TerminalSessionManager()

    started = manager.start(
        tmp_path,
        'python --version',
        preferences={'terminal': 'always'},
    )

    assert started['ok'] is True
    assert started['risk'] == 'SAFE'
