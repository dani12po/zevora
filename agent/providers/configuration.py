"""Versioned universal provider manifests and atomic local persistence."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.config import ROOT

PROVIDER_SCHEMA_VERSION = 2
PROTOCOLS = {
    "openai-compatible", "anthropic-compatible", "http-rest",
    "local-openai-compatible", "custom-runtime", "unknown",
}
RUNTIMES = {"python", "node", "shell", "typescript"}
TRUST_STATES = {
    "UNCONFIGURED", "CONFIGURED", "TESTING", "HEALTHY", "DEGRADED",
    "FAILED", "TRUSTED_RUNTIME",
}
CAPABILITY_KEYS = {
    "chat", "streaming", "reasoning", "vision", "audio", "tool_calling",
    "json_mode", "embeddings", "code", "long_context",
}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[_-])(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|password|secret|credential)(?:$|[_-])"
)
_SENSITIVE_HEADER_RE = re.compile(r"(?i)^(?:authorization|proxy-authorization|x-api-key|api-key|x-auth-token)$")
_SECRET_VALUE_RE = re.compile(r"(?i)(?:bearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}\b)")


def _validate_secret_free(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)) and item not in (None, "", False):
                raise ValueError(f"{path} must not contain credential metadata")
            _validate_secret_free(item, path)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_secret_free(item, path)
    elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise ValueError(f"{path} must not contain literal credentials")


@dataclass(frozen=True)
class CredentialReference:
    source: str = "environment"
    name: str = ""

    def validate(self) -> None:
        if self.source not in {"environment", "secure-local", "runtime", "external"}:
            raise ValueError("unsupported credential source")
        if self.name and not _ENV_RE.fullmatch(self.name):
            raise ValueError("credential name must be an environment-style identifier")


@dataclass(frozen=True)
class RuntimePermissions:
    network: bool = True
    filesystem: str = "temporary"
    workspace: bool = False
    allowed_hosts: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.filesystem not in {"none", "temporary"}:
            raise ValueError("runtime filesystem must be none or temporary")
        if self.workspace:
            raise ValueError("provider runtimes cannot mount the ZEVORA workspace")
        for host in self.allowed_hosts:
            if not host or "/" in host or "\\" in host or ":" in host:
                raise ValueError("runtime allowed_hosts must contain hostnames only")


@dataclass(frozen=True)
class RuntimeManifest:
    runtime: str
    entrypoint: str
    permissions: RuntimePermissions = field(default_factory=RuntimePermissions)
    trusted: bool = False
    timeout_seconds: int = 120
    max_output_bytes: int = 10 * 1024 * 1024
    max_temp_bytes: int = 100 * 1024 * 1024
    environment: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.runtime not in RUNTIMES:
            raise ValueError("unsupported provider runtime")
        entry = Path(self.entrypoint)
        if entry.is_absolute() or ".." in entry.parts or len(entry.parts) != 1:
            raise ValueError("runtime entrypoint must be one filename")
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("runtime timeout must be between 1 and 600 seconds")
        if not 1024 <= self.max_output_bytes <= 50 * 1024 * 1024:
            raise ValueError("runtime output limit is outside the supported range")
        if not 1024 <= self.max_temp_bytes <= 500 * 1024 * 1024:
            raise ValueError("runtime temporary disk limit is outside the supported range")
        self.permissions.validate()
        for key, value in self.environment.items():
            if not _ENV_RE.fullmatch(key) or len(str(value)) > 2048:
                raise ValueError("invalid runtime environment metadata")
            if _SENSITIVE_KEY_RE.search(key):
                raise ValueError("runtime environment must not contain credential metadata")
        _validate_secret_free(self.environment, "runtime environment")


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    name: str
    protocol: str
    base_url: str = ""
    default_model: str = ""
    credential: CredentialReference = field(default_factory=CredentialReference)
    enabled: bool = True
    routing_priority: int = 50
    request_options: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, bool | None] = field(default_factory=dict)
    context_length: int | None = None
    input_price: float | None = None
    output_price: float | None = None
    runtime: RuntimeManifest | None = None
    state: str = "CONFIGURED"
    source: str = "user"
    schema_version: int = PROVIDER_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema version")
        if not _ID_RE.fullmatch(self.provider_id):
            raise ValueError("provider id must use lowercase letters, numbers, dots, underscores, or hyphens")
        if not self.name.strip() or len(self.name) > 120:
            raise ValueError("provider name is required")
        if self.protocol not in PROTOCOLS:
            raise ValueError("unsupported provider protocol")
        if self.state not in TRUST_STATES:
            raise ValueError("unsupported provider state")
        if not 0 <= self.routing_priority <= 999:
            raise ValueError("routing priority must be between 0 and 999")
        if self.protocol not in {"custom-runtime", "unknown"}:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("provider base_url must be an absolute HTTP(S) URL")
        if self.protocol == "custom-runtime":
            if not self.runtime:
                raise ValueError("custom runtime provider requires a runtime manifest")
            self.runtime.validate()
        elif self.runtime is not None:
            raise ValueError("runtime metadata is only valid for custom-runtime providers")
        self.credential.validate()
        unknown = set(self.capabilities) - CAPABILITY_KEYS
        if unknown:
            raise ValueError(f"unknown capabilities: {', '.join(sorted(unknown))}")
        for name, mapping in (("request options", self.request_options), ("extra body", self.extra_body)):
            json.dumps(mapping, ensure_ascii=True)
            _validate_secret_free(mapping, name)
        credential_placeholder = f"${{{self.credential.name}}}" if self.credential.name else ""
        for key, value in self.headers.items():
            if not key.strip() or "\r" in key or "\n" in key or "\r" in value or "\n" in value:
                raise ValueError("invalid provider header")
            if len(key) > 128 or len(value) > 4096:
                raise ValueError("provider header is too large")
            sensitive = _SENSITIVE_HEADER_RE.fullmatch(key.strip()) or _SECRET_VALUE_RE.search(value)
            if sensitive and (not credential_placeholder or credential_placeholder not in value):
                raise ValueError("sensitive provider headers must use the declared credential placeholder")
        if self.context_length is not None and self.context_length <= 0:
            raise ValueError("context_length must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self, configured: bool = False, masked: str = "") -> dict[str, Any]:
        data = self.to_dict()
        data["credential"] = {
            "source": self.credential.source,
            "name": self.credential.name,
            "configured": configured,
            "masked": masked,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderManifest":
        credential_data = data.get("credential") or {}
        runtime_data = data.get("runtime")
        runtime = None
        if runtime_data:
            permissions_data = runtime_data.get("permissions") or {}
            runtime = RuntimeManifest(
                runtime=str(runtime_data.get("runtime", "")),
                entrypoint=str(runtime_data.get("entrypoint", "")),
                permissions=RuntimePermissions(
                    network=bool(permissions_data.get("network", True)),
                    filesystem=str(permissions_data.get("filesystem", "temporary")),
                    workspace=bool(permissions_data.get("workspace", False)),
                    allowed_hosts=tuple(permissions_data.get("allowed_hosts") or ()),
                ),
                trusted=bool(runtime_data.get("trusted", False)),
                timeout_seconds=int(runtime_data.get("timeout_seconds", 120)),
                max_output_bytes=int(runtime_data.get("max_output_bytes", 10 * 1024 * 1024)),
                max_temp_bytes=int(runtime_data.get("max_temp_bytes", 100 * 1024 * 1024)),
                environment={str(k): str(v) for k, v in (runtime_data.get("environment") or {}).items()},
            )
        manifest = cls(
            provider_id=str(data.get("provider_id") or data.get("id") or "").strip().lower(),
            name=str(data.get("name") or "").strip(),
            protocol=str(data.get("protocol") or "unknown").strip().lower(),
            base_url=str(data.get("base_url") or "").strip(),
            default_model=str(data.get("default_model") or data.get("model") or "").strip(),
            credential=CredentialReference(
                source=str(credential_data.get("source") or "environment"),
                name=str(credential_data.get("name") or data.get("api_key_env") or "").strip(),
            ),
            enabled=bool(data.get("enabled", True)),
            routing_priority=int(data.get("routing_priority", 50)),
            request_options=dict(data.get("request_options") or {}),
            extra_body=dict(data.get("extra_body") or {}),
            headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
            capabilities={str(k): v for k, v in (data.get("capabilities") or {}).items()},
            context_length=data.get("context_length"),
            input_price=data.get("input_price"),
            output_price=data.get("output_price"),
            runtime=runtime,
            state=str(data.get("state") or "CONFIGURED"),
            source=str(data.get("source") or "user"),
            schema_version=int(data.get("schema_version", PROVIDER_SCHEMA_VERSION)),
        )
        manifest.validate()
        return manifest


class ProviderStore:
    """Atomic provider persistence with backward-compatible migration."""

    def __init__(self, path: Path | None = None, runtime_root: Path | None = None):
        self.path = path or ROOT / "config" / "providers.json"
        self.runtime_root = runtime_root or ROOT / "data" / "runtime" / "providers"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    def load_raw(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"providers": {}, "model_overrides": {}}
        return self._migrate(data)

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        if int(data.get("provider_schema_version", 1)) >= PROVIDER_SCHEMA_VERSION:
            data.setdefault("custom_providers", [])
            return data
        migrated = dict(data)
        converted = []
        for item in data.get("custom_providers", []):
            provider_id = str(item.get("provider_id") or item.get("name") or "").strip().lower()
            provider_id = re.sub(r"[^a-z0-9._-]+", "-", provider_id).strip("-")
            if not provider_id or not item.get("base_url"):
                continue
            converted.append(ProviderManifest(
                provider_id=provider_id,
                name=str(item.get("display_name") or item.get("name") or provider_id),
                protocol="openai-compatible",
                base_url=str(item.get("base_url")),
                default_model=str(item.get("default_model") or ""),
                credential=CredentialReference(name=str(item.get("api_key_env") or "")),
                capabilities={"vision": bool(item.get("supports_vision"))},
            ).to_dict())
        migrated["custom_providers"] = converted
        migrated["provider_schema_version"] = PROVIDER_SCHEMA_VERSION
        self._write(migrated, backup=self.path.exists())
        return migrated

    def list(self) -> list[ProviderManifest]:
        manifests = []
        for item in self.load_raw().get("custom_providers", []):
            try:
                manifests.append(ProviderManifest.from_dict(item))
            except (TypeError, ValueError):
                continue
        return manifests

    def get(self, provider_id: str) -> ProviderManifest | None:
        normalized = provider_id.strip().lower()
        return next((item for item in self.list() if item.provider_id == normalized), None)

    def save(self, manifest: ProviderManifest, script: str | None = None) -> ProviderManifest:
        manifest.validate()
        script_path = None
        previous_script: bytes | None = None
        if script is not None:
            if manifest.protocol != "custom-runtime" or manifest.runtime is None:
                raise ValueError("scripts can only be stored for custom runtime providers")
            encoded_script = script.encode("utf-8")
            if len(encoded_script) > 512 * 1024:
                raise ValueError("provider script exceeds 512 KB")
            script_path = self.script_path(manifest)
            script_path.parent.mkdir(parents=True, exist_ok=True)
            previous_script = script_path.read_bytes() if script_path.is_file() else None
            if previous_script != encoded_script and manifest.runtime.trusted:
                manifest = replace(
                    manifest,
                    runtime=replace(manifest.runtime, trusted=False),
                    state="CONFIGURED",
                )
            temporary_script = script_path.with_suffix(script_path.suffix + ".tmp")
            temporary_script.write_bytes(encoded_script)
            temporary_script.replace(script_path)

        data = self.load_raw()
        entries = [item for item in data.get("custom_providers", [])
                   if str(item.get("provider_id") or item.get("name") or "").lower() != manifest.provider_id]
        entries.append(manifest.to_dict())
        data["custom_providers"] = sorted(entries, key=lambda item: str(item.get("provider_id", "")))
        data["provider_schema_version"] = PROVIDER_SCHEMA_VERSION
        try:
            self._write(data, backup=self.path.exists())
        except Exception:
            if script_path is not None:
                if previous_script is None:
                    script_path.unlink(missing_ok=True)
                else:
                    rollback = script_path.with_suffix(script_path.suffix + ".rollback")
                    rollback.write_bytes(previous_script)
                    rollback.replace(script_path)
            raise
        return manifest

    def remove(self, provider_id: str) -> bool:
        normalized = provider_id.strip().lower()
        data = self.load_raw()
        before = len(data.get("custom_providers", []))
        data["custom_providers"] = [item for item in data.get("custom_providers", [])
            if str(item.get("provider_id") or item.get("name") or "").lower() != normalized]
        if len(data["custom_providers"]) == before:
            return False
        self._write(data, backup=True)
        runtime_dir = (self.runtime_root / normalized).resolve()
        if runtime_dir.parent == self.runtime_root.resolve() and runtime_dir.is_dir():
            shutil.rmtree(runtime_dir)
        return True

    def script_path(self, manifest: ProviderManifest) -> Path:
        if manifest.runtime is None:
            raise ValueError("provider has no runtime")
        root = (self.runtime_root / manifest.provider_id).resolve()
        path = (root / manifest.runtime.entrypoint).resolve()
        if path.parent != root:
            raise ValueError("runtime entrypoint escapes provider directory")
        return path

    def export(self, provider_id: str) -> dict[str, Any]:
        manifest = self.get(provider_id)
        if not manifest:
            raise KeyError(provider_id)
        return manifest.public_dict(configured=False, masked="")

    def _write(self, data: dict[str, Any], backup: bool = False) -> None:
        if backup and self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)
