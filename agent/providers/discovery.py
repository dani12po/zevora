from datetime import datetime, timezone
from ..models.metadata import ModelMetadata
from ..models.registry import ModelRegistry
from .registry import configured_providers, get_provider

class ProviderDiscovery:
    def __init__(self, registry: ModelRegistry): self.registry = registry

    def configured_list(self) -> list[dict]:
        """Synchronous list of providers and their configured status (no health check)."""
        return configured_providers()

    async def providers(self) -> list[dict]:
        result = []
        for item in configured_providers():
            provider = get_provider(item['provider'])
            try:
                health = await provider.health_check() if item['configured'] and item['enabled'] else False
            except Exception:
                health = False
            status = 'disabled' if not item['enabled'] else (
                'healthy' if health else ('unconfigured' if not item['configured'] else 'unavailable')
            )
            result.append({**item, 'health_status': status})
        return result

    async def refresh(self, provider_name: str | None = None) -> list[dict]:
        names = (
            [provider_name]
            if provider_name
            else [item['provider'] for item in configured_providers() if item['configured'] and item['enabled']]
        )
        output = []
        for name in names:
            configured = next((item for item in configured_providers() if item['provider'] == name), None)
            if not configured or not configured['enabled']:
                output.append({'provider': name, 'health_status': 'disabled', 'models_discovered': 0})
                continue
            provider = get_provider(name)
            if not getattr(provider, 'configured', lambda: False)():
                continue
            try:
                healthy = await provider.health_check()
            except Exception:
                healthy = False
            models: list[dict] = []
            if healthy:
                try:
                    models = await provider.list_models()
                except Exception:
                    models = []
            normalized = [
                ModelMetadata(
                    provider=name,
                    model_id=item['model_id'],
                    display_name=item.get('display_name') or item['model_id'],
                    capabilities=item.get('capabilities', []),
                    capability_profile=item.get('capability_profile', {}),
                    context_window=item.get('context_window'),
                    max_output_tokens=item.get('max_output_tokens'),
                    supports_streaming=item.get('supports_streaming'),
                    supports_tools=item.get('supports_tools'),
                    supports_vision=item.get('supports_vision'),
                    supports_reasoning=item.get('supports_reasoning'),
                    supports_code=item.get('supports_code'),
                    supports_json=item.get('supports_json'),
                    input_price=item.get('input_price'),
                    output_price=item.get('output_price'),
                    availability=item.get('availability', 'unknown'),
                    health_status='healthy' if healthy else 'unavailable',
                    last_verified=datetime.now(timezone.utc).isoformat(),
                )
                for item in models
            ]
            # Only replace if we actually got models — preserve stale data on empty list.
            if normalized:
                self.registry.replace_provider(name, normalized)
            output.append({
                'provider': name,
                'health_status': 'healthy' if healthy else 'unavailable',
                'models_discovered': len(normalized),
            })
        return output
