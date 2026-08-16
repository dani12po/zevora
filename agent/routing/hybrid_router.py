from dataclasses import asdict, dataclass
from enum import Enum

from ..config import settings
from ..models import capabilities as cap
from ..providers.registry import provider_policy
from .task_classifier import TaskClassifier


class Route(str, Enum):
    CACHE = 'CACHE'
    LOCAL = 'LOCAL'
    CLOUD = 'CLOUD'
    UNAVAILABLE = 'UNAVAILABLE'


@dataclass(frozen=True)
class RoutingDecision:
    route: Route
    provider: str | None
    model_id: str | None
    reason: str
    task_type: list[str]
    complexity_score: float
    tools: list[str]
    estimated_cost: float | None

    def to_dict(self):
        return {**asdict(self), 'route': self.route.value}


class AdaptiveHybridRouter:
    """Rank local and cloud providers; inference remains provider-owned."""

    MIN_ADAPTIVE_SAMPLES = 3
    # Architecture and migration rules currently raise complexity to .53;
    # keep those tasks cloud-first while routine prompts remain local-first.
    CLOUD_FIRST_COMPLEXITY = .50

    def __init__(self, classifier=None):
        self.classifier = classifier or TaskClassifier()

    def _capability(self, model: dict, task) -> float:
        capabilities = set(model.get('capabilities', []))
        required = set(task.required_capabilities)
        if required and not required.issubset(capabilities):
            return 0.0
        profile = model.get('capability_profile', {})
        scores = [
            profile.get('coding_score', 0.5 if cap.CODING in required else 1.0),
            profile.get('reasoning_score', 0.5 if cap.REASONING in required else 1.0),
            profile.get('instruction_score', 0.5),
        ]
        return min(scores)

    def _adaptive_confidence(self, model: dict, performance: dict) -> float:
        history = performance.get((model.get('provider'), model.get('model_id')), {})
        if history.get('attempts', 0) < self.MIN_ADAPTIVE_SAMPLES:
            return 0.5
        success = max(0.0, min(float(history.get('success_rate', 0)), 1.0))
        quality = max(0.0, min(float(history.get('quality_score', 0)), 1.0))
        latency = max(0.0, float(history.get('latency_ms', 0)))
        latency_score = 1.0 / (1.0 + latency / 5000.0)
        return success * .65 + quality * .25 + latency_score * .10

    def _select_model(
        self,
        models: list[dict],
        task,
        local: bool,
        excluded_providers: set[str],
        excluded_models: set[tuple[str, str]],
        performance: dict | None = None,
    ) -> dict | None:
        candidates = []
        adaptive = performance or {}
        use_history = any(
            item.get('attempts', 0) >= self.MIN_ADAPTIVE_SAMPLES
            for item in adaptive.values()
        )
        for model in models:
            provider = str(model.get('provider') or '').lower()
            if (provider == 'local') != local:
                continue
            model_id = str(model.get('model_id') or '')
            policy = provider_policy(provider)
            if (
                provider in excluded_providers
                or (provider, model_id) in excluded_models
                or not policy['enabled']
            ):
                continue
            if (
                model.get('availability') != 'verified'
                or model.get('health_status') != 'healthy'
            ):
                continue
            score = self._capability(model, task)
            if not score:
                continue
            preferred = model_id == policy.get('default_model')
            cost = (
                model.get('input_price')
                if model.get('input_price') is not None
                else float('inf')
            )
            confidence = (
                self._adaptive_confidence(model, adaptive) if use_history else .5
            )
            candidates.append((
                -confidence, not preferred, cost, -score,
                -policy['routing_priority'], model,
            ))
        return min(candidates, key=lambda item: item[:-1])[-1] if candidates else None

    def _rank_pool(
        self, models: list[dict], task, local: bool, performance: dict | None
    ) -> list[RoutingDecision]:
        ranked = []
        excluded_models: set[tuple[str, str]] = set()
        while True:
            model = self._select_model(
                models, task, local, set(), excluded_models, performance
            )
            if not model:
                return ranked
            route = Route.LOCAL if local else Route.CLOUD
            kind = 'LOCAL' if local else 'CLOUD'
            reason = f'BEST_{kind}_MATCH' if not ranked else f'ALTERNATE_{kind}_MATCH'
            ranked.append(self._decision(task, model, route, reason))
            excluded_models.add((
                str(model.get('provider') or '').lower(),
                str(model.get('model_id') or ''),
            ))

    @staticmethod
    def _decision(
        task, model: dict, route: Route, reason: str
    ) -> RoutingDecision:
        return RoutingDecision(
            route, model['provider'], model['model_id'], reason,
            task.labels, task.complexity_score, task.requires_tools, None,
        )

    def candidates(
        self, prompt: str, models: list[dict], performance: dict | None = None
    ) -> list[RoutingDecision]:
        """Return healthy capable models in mode-aware fallback order."""
        task = self.classifier.classify(prompt)
        local = self._rank_pool(models, task, True, performance)
        cloud = self._rank_pool(models, task, False, performance)
        mode = settings.routing_mode.upper()
        if mode == 'LOCAL_ONLY':
            return local
        if mode == 'CLOUD_ONLY':
            return cloud
        cloud_first = (
            task.complexity_score >= self.CLOUD_FIRST_COMPLEXITY
            or cap.VISION in task.required_capabilities
        )
        return (cloud + local) if cloud_first else (local + cloud)

    def decide(
        self,
        prompt: str,
        models: list[dict],
        resource_ok: bool = True,
        cache_hit: bool = False,
        exclude_providers: set[str] | None = None,
        exclude_models: set[tuple[str, str]] | None = None,
        performance: dict | None = None,
    ) -> RoutingDecision:
        task = self.classifier.classify(prompt)
        if cache_hit:
            return RoutingDecision(
                Route.CACHE, None, None, 'EXACT_CACHE_HIT',
                task.labels, task.complexity_score, [], 0.0,
            )
        excluded_providers = exclude_providers or set()
        excluded_models = exclude_models or set()
        for candidate in self.candidates(prompt, models, performance):
            if (
                candidate.provider not in excluded_providers
                and (candidate.provider or '', candidate.model_id or '')
                not in excluded_models
                and (resource_ok or candidate.route is not Route.LOCAL)
            ):
                return candidate
        return RoutingDecision(
            Route.UNAVAILABLE, None, None, 'NO_CAPABLE_MODEL',
            task.labels, task.complexity_score, task.requires_tools, None,
        )
