from zevora.cli import main
def test_version_command(capsys):
    main(['version'])
    assert 'Zero-External Vendor Oriented Reasoning Agent' in capsys.readouterr().out
def test_help_command(capsys):
    main(['help'])
    assert 'background' in capsys.readouterr().out
