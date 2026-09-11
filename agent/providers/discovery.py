import asyncio
import logging
from datetime import datetime, timezone
from ..config import settings
from ..models.metadata import ModelMetadata
from ..models.registry import ModelRegistry
from .errors import ProviderUnavailableError, failure_details
from .registry import configured_providers, get_provider

logger = logging.getLogger(__name__)


class ProviderDiscovery:
    def __init__(self, registry: ModelRegistry): self.registry = registry

    def configured_list(self) -> list[dict]:
        """Synchronous list of providers and their configured status (no health check)."""
        return configured_providers()

    async def _health_one(self, item: dict) -> dict:
        """Health-check one provider, bounded by the discovery timeout."""
        try:
            health = await asyncio.wait_for(
                get_provider(item['provider']).health_check(),
                timeout=settings.discovery_timeout_seconds,
            ) if item['configured'] and item['enabled'] else False
        except Exception as error:
            logger.warning("Provider discovery health check failed for %s: %s", item['provider'], type(error).__name__)
            health = False
        status = 'disabled' if not item['enabled'] else (
            'healthy' if health else ('unconfigured' if not item['configured'] else 'unavailable')
        )
        return {**item, 'health_status': status}

    async def providers(self) -> list[dict]:
        items = configured_providers()
        probed = await asyncio.gather(
            *(self._health_one(item) for item in items), return_exceptions=True,
        )
        result = []
        for item, outcome in zip(items, probed):
            if isinstance(outcome, Exception):
                logger.warning(
                    "Provider discovery health check failed for %s: %s",
                    item['provider'], type(outcome).__name__,
                )
                outcome = {**item, 'health_status': 'unavailable'}
            result.append(outcome)
        return result

    async def _probe(self, name: str) -> tuple[bool, list, str | None, str | None]:
        """Run one provider's health + model probe with discovery timeouts."""
        provider = get_provider(name)
        failure_reason = None
        failure_message = None
        try:
            healthy = await asyncio.wait_for(
                provider.health_check(), timeout=settings.discovery_timeout_seconds
            )
            if not healthy:
                failure_reason, failure_message = failure_details(
                    ProviderUnavailableError(f'{name} health check failed'),
                    local=name == 'local',
                )
        except Exception as error:
            logger.warning(
                "Provider refresh health check failed for %s: %s", name, type(error).__name__
            )
            healthy = False
            failure_reason, failure_message = failure_details(error, local=name == 'local')

        models: list[dict] = []
        if healthy:
            try:
                models = await asyncio.wait_for(
                    provider.list_models(), timeout=settings.discovery_timeout_seconds
                )
                if not models:
                    failure_reason = 'NO_MODELS'
                    failure_message = 'The provider is reachable but returned no usable models.'
            except Exception as error:
                logger.warning(
                    "Provider model refresh failed for %s: %s", name, type(error).__name__
                )
                healthy = False
                failure_reason, failure_message = failure_details(error, local=name == 'local')
        return healthy, models, failure_reason, failure_message

    async def refresh(self, provider_name: str | None = None) -> list[dict]:
        configured_items = configured_providers()
        names = (
            [provider_name]
            if provider_name
            else [item['provider'] for item in configured_items if item['configured'] and item['enabled']]
        )
        output = []
        eligible: list[str] = []
        for name in names:
            configured = next((item for item in configured_items if item['provider'] == name), None)
            if not configured or not configured['enabled']:
                self.registry.set_provider_health(name, 'disabled')
                output.append({
                    'provider': name, 'health_status': 'disabled', 'models_discovered': 0,
                    'failure_reason': 'PROVIDER_DISABLED',
                    'failure_message': 'The provider is disabled.',
                })
                continue
            provider = get_provider(name)
            if not getattr(provider, 'configured', lambda: False)():
                self.registry.set_provider_health(name, 'unconfigured')
                output.append({
                    'provider': name, 'health_status': 'unconfigured', 'models_discovered': 0,
                    'failure_reason': 'PROVIDER_UNCONFIGURED',
                    'failure_message': 'The provider credential is not configured.',
                })
                continue
            eligible.append(name)

        # Network probes run concurrently (each bounded by the discovery
        # timeout); registry writes stay sequential below to avoid SQLite
        # contention between concurrent refresh tasks.
        probes = await asyncio.gather(
            *(self._probe(name) for name in eligible), return_exceptions=True,
        )
        for name, probe in zip(eligible, probes):
            if isinstance(probe, Exception):
                logger.warning(
                    "Provider refresh probe failed for %s: %s", name, type(probe).__name__
                )
                healthy, models = False, []
                failure_reason, failure_message = failure_details(probe, local=name == 'local')
            else:
                healthy, models, failure_reason, failure_message = probe
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
                    availability=item.get('availability', 'verified'),
                    health_status='healthy',
                    last_verified=datetime.now(timezone.utc).isoformat(),
                    deployment=item.get('deployment'),
                    # Local deployment details so the registry never confuses
                    # the same model across embedded vs remote deployments.
                    version=item.get('version'),
                    runtime=item.get('runtime'),
                    format=item.get('format'),
                    quantization=item.get('quantization'),
                    size_bytes=item.get('size_bytes'),
                    sha256=item.get('sha256'),
                    source=item.get('source', 'huggingface' if name in {'local', 'local_remote'} else None),
                    license=item.get('license'),
                    installed=item.get('installed'),
                    package_id=item.get('package_id'),
                    compatibility=item.get('compatibility', {}),
                )
                for item in models
            ]
            if normalized or healthy:
                self.registry.replace_provider(name, normalized)
            else:
                self.registry.set_provider_health(name, 'unavailable')
            output.append({
                'provider': name,
                'health_status': 'healthy' if healthy else 'unavailable',
                'models_discovered': len(normalized),
                'failure_reason': failure_reason,
                'failure_message': failure_message,
            })
        return output
