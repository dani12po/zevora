"""Validated knowledge, skill, and future model evolution."""
from .engine import EvolutionEngine
from .evaluator import EvaluationResult, evaluate_outcome

__all__ = ['EvolutionEngine', 'EvaluationResult', 'evaluate_outcome']
