"""Validated local intelligence package manifests."""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from zevora.version import LOCAL_PACKAGE_MANIFEST_VERSION, MIN_COMPATIBLE_APP_VERSION


@dataclass(frozen=True)
class LocalPackageManifest:
    package_id: str
    version: str
    runtime: str
    format: str
    model_id: str
    capabilities: tuple[str, ...] = ()
    context_length: int | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    source: str | None = None
    license: str | None = None
    components: dict[str, str] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    manifest_version: int = LOCAL_PACKAGE_MANIFEST_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocalPackageManifest":
        required = ("package_id", "version", "runtime", "format", "model_id")
        missing = [key for key in required if not str(data.get(key, "")).strip()]
        if missing:
            raise ValueError(f"manifest missing required fields: {', '.join(missing)}")
        manifest_version = int(data.get("manifest_version", LOCAL_PACKAGE_MANIFEST_VERSION))
        if manifest_version > LOCAL_PACKAGE_MANIFEST_VERSION:
            raise ValueError("unsupported local intelligence manifest version")
        capabilities = tuple(str(item).strip() for item in data.get("capabilities", []) if str(item).strip())
        context_length = data.get("context_length")
        if context_length is not None and int(context_length) <= 0:
            raise ValueError("context_length must be positive when provided")
        size_bytes = data.get("size_bytes")
        if size_bytes is not None and int(size_bytes) < 0:
            raise ValueError("size_bytes cannot be negative")
        return cls(
            package_id=str(data["package_id"]).strip(),
            version=str(data["version"]).strip(),
            runtime=str(data["runtime"]).strip().lower(),
            format=str(data["format"]).strip().lower(),
            model_id=str(data["model_id"]).strip(),
            capabilities=capabilities,
            context_length=int(context_length) if context_length is not None else None,
            size_bytes=int(size_bytes) if size_bytes is not None else None,
            sha256=str(data["sha256"]).lower() if data.get("sha256") else None,
            source=str(data["source"]).strip() if data.get("source") else None,
            license=str(data["license"]).strip() if data.get("license") else None,
            components=dict(data.get("components") or {}),
            compatibility=dict(data.get("compatibility") or {}),
            manifest_version=manifest_version,
        )

    @classmethod
    def load(cls, path: Path) -> "LocalPackageManifest":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "manifest_version": self.manifest_version,
            "package_id": self.package_id,
            "version": self.version,
            "runtime": self.runtime,
            "format": self.format,
            "model_id": self.model_id,
            "capabilities": list(self.capabilities),
            "context_length": self.context_length,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "source": self.source,
            "license": self.license,
            "components": self.components,
            "compatibility": self.compatibility,
        }
        return payload

    def verify_file(self, path: Path) -> bool:
        if not self.sha256:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().lower() == self.sha256.lower()

    def compatible_with(self, app_version: str = MIN_COMPATIBLE_APP_VERSION) -> bool:
        minimum = str(self.compatibility.get("min_app_version", "0.0.0"))
        return _version_tuple(app_version) >= _version_tuple(minimum)


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = str(value).split(".")
    numbers = []
    for part in parts[:3]:
        digits = "".join(char for char in part if char.isdigit())
        numbers.append(int(digits or 0))
    return tuple((numbers + [0, 0, 0])[:3])
