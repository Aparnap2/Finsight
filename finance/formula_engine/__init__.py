"""Formula Engine — deterministic core for all financial calculations.

All monetary values use decimal.Decimal (never float).
No LLM calls. Pure Python, fully tested.

Exported Public API:
    Formula, FormulaRegistry        — formula definitions & registry
    DependencyResolver              — topological sort for evaluation order
    FormulaEvaluator, EvaluationContext, EvaluationError — orchestration
"""

from finance.formula_engine.formula_registry import Formula, FormulaRegistry
from finance.formula_engine.dependency_resolver import DependencyResolver
from finance.formula_engine.evaluator import FormulaEvaluator, EvaluationContext, EvaluationError

__all__ = [
    "Formula",
    "FormulaRegistry",
    "DependencyResolver",
    "FormulaEvaluator",
    "EvaluationContext",
    "EvaluationError",
]
