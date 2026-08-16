"""Hash-verified, staged component updates with atomic activation and rollback."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx

from zevora.version import __version__


@dataclass(frozen=True)
class UpdateComponent:
    component_id: str
    version: str
    url: str
    sha256: str
    destination: str
    size_bytes: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateComponent":
        required = ('id', 'version', 'url', 'sha256', 'destination')
        missing = [key for key in required if not str(data.get(key, '')).strip()]
        if missing:
            raise ValueError(f"update component missing: {', '.join(missing)}")
        digest = str(data['sha256']).lower()
        if len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
            raise ValueError('component sha256 is invalid')
        destination = Path(str(data['destination']))
        if destination.is_absolute() or '..' in destination.parts:
            raise ValueError('component destination must be relative and traversal-free')
        parsed = urlparse(str(data['url']))
        if parsed.scheme not in {'https', 'file'}:
            raise ValueError('update component URL must use HTTPS or local file scheme')
        if parsed.scheme == 'file' and parsed.netloc not in {'', 'localhost'}:
            raise ValueError('file update component URL must reference the local host')
        return cls(
            component_id=str(data['id']), version=str(data['version']), url=str(data['url']),
            sha256=digest, destination=str(destination),
            size_bytes=int(data['size_bytes']) if data.get('size_bytes') is not None else None,
        )


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    min_app_version: str
    components: tuple[UpdateComponent, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateManifest":
        return cls(
            version=str(data.get('version') or '').strip(),
            min_app_version=str(data.get('min_app_version') or '0.0.0'),
            components=tuple(UpdateComponent.from_dict(item) for item in data.get('components', [])),
        )


class VerifiedUpdater:
    def __init__(self, root: Path, backup_root: Path):
        self.root = root.resolve()
        self.backup_root = backup_root.resolve()

    def plan(self, manifest: UpdateManifest, installed: dict[str, str]) -> list[UpdateComponent]:
        if _version_tuple(__version__) < _version_tuple(manifest.min_app_version):
            raise ValueError('update manifest is incompatible with this ZEVORA version')
        return [item for item in manifest.components if installed.get(item.component_id) != item.version]

    async def stage(self, components: list[UpdateComponent], staging: Path) -> list[tuple[UpdateComponent, Path]]:
        staging.mkdir(parents=True, exist_ok=True)
        staged = []
        for component in components:
            target = staging / f'{component.component_id}.stage'
            parsed = urlparse(component.url)
            if parsed.scheme == 'file':
                local_path = Path(url2pathname(unquote(parsed.path)))
                shutil.copy2(local_path, target)
            else:
                async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                    response = await client.get(component.url)
                    response.raise_for_status()
                    target.write_bytes(response.content)
            if component.size_bytes is not None and target.stat().st_size != component.size_bytes:
                target.unlink(missing_ok=True)
                raise ValueError(f'component size mismatch: {component.component_id}')
            if _sha256(target) != component.sha256:
                target.unlink(missing_ok=True)
                raise ValueError(f'component hash mismatch: {component.component_id}')
            staged.append((component, target))
        return staged

    def activate(self, staged: list[tuple[UpdateComponent, Path]], release_version: str) -> dict:
        backup = self.backup_root / release_version
        backup.mkdir(parents=True, exist_ok=True)
        activated = []
        try:
            for component, source in staged:
                destination = (self.root / component.destination).resolve()
                if not destination.is_relative_to(self.root):
                    raise ValueError('update destination escaped installation root')
                destination.parent.mkdir(parents=True, exist_ok=True)
                backup_file = backup / component.destination
                if destination.exists():
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_file)
                temporary = destination.with_suffix(destination.suffix + '.update')
                shutil.copy2(source, temporary)
                temporary.replace(destination)
                activated.append((destination, backup_file))
        except Exception:
            self.rollback(activated)
            raise
        return {'version': release_version, 'activated': len(activated), 'backup': str(backup)}

    @staticmethod
    def rollback(activated: list[tuple[Path, Path]]) -> None:
        for destination, backup in reversed(activated):
            if backup.exists():
                shutil.copy2(backup, destination)
            else:
                destination.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, int, int]:
    values = []
    for part in str(value).split('.')[:3]:
        digits = ''.join(char for char in part if char.isdigit())
        values.append(int(digits or 0))
    return tuple((values + [0, 0, 0])[:3])
