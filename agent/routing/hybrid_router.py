from dataclasses import asdict, dataclass, replace
from enum import Enum

from ..config import settings
from ..models import capabilities as cap
from ..providers.registry import provider_policy
from ..storage.context_economy import estimate_tokens
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
    estimated_context_tokens: int = 0
    capability_score: float = 0.0
    adaptive_confidence: float = 0.5
    routing_score: float = 0.0
    availability: str = 'unknown'

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
        # One cursor per eligible provider pool.  This is intentionally kept on
        # the long-lived router so cold providers receive a first attempt across
        # requests, rather than being reset on every routing decision.
        self._exploration_cursors: dict[tuple[bool, tuple[str, ...]], int] = {}

    @staticmethod
    def _context_window(model: dict) -> int | None:
        value = model.get('context_window')
        if value is None:
            value = (model.get('compatibility') or {}).get('context_window')
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _supports_tools(model: dict) -> bool:
        declared = model.get('supports_tools')
        if declared is not None:
            return declared is True
        compatibility = model.get('compatibility') or {}
        if compatibility.get('supports_tools') is not None:
            return compatibility.get('supports_tools') is True
        return cap.TOOL_USE in set(model.get('capabilities', []))

    def _capability(self, model: dict, task, context_tokens: int = 0) -> float:
        capabilities = set(model.get('capabilities', []))
        required = set(task.required_capabilities)
        if required and not required.issubset(capabilities):
            return 0.0
        if task.requires_tools and not self._supports_tools(model):
            return 0.0
        context_window = self._context_window(model)
        if context_window is not None and context_tokens > context_window:
            return 0.0
        profile = model.get('capability_profile', {})
        scores = [
            profile.get('coding_score', 0.5 if cap.CODING in required else 1.0),
            profile.get('reasoning_score', 0.5 if cap.REASONING in required else 1.0),
            profile.get('instruction_score', 0.5),
        ]
        return min(max(0.0, min(float(score), 1.0)) for score in scores)

    @staticmethod
    def _available(model: dict, local: bool) -> bool:
        if model.get('availability') != 'verified' or model.get('health_status') != 'healthy':
            return False
        if local and model.get('installed') is False:
            return False
        compatibility = model.get('compatibility') or {}
        return not any(
            compatibility.get(key) is False
            for key in ('compatible', 'app_compatible', 'runtime_compatible')
        )

    @staticmethod
    def _estimated_cost(
        model: dict, context_tokens: int, expected_output_tokens: int
    ) -> float | None:
        input_price = model.get('input_price')
        output_price = model.get('output_price')
        if input_price is None and output_price is None:
            return None
        input_cost = float(input_price or 0) * max(context_tokens, 0) / 1_000_000
        output_cost = float(output_price or 0) * max(expected_output_tokens, 0) / 1_000_000
        return input_cost + output_cost

    def _adaptive_confidence(self, model: dict, performance: dict) -> float:
        history = performance.get((model.get('provider'), model.get('model_id')), {})
        if history.get('attempts', 0) < self.MIN_ADAPTIVE_SAMPLES:
            return 0.5
        success = max(0.0, min(float(history.get('success_rate', 0)), 1.0))
        quality = max(0.0, min(float(history.get('quality_score', 0)), 1.0))
        latency = max(0.0, float(history.get('latency_ms', 0)))
        latency_score = 1.0 / (1.0 + latency / 5000.0)
        return success * .65 + quality * .25 + latency_score * .10

    @staticmethod
    def _priority_score(policy: dict) -> float:
        """Convert the UI's 0..999 priority into a routing score contribution."""
        try:
            priority = float(policy.get('routing_priority', 50))
        except (TypeError, ValueError):
            priority = 50.0
        # UI priorities conventionally use 0..100 (for example 90 and 80).
        # Values above 100 remain valid but saturate instead of overpowering
        # capability and observed reliability.
        return max(0.0, min(priority / 100.0, 1.0))

    def _next_exploration_provider(
        self, candidates: list[dict], local: bool, advance: bool
    ) -> str:
        providers = tuple(sorted({item['_routing_provider'] for item in candidates}))
        key = (local, providers)
        cursor = self._exploration_cursors.get(key, 0)
        provider = providers[cursor % len(providers)]
        if advance:
            self._exploration_cursors[key] = cursor + 1
        return provider

    def _select_model(
        self,
        models: list[dict],
        task,
        local: bool,
        excluded_providers: set[str],
        excluded_models: set[tuple[str, str]],
        performance: dict | None = None,
        context_tokens: int = 0,
        expected_output_tokens: int = 512,
        advance_exploration: bool = False,
    ) -> dict | None:
        candidates = []
        adaptive = performance or {}
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
            if not self._available(model, local):
                continue
            capability_score = self._capability(model, task, context_tokens)
            if not capability_score:
                continue
            preferred = model_id == policy.get('default_model')
            estimated_cost = self._estimated_cost(
                model, context_tokens, expected_output_tokens
            )
            cost_rank = estimated_cost if estimated_cost is not None else float('inf')
            history = adaptive.get((provider, model_id), {})
            attempts = int(history.get('attempts', 0) or 0)
            confidence = self._adaptive_confidence(model, adaptive)
            priority_score = self._priority_score(policy)
            # Reliability is strongest once sampled; capability remains a
            # material factor and UI priority is deliberately strong enough to
            # beat a small cost gap. Cost is a tie-breaker, not a provider lock.
            routing_score = (
                confidence * .50 + capability_score * .30 + priority_score * .20
            )
            enriched = {
                **model,
                '_routing_capability_score': capability_score,
                '_routing_confidence': confidence,
                '_routing_score': routing_score,
                '_routing_estimated_cost': estimated_cost,
                '_routing_context_tokens': context_tokens,
                '_routing_provider': provider,
                '_routing_attempts': attempts,
                '_routing_preferred': preferred,
                '_routing_cost_rank': cost_rank,
            }
            candidates.append(enriched)
        if not candidates:
            return None

        # A configured default is an explicit model override, so preserve its
        # established contract ahead of automated provider exploration.
        preferred_candidates = [
            item for item in candidates if item['_routing_preferred']
        ]
        if preferred_candidates:
            candidates = preferred_candidates

        # Every healthy, configured provider gets MIN_ADAPTIVE_SAMPLES before
        # cost/reliability can dominate. This avoids a free model permanently
        # starving the others of the history needed for adaptive routing.
        unexplored = [
            item for item in candidates
            if item['_routing_attempts'] < self.MIN_ADAPTIVE_SAMPLES
        ]
        pool = unexplored or candidates
        if unexplored:
            selected_provider = self._next_exploration_provider(
                unexplored, local, advance_exploration
            )
            pool = [
                item for item in unexplored
                if item['_routing_provider'] == selected_provider
            ]

        return min(
            pool,
            key=lambda item: (
                not item['_routing_preferred'],
                -item['_routing_score'],
                item['_routing_cost_rank'],
                item['_routing_provider'],
                item.get('model_id', ''),
            ),
        )

    def _rank_pool(
        self,
        models: list[dict],
        task,
        local: bool,
        performance: dict | None,
        context_tokens: int,
        expected_output_tokens: int,
    ) -> list[RoutingDecision]:
        ranked = []
        excluded_models: set[tuple[str, str]] = set()
        while True:
            model = self._select_model(
                models,
                task,
                local,
                set(),
                excluded_models,
                performance,
                context_tokens,
                expected_output_tokens,
                advance_exploration=not ranked,
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
            route=route,
            provider=model['provider'],
            model_id=model['model_id'],
            reason=reason,
            task_type=task.labels,
            complexity_score=task.complexity_score,
            tools=task.requires_tools,
            estimated_cost=model.get('_routing_estimated_cost'),
            estimated_context_tokens=model.get('_routing_context_tokens', 0),
            capability_score=model.get('_routing_capability_score', 0.0),
            adaptive_confidence=model.get('_routing_confidence', 0.5),
            routing_score=model.get('_routing_score', 0.0),
            availability=model.get('availability', 'unknown'),
        )

    def candidates(
        self,
        prompt: str,
        models: list[dict],
        performance: dict | None = None,
        context_tokens: int = 0,
        expected_output_tokens: int = 512,
        require_native_tools: bool = True,
    ) -> list[RoutingDecision]:
        """Return healthy capable models in mode-aware fallback order."""
        task = self.classifier.classify(prompt)
        if not require_native_tools and task.requires_tools:
            task = replace(task, requires_tools=[])
        estimated_context_tokens = max(0, context_tokens) + estimate_tokens(prompt)
        local = self._rank_pool(
            models, task, True, performance,
            estimated_context_tokens, expected_output_tokens,
        )
        cloud = self._rank_pool(
            models, task, False, performance,
            estimated_context_tokens, expected_output_tokens,
        )
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
        context_tokens: int = 0,
        expected_output_tokens: int = 512,
        require_native_tools: bool = True,
    ) -> RoutingDecision:
        task = self.classifier.classify(prompt)
        if cache_hit:
            return RoutingDecision(
                Route.CACHE, None, None, 'EXACT_CACHE_HIT',
                task.labels, task.complexity_score, [], 0.0,
            )
        excluded_providers = exclude_providers or set()
        excluded_models = exclude_models or set()
        for candidate in self.candidates(
            prompt,
            models,
            performance,
            context_tokens=context_tokens,
            expected_output_tokens=expected_output_tokens,
            require_native_tools=require_native_tools,
        ):
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
