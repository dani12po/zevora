from types import SimpleNamespace

from zevora.bootstrap import Bootstrap

def test_quick_bootstrap_is_idempotent_and_safe(tmp_path):
    (tmp_path/'.env.example').write_text('OPENAI_API_KEY=\n',encoding='utf-8')
    bootstrap=Bootstrap(tmp_path,quiet=True); bootstrap.quick_check(); bootstrap.quick_check()
    assert (tmp_path/'.env').is_file()
    assert (tmp_path/'data'/'runtime').is_dir()
    assert (tmp_path/'config'/'mcp.json').is_file()
    assert 'OPENAI_API_KEY=' in (tmp_path/'.env').read_text(encoding='utf-8')


def test_windows_dependencies_use_prebuilt_llama_cpp_wheel(monkeypatch, tmp_path):
    bootstrap = Bootstrap(tmp_path, quiet=True)
    commands = []

    monkeypatch.setattr('zevora.bootstrap.os.name', 'nt')
    monkeypatch.setattr(
        'zevora.bootstrap.subprocess.run',
        lambda command, **_kwargs: commands.append(command) or SimpleNamespace(returncode=0),
    )

    bootstrap.dependencies()

    command = commands[0]
    assert '--prefer-binary' in command
    assert 'https://abetlen.github.io/llama-cpp-python/whl/cpu' in command
    assert command[-2:] == ['-e', str(tmp_path)]
