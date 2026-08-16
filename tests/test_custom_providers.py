import asyncio

import pytest
from fastapi.testclient import TestClient

import main
from agent.providers.configuration import (
    CredentialReference,
    ProviderManifest,
    ProviderStore,
    RuntimeManifest,
    RuntimePermissions,
)
from agent.providers.credentials import CredentialResolver
from agent.providers.manifest_provider import ManifestProvider
from agent.providers.runtime import CustomRuntimeManager
from agent.providers.script_analyzer import ScriptAnalyzer
from agent.providers.service import ProviderService


def openai_manifest(provider_id="custom-openai", **kwargs):
    return ProviderManifest(
        provider_id=provider_id,
        name="Custom OpenAI",
        protocol="openai-compatible",
        base_url="https://api.example.test/v1",
        default_model="example-model",
        credential=CredentialReference(name="EXAMPLE_API_KEY"),
        **kwargs,
    )


def runtime_manifest(provider_id="runtime-provider", **kwargs):
    return ProviderManifest(
        provider_id=provider_id,
        name="Runtime Provider",
        protocol="custom-runtime",
        default_model="runtime-model",
        credential=CredentialReference(source="runtime", name="RUNTIME_KEY"),
        runtime=RuntimeManifest(
            runtime="python",
            entrypoint="provider.py",
            timeout_seconds=5,
            **kwargs,
        ),
    )


def test_provider_store_writes_runtime_script_and_secret_free_export(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    manifest = openai_manifest()
    store.save(manifest)

    exported = store.export(manifest.provider_id)
    assert exported["credential"]["name"] == "EXAMPLE_API_KEY"
    assert "value" not in exported["credential"]
    persisted = (tmp_path / "providers.json").read_text(encoding="utf-8")
    assert "EXAMPLE_API_KEY" in persisted
    assert "secret-value" not in persisted

    runtime = runtime_manifest()
    store.save(runtime, 'print({"type": "result", "content": "ok"})\n')
    assert store.script_path(runtime).read_text(encoding="utf-8").startswith("print(")


def test_provider_store_does_not_commit_manifest_when_script_contract_is_invalid(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    with pytest.raises(ValueError, match="scripts can only"):
        store.save(openai_manifest(), script="print('not allowed')")
    assert store.get("custom-openai") is None


def test_provider_store_restores_script_when_manifest_write_fails(tmp_path, monkeypatch):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    manifest = runtime_manifest()
    store.save(manifest, "old-source\n")

    monkeypatch.setattr(store, "_write", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        store.save(manifest, "new-source\n")
    assert store.script_path(manifest).read_text(encoding="utf-8") == "old-source\n"


def test_credential_resolver_late_binds_and_substitutes_only_declared_secret(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("EXAMPLE_API_KEY=file-secret-value\n", encoding="utf-8")
    resolver = CredentialResolver(env_file)
    reference = CredentialReference(name="EXAMPLE_API_KEY")

    monkeypatch.delenv("EXAMPLE_API_KEY", raising=False)
    credential = resolver.resolve(reference)
    assert credential.value == "file-secret-value"
    assert credential.masked == "********alue"
    assert resolver.substitute_headers(
        {"Authorization": "Bearer ${EXAMPLE_API_KEY}"}, credential
    ) == {"Authorization": "Bearer file-secret-value"}
    with pytest.raises(ValueError, match="undeclared credential"):
        resolver.substitute_headers({"X-Other": "${OTHER_SECRET}"}, credential)


def test_provider_manifest_api_masks_credentials(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    secret = "api-contract-secret"
    env_file.write_text(f"EXAMPLE_API_KEY={secret}\n", encoding="utf-8")
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    store.save(openai_manifest())
    monkeypatch.setattr(main, "provider_service", ProviderService(store, env_file=env_file))

    response = TestClient(main.app).get("/api/provider-manifests")
    assert response.status_code == 200
    payload = response.json()
    credential = payload["providers"][0]["credential"]
    assert credential["configured"] is True
    assert credential["masked"] == "********cret"
    assert secret not in response.text


def test_script_analyzer_is_static_and_classifies_dynamic_python():
    analyzer = ScriptAnalyzer()
    analysis = analyzer.analyze(
        "import os\n"
        "import openai\n"
        "client = openai.OpenAI(base_url='https://example.test/v1', api_key=os.getenv('EXAMPLE_API_KEY'))\n"
        "client.chat.completions.create(model='example-model', messages=[], stream=True)\n"
    )
    assert analysis.protocol == "openai-compatible"
    assert analysis.base_url == "https://example.test/v1"
    assert analysis.credential_env == "EXAMPLE_API_KEY"
    assert analysis.stream is True
    assert analysis.requires_runtime is False

    dynamic = analyzer.analyze("eval(input())", "python")
    assert dynamic.protocol == "custom-runtime"
    assert dynamic.requires_runtime is True


def test_script_analyzer_redacts_sensitive_header_by_name():
    secret = "short-literal-secret"
    analysis = ScriptAnalyzer().analyze(
        "import requests\n"
        f"requests.post('https://example.test', headers={{'X-API-Key': '{secret}'}})\n",
        "python",
    )

    assert analysis.headers == {"X-API-Key": "[REDACTED]"}
    assert secret not in str(analysis.to_dict())


def test_manifest_rejects_literal_secrets_in_exported_metadata(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    with pytest.raises(ValueError, match="credential placeholder"):
        store.save(openai_manifest(headers={"Authorization": "Bearer literal-secret-value"}))

    with pytest.raises(ValueError, match="credential metadata"):
        store.save(runtime_manifest(environment={"API_TOKEN": "literal-secret-value"}))


def test_runtime_source_change_revokes_persisted_trust(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    trusted = runtime_manifest(trusted=True)
    store.save(trusted, 'print({"type": "result", "content": "old"})\n')

    saved = store.save(
        trusted, 'print({"type": "result", "content": "changed"})\n'
    )

    assert saved.runtime is not None and saved.runtime.trusted is False
    persisted = store.get(trusted.provider_id)
    assert persisted is not None and persisted.runtime is not None
    assert persisted.runtime.trusted is False
    manager = CustomRuntimeManager(store, CredentialResolver(runtime_values={"RUNTIME_KEY": "secret"}))
    with pytest.raises(PermissionError, match="approval"):
        asyncio.run(manager.execute(persisted, {"type": "chat"}))


def test_manifest_provider_uses_injected_runtime_store(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    manifest = runtime_manifest()
    store.save(manifest, 'print({"type": "result", "content": "ok"})\n')
    manager = CustomRuntimeManager(store, CredentialResolver(runtime_values={"RUNTIME_KEY": "secret"}))
    provider = ManifestProvider(manifest, manager.resolver, manager)
    assert provider.configured() is True


def test_manifest_provider_health_failure_is_logged(tmp_path, caplog, monkeypatch):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    manifest = runtime_manifest(trusted=True)
    store.save(manifest, 'print({"type": "result", "content": "ok"})\n')
    manager = CustomRuntimeManager(store, CredentialResolver(runtime_values={"RUNTIME_KEY": "secret"}))

    async def fail(*_args, **_kwargs):
        raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr(manager, "execute", fail)
    provider = ManifestProvider(manifest, manager.resolver, manager)

    assert asyncio.run(provider.health_check()) is False
    assert "Provider health check failed for runtime-provider: RuntimeError" in caplog.text
    assert "sensitive provider detail" not in caplog.text


def test_custom_runtime_requires_approval_and_returns_structured_events(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    manifest = runtime_manifest()
    store.save(
        manifest,
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'type': 'status', 'message': request['type']}))\n"
        "print(json.dumps({'type': 'text_delta', 'content': 'hello'}))\n"
        "print(json.dumps({'type': 'usage', 'usage': {'total_tokens': 2}}))\n"
        "print(json.dumps({'type': 'done'}))\n",
    )
    manager = CustomRuntimeManager(store, CredentialResolver(runtime_values={"RUNTIME_KEY": "secret"}))

    with pytest.raises(PermissionError, match="approval"):
        asyncio.run(manager.execute(manifest, {"type": "chat"}))

    result = asyncio.run(manager.execute(manifest, {"type": "chat"}, approved=True))
    assert result.text == "hello"
    assert result.usage == {"total_tokens": 2}
    assert [event["type"] for event in result.events] == ["status", "text_delta", "usage", "done"]


def test_custom_runtime_redacts_credential_from_events_and_errors(tmp_path):
    store = ProviderStore(tmp_path / "providers.json", tmp_path / "runtime")
    manifest = runtime_manifest()
    secret = "runtime-secret-value"
    store.save(
        manifest,
        "import json, os\n"
        "print(json.dumps({'type': 'result', 'content': os.environ['RUNTIME_KEY']}))\n",
    )
    manager = CustomRuntimeManager(store, CredentialResolver(runtime_values={"RUNTIME_KEY": secret}))
    result = asyncio.run(manager.execute(manifest, {"type": "chat"}, approved=True))
    assert result.text == "[REDACTED]"
    assert secret not in result.safe_log

    store.save(
        manifest,
        "import json, os\n"
        "print(json.dumps({'type': 'error', 'message': os.environ['RUNTIME_KEY']}))\n",
    )
    with pytest.raises(Exception) as caught:
        asyncio.run(manager.execute(manifest, {"type": "chat"}, approved=True))
    assert secret not in str(caught.value)
