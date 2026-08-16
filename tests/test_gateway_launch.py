import subprocess
from zevora import gateway

def test_windows_launch_uses_hidden_detached_process(monkeypatch):
    captured={}; state={'running':False}
    class Process: pid=10
    monkeypatch.setattr(gateway,'status',lambda:{'running':True,'pid':10,'port':7432,'url':'http://127.0.0.1:7432'} if state['running'] else {'running':False,'port':None})
    monkeypatch.setattr(gateway,'_port',lambda:7432)
    monkeypatch.setattr(gateway,'_health',lambda port:captured.get('started',False))
    monkeypatch.setattr(gateway,'_write',lambda pid,port:state.update(running=True))
    monkeypatch.setattr(gateway.subprocess,'Popen',lambda *args,**kwargs:captured.update(kwargs,started=True) or Process())
    result=gateway.start()
    assert result['running'] and captured['creationflags'] & subprocess.CREATE_NO_WINDOW


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
