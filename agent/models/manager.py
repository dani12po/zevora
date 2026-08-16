"""Hardware diagnostics and local intelligence package/model discovery."""
import importlib.util
import os
import platform
from pathlib import Path
import shutil
import subprocess

import psutil

from ..config import ROOT, settings
from ..providers.local_provider import local_runtime_status


class LocalIntelligenceManager:
    """Expose bounded host diagnostics and shared local runtime state."""

    def resource_state(self) -> dict:
        memory = psutil.virtual_memory()
        disk_root = Path(ROOT.anchor or os.sep)
        disk = shutil.disk_usage(disk_root)
        gpu = self._gpu_state()
        return {
            'os': platform.system(),
            'os_version': platform.version(),
            'architecture': platform.machine(),
            'cpu': platform.processor() or 'unknown',
            'cpu_count': psutil.cpu_count(logical=True),
            'ram_available_mb': memory.available // 1024 // 1024,
            'ram_total_mb': memory.total // 1024 // 1024,
            'ram_percent': memory.percent,
            'cpu_percent': psutil.cpu_percent(interval=None),
            'disk_free_bytes': disk.free,
            'disk_total_bytes': disk.total,
            'gpu': gpu,
            'llamacpp_available': importlib.util.find_spec('llama_cpp') is not None,
            'ollama_available': shutil.which('ollama') is not None,
            'local_models': self.discover_models(),
            'local_model': local_runtime_status(),
        }

    def discover_models(self, limit: int = 100) -> list[dict]:
        roots = {ROOT / 'models', settings.local_model_package_dir / 'model'}
        configured = settings.local_model_file
        if configured.parent.exists():
            roots.add(configured.parent)
        if settings.local_model_external_path:
            external = Path(settings.local_model_external_path).expanduser()
            if external.is_file():
                roots.add(external.parent)
            elif external.is_dir():
                roots.add(external)
        found: dict[str, dict] = {}
        for root in roots:
            if not root.is_dir():
                continue
            try:
                candidates = root.glob('*.gguf')
                for path in candidates:
                    resolved = path.resolve()
                    found[str(resolved)] = {
                        'path': str(resolved),
                        'name': path.name,
                        'format': 'gguf',
                        'size_bytes': path.stat().st_size,
                        'external': not resolved.is_relative_to(ROOT.resolve()),
                    }
                    if len(found) >= max(1, min(limit, 500)):
                        return list(found.values())
            except OSError:
                continue
        return list(found.values())

    @staticmethod
    def installation_choices() -> list[dict]:
        return [
            {'id': 'recommended', 'label': 'Install Recommended ZEVORA Local Intelligence'},
            {'id': 'existing', 'label': 'Use Existing Local Model'},
            {'id': 'custom', 'label': 'Configure Custom Local Intelligence'},
            {'id': 'skip', 'label': 'Skip Local Model'},
        ]

    def uninstall_package(self, *, approved: bool = False) -> dict:
        """Plan or remove only the configured repository-managed package directory."""
        package = settings.local_model_package_dir.resolve()
        managed_root = (ROOT / 'data' / 'models').resolve()
        if package == managed_root or not package.is_relative_to(managed_root):
            raise ValueError('local package directory is outside the managed model area')
        files = []
        total_bytes = 0
        if package.is_dir():
            for path in package.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    files.append(str(path.relative_to(package)))
                    total_bytes += size
        result = {
            'approved': approved,
            'package': str(package),
            'exists': package.is_dir(),
            'files': files[:500],
            'file_count': len(files),
            'bytes': total_bytes,
            'external_models_preserved': True,
            'executed': False,
        }
        if not approved or not package.is_dir():
            return result
        shutil.rmtree(package)
        return {**result, 'executed': True, 'exists': False}

    @staticmethod
    def _gpu_state() -> dict:
        command = shutil.which('nvidia-smi')
        if not command:
            return {'available': False, 'name': None, 'vram_total_mb': None}
        try:
            output = subprocess.run(
                [command, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            ).stdout.strip().splitlines()
            if not output:
                return {'available': False, 'name': None, 'vram_total_mb': None}
            name, _, memory = output[0].partition(',')
            return {
                'available': True,
                'name': name.strip() or None,
                'vram_total_mb': int(memory.strip()) if memory.strip().isdigit() else None,
            }
        except (OSError, subprocess.SubprocessError, ValueError):
            return {'available': False, 'name': None, 'vram_total_mb': None}
