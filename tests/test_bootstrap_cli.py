from zevora.cli import main

def test_gateway_target_alias_is_accepted(monkeypatch):
    monkeypatch.setattr('zevora.cli.launch',lambda:None)
    main(['start','gateway'])
