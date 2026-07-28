"""Formula Evaluator — high-level orchestration of formula evaluation.

Manages evaluation context, error collection, and partial evaluation of
formula subsets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finance.formula_engine.formula_registry import FormulaRegistry
    from finance.formula_engine.dependency_resolver import DependencyResolver


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class EvaluationError:
    """Describes a single evaluation failure."""

    formula_name: str
    input_name: str | None = None
    message: str = ""

    def __repr__(self) -> str:
        return (
            f"EvaluationError(formula={self.formula_name!r}, "
            f"input={self.input_name!r}, msg={self.message!r})"
        )


@dataclass
class EvaluationContext:
    """Holds the state and results of a formula evaluation run."""

    values: dict[str, Decimal] = field(default_factory=dict)
    """All known values — seed inputs plus computed formula outputs."""

    evaluated: set[str] = field(default_factory=set)
    """Names of formulas that were successfully evaluated."""

    errors: list[EvaluationError] = field(default_factory=list)
    """Any errors encountered during evaluation."""

    def __repr__(self) -> str:
        return (
            f"EvaluationContext(values={len(self.values)}, "
            f"evaluated={len(self.evaluated)}, "
            f"errors={len(self.errors)})"
        )


# ── Evaluator ─────────────────────────────────────────────────────────────────


class FormulaEvaluator:
    """High-level evaluator that manages the evaluation lifecycle.

    Handles dependency resolution, partial evaluation, and error collection
    with clear messages for missing inputs.
    """

    def __init__(
        self,
        registry: FormulaRegistry,
        resolver: DependencyResolver,
    ) -> None:
        self._registry = registry
        self._resolver = resolver

    # ── Full evaluation ──────────────────────────────────────────────────────

    def evaluate(
        self, seed_inputs: dict[str, Decimal]
    ) -> EvaluationContext:
        """Evaluate all registered formulas in dependency order.

        *seed_inputs* are the externally-provided raw values (account balances,
        KPIs, headcount, etc.).

        Returns an ``EvaluationContext`` containing all computed values,
        the set of successfully-evaluated formulas, and any errors.
        """
        context = EvaluationContext(values=dict(seed_inputs))

        try:
            order = self._resolver.resolve(
                self._registry, set(seed_inputs.keys())
            )
        except ValueError as exc:
            context.errors.append(
                EvaluationError(
                    formula_name="(resolver)",
                    message=str(exc),
                )
            )
            return context

        self._evaluate_in_order(context, order)
        return context

    # ── Partial evaluation ───────────────────────────────────────────────────

    def evaluate_partial(
        self,
        seed_inputs: dict[str, Decimal],
        formulas: list[str],
    ) -> EvaluationContext:
        """Evaluate a subset of formulas.

        Only the named *formulas* (and any formulas they transitively depend
        on) are evaluated. This is useful for targeted recalculation.

        Returns an ``EvaluationContext``.
        """
        # Verify requested formulas exist
        for name in formulas:
            if name not in self._registry._registry:
                context = EvaluationContext(values=dict(seed_inputs))
                context.errors.append(
                    EvaluationError(
                        formula_name=name,
                        message=f"Formula '{name}' not found in registry",
                    )
                )
                return context

        # Compute transitive closure of dependencies
        needed: set[str] = set(formulas)
        visited: set[str] = set()
        stack: list[str] = list(formulas)

        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            deps = self._resolver.depends_on(name, self._registry)
            for dep in deps:
                if dep not in visited:
                    needed.add(dep)
                    stack.append(dep)

        # Resolve full order but only evaluate what's needed
        try:
            full_order = self._resolver.resolve(
                self._registry, set(seed_inputs.keys())
            )
        except ValueError as exc:
            context = EvaluationContext(values=dict(seed_inputs))
            context.errors.append(
                EvaluationError(
                    formula_name="(resolver)",
                    message=str(exc),
                )
            )
            return context

        # Filter to only what's needed
        order = [n for n in full_order if n in needed]

        context = EvaluationContext(values=dict(seed_inputs))
        self._evaluate_in_order(context, order)
        return context

    # ── Internal ─────────────────────────────────────────────────────────────

    def _evaluate_in_order(
        self, context: EvaluationContext, order: list[str]
    ) -> None:
        """Evaluate formulas in the given order, collecting errors."""
        for formula_name in order:
            formula = self._registry.get(formula_name)

            # Check for missing inputs
            missing = [
                inp for inp in formula.inputs if inp not in context.values
            ]
            if missing:
                context.errors.append(
                    EvaluationError(
                        formula_name=formula_name,
                        input_name=missing[0],
                        message=(
                            f"Missing required input '{missing[0]}' "
                            f"for formula '{formula_name}'. "
                            f"All missing: {missing}"
                        ),
                    )
                )
                continue

            # Evaluate
            try:
                kwargs = {k: context.values[k] for k in formula.inputs}
                result = formula.fn(**kwargs)
                context.values[formula.output_name] = result
                context.evaluated.add(formula_name)
            except Exception as exc:
                context.errors.append(
                    EvaluationError(
                        formula_name=formula_name,
                        message=str(exc),
                    )
                )
