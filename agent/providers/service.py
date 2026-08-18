"""Shared provider management operations for API, CLI, and dashboard clients."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent.config import ROOT
from .configuration import ProviderManifest, ProviderStore
from .credentials import CredentialResolver
from .manifest_provider import ManifestProvider
from .runtime import CustomRuntimeManager
from .script_analyzer import ScriptAnalyzer


class ProviderService:
    """Own provider lifecycle operations without exposing credential values."""

    def __init__(
        self,
        store: ProviderStore | None = None,
        resolver: CredentialResolver | None = None,
        env_file: Path | None = None,
    ):
        self.store = store or ProviderStore()
        self.env_file = env_file or ROOT / ".env"
        self.resolver = resolver or CredentialResolver(self.env_file)
        self.analyzer = ScriptAnalyzer()
        self.runtime_manager = CustomRuntimeManager(self.store, self.resolver)

    def list(self) -> list[dict[str, Any]]:
        return [self._public(item) for item in self.store.list()]

    def get(self, provider_id: str) -> dict[str, Any]:
        return self._public(self._required(provider_id))

    def save(
        self,
        payload: dict[str, Any],
        *,
        credential_value: str | None = None,
        script: str | None = None,
    ) -> dict[str, Any]:
        clean = dict(payload)
        clean.pop("credential_value", None)
        credential = dict(clean.get("credential") or {})
        credential.pop("configured", None)
        credential.pop("masked", None)
        clean["credential"] = credential
        manifest = ProviderManifest.from_dict(clean)
        if credential_value is not None:
            self._write_credential(manifest, credential_value)
        saved = self.store.save(manifest, script=script)
        return self._public(saved)

    def set_enabled(self, provider_id: str, enabled: bool) -> dict[str, Any]:
        manifest = replace(self._required(provider_id), enabled=enabled)
        self.store.save(manifest)
        return self._public(manifest)

    def trust_runtime(self, provider_id: str, *, approved: bool) -> dict[str, Any]:
        manifest = self._required(provider_id)
        if manifest.protocol != "custom-runtime" or manifest.runtime is None:
            raise ValueError("provider is not a custom runtime")
        if not approved:
            raise PermissionError("explicit runtime trust approval is required")
        runtime = replace(manifest.runtime, trusted=True)
        trusted = replace(manifest, runtime=runtime, state="TRUSTED_RUNTIME")
        self.store.save(trusted)
        return self._public(trusted)

    async def test(self, provider_id: str, *, runtime_approved: bool = False) -> dict[str, Any]:
        manifest = self._required(provider_id)
        testing = replace(manifest, state="TESTING")
        self.store.save(testing)
        provider = ManifestProvider(testing, self.resolver, self.runtime_manager)
        result = await provider.test_connection(approved=runtime_approved)
        final_state = "HEALTHY" if result.get("success") else "FAILED"
        if final_state == "HEALTHY" and manifest.runtime and manifest.runtime.trusted:
            final_state = "TRUSTED_RUNTIME"
        self.store.save(replace(manifest, state=final_state))
        return result

    async def refresh_models(self, provider_id: str) -> dict[str, Any]:
        manifest = self._required(provider_id)
        provider = ManifestProvider(manifest, self.resolver, self.runtime_manager)
        models = await provider.list_models()
        return {"provider": provider_id, "models": models, "count": len(models)}

    def analyze(self, source: str, language: str = "auto") -> dict[str, Any]:
        return self.analyzer.analyze(source, language).to_dict()

    def import_manifest(
        self,
        payload: dict[str, Any] | str,
        *,
        credential_value: str | None = None,
        script: str | None = None,
    ) -> dict[str, Any]:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        data.pop("credential_value", None)
        return self.save(data, credential_value=credential_value, script=script)

    def export_manifest(self, provider_id: str) -> dict[str, Any]:
        return self.store.export(provider_id)

    def remove(self, provider_id: str) -> bool:
        return self.store.remove(provider_id)

    def generate_example(self, provider_id: str, language: str) -> dict[str, str]:
        manifest = self._required(provider_id)
        selected = language.lower()
        generators = {
            "python": self._python_example,
            "node": self._node_example,
            "javascript": self._node_example,
            "typescript": self._node_example,
            "curl": self._curl_example,
            "shell": self._curl_example,
        }
        if selected not in generators:
            raise ValueError("language must be python, node, typescript, curl, or shell")
        return {"language": selected, "source": generators[selected](manifest)}

    def runtime_availability(self) -> dict[str, Any]:
        return self.runtime_manager.availability()

    def _public(self, manifest: ProviderManifest) -> dict[str, Any]:
        status = self.resolver.status(manifest.credential)
        data = manifest.public_dict(status["configured"], status["masked"])
        if manifest.runtime:
            path = self.store.script_path(manifest)
            data["runtime"]["script_configured"] = path.is_file()
        return data

    def _required(self, provider_id: str) -> ProviderManifest:
        manifest = self.store.get(provider_id)
        if not manifest:
            raise KeyError(provider_id)
        return manifest

    def _write_credential(self, manifest: ProviderManifest, value: str) -> None:
        if manifest.credential.source != "environment" or not manifest.credential.name:
            raise ValueError("credential values require a declared environment credential name")
        if "\r" in value or "\n" in value:
            raise ValueError("credential value must not contain newlines")
        lines = self.env_file.read_text(encoding="utf-8").splitlines() if self.env_file.exists() else []
        target = manifest.credential.name
        replacement = f"{target}={value}"
        found = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, _ = stripped.partition("=")
                if key.strip().upper() == target:
                    lines[index] = replacement
                    found = True
                    break
        if not found:
            lines.append(replacement)
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.env_file.with_suffix(self.env_file.suffix + ".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(self.env_file)

    def runtime_source(self, provider_id: str) -> str:
        manifest = self._required(provider_id)
        if manifest.protocol != "custom-runtime" or manifest.runtime is None:
            raise ValueError("provider has no runtime source")
        path = self.store.script_path(manifest)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _python_example(manifest: ProviderManifest) -> str:
        env = manifest.credential.name or "PROVIDER_API_KEY"
        return (
            "import os\n"
            "from openai import OpenAI\n\n"
            f"client = OpenAI(base_url={manifest.base_url!r}, api_key=os.getenv({env!r}))\n"
            "response = client.chat.completions.create(\n"
            f"    model={manifest.default_model!r},\n"
            "    messages=[{'role': 'user', 'content': 'Hello'}],\n"
            ")\n"
            "print(response.choices[0].message.content)\n"
        )

    @staticmethod
    def _node_example(manifest: ProviderManifest) -> str:
        env = manifest.credential.name or "PROVIDER_API_KEY"
        return (
            "import OpenAI from 'openai';\n\n"
            f"const client = new OpenAI({{ baseURL: {json.dumps(manifest.base_url)}, apiKey: process.env.{env} }});\n"
            "const response = await client.chat.completions.create({\n"
            f"  model: {json.dumps(manifest.default_model)},\n"
            "  messages: [{ role: 'user', content: 'Hello' }],\n"
            "});\n"
            "console.log(response.choices[0].message.content);\n"
        )

    @staticmethod
    def _curl_example(manifest: ProviderManifest) -> str:
        env = manifest.credential.name or "PROVIDER_API_KEY"
        endpoint = manifest.base_url.rstrip("/")
        if manifest.protocol in {"openai-compatible", "local-openai-compatible"}:
            endpoint += "/chat/completions"
        return (
            f"curl {json.dumps(endpoint)} \\\n"
            "  -H \"Content-Type: application/json\" \\\n"
            f"  -H \"Authorization: Bearer ${{{env}}}\" \\\n"
            f"  -d '{{\"model\":{json.dumps(manifest.default_model)},\"messages\":[{{\"role\":\"user\",\"content\":\"Hello\"}}]}}'\n"
        )
