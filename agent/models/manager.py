"""Local machine and llama.cpp runtime diagnostics."""
import psutil

from ..providers.local_provider import local_runtime_status


class LocalIntelligenceManager:
    """Expose host resources and the shared local model runtime state."""

    def resource_state(self) -> dict:
        memory = psutil.virtual_memory()
        return {
            'ram_available_mb': memory.available // 1024 // 1024,
            'ram_total_mb': memory.total // 1024 // 1024,
            'ram_percent': memory.percent,
            'cpu_percent': psutil.cpu_percent(interval=None),
            'local_model': local_runtime_status(),
        }
