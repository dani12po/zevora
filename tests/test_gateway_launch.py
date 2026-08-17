import os
from types import SimpleNamespace

from zevora import gateway


def test_windows_launch_uses_hidden_detached_process(monkeypatch):
    captured = {}
    state = {'running': False}
    flags = {
        'new_process_group': 0x00000200,
        'detached_process': 0x00000008,
        'no_window': 0x08000000,
    }

    class StartupInfo:
        dwFlags = 0
        wShowWindow = None

    class Process:
        pid = 10

    monkeypatch.setattr(gateway, 'os', SimpleNamespace(name='nt', environ=os.environ))
    monkeypatch.setattr(gateway.subprocess, 'STARTUPINFO', StartupInfo, raising=False)
    monkeypatch.setattr(gateway.subprocess, 'STARTF_USESHOWWINDOW', 0x00000001, raising=False)
    monkeypatch.setattr(gateway.subprocess, 'SW_HIDE', 0, raising=False)
    monkeypatch.setattr(gateway.subprocess, 'CREATE_NEW_PROCESS_GROUP', flags['new_process_group'], raising=False)
    monkeypatch.setattr(gateway.subprocess, 'DETACHED_PROCESS', flags['detached_process'], raising=False)
    monkeypatch.setattr(gateway.subprocess, 'CREATE_NO_WINDOW', flags['no_window'], raising=False)
    monkeypatch.setattr(gateway, 'status', lambda: {
        'running': True, 'pid': 10, 'port': 7432, 'url': 'http://127.0.0.1:7432',
    } if state['running'] else {'running': False, 'port': None})
    monkeypatch.setattr(gateway, '_port', lambda: 7432)
    monkeypatch.setattr(gateway, '_health', lambda _port: captured.get('started', False))
    monkeypatch.setattr(gateway, '_write', lambda _pid, _port: state.update(running=True))
    monkeypatch.setattr(
        gateway.subprocess,
        'Popen',
        lambda *args, **kwargs: captured.update(kwargs, started=True) or Process(),
    )

    result = gateway.start()

    expected_flags = flags['new_process_group'] | flags['detached_process'] | flags['no_window']
    assert result['running']
    assert captured['creationflags'] == expected_flags
    assert captured['startupinfo'].dwFlags == gateway.subprocess.STARTF_USESHOWWINDOW
    assert captured['startupinfo'].wShowWindow == gateway.subprocess.SW_HIDE
    assert 'start_new_session' not in captured


def test_stop_sends_runtime_shutdown_token(monkeypatch, tmp_path):
    token_file = tmp_path / 'gateway.token'
    metadata_file = tmp_path / 'gateway.json'
    token_file.write_text('controller-secret', encoding='utf-8')
    requests = []
    health_checks = iter([False])

    monkeypatch.setattr(gateway, 'TOKEN', token_file)
    monkeypatch.setattr(gateway, 'META', metadata_file)
    monkeypatch.setattr(gateway, 'status', lambda: {
        'running': True,
        'pid': 10,
        'port': 7432,
        'url': 'http://127.0.0.1:7432',
    })
    monkeypatch.setattr(gateway, '_health', lambda _port: next(health_checks))
    monkeypatch.setattr(
        gateway,
        'urlopen',
        lambda request, timeout: requests.append(request) or type(
            'Response', (), {'read': lambda self: b''}
        )(),
    )

    assert gateway.stop(timeout=1) is True
    assert requests[0].full_url == 'http://127.0.0.1:7432/shutdown'
    assert requests[0].get_header('X-zevora-shutdown-token') == 'controller-secret'
    assert not token_file.exists()
