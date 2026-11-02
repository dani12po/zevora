"""Deterministic promotion gates for learned artifacts."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationResult:
    accepted: bool
    confidence: float
    reasons: tuple[str, ...]


def evaluate_outcome(*, success: bool, verified: bool, quality_score: float,
                     observations: int = 1, min_quality: float = .70,
                     min_observations: int = 2) -> EvaluationResult:
    reasons = []
    if not success:
        reasons.append('task_failed')
    if not verified:
        reasons.append('not_verified')
    if quality_score < min_quality:
        reasons.append('quality_below_threshold')
    if observations < min_observations:
        reasons.append('insufficient_observations')
    confidence = max(0.0, min(1.0, quality_score * min(1.0, observations / max(1, min_observations))))
    return EvaluationResult(not reasons, confidence, tuple(reasons))
