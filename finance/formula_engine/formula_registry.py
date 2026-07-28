"""Formula Definitions — the deterministic core of all financial calculations.

All monetary values use decimal.Decimal (never float).
No LLM calls. Pure Python.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Callable


class Formula:
    """A single deterministic financial formula.

    Attributes:
        name: Unique identifier for this formula.
        description: Human-readable description.
        category: One of "ratio", "aggregation", "variance", "growth", "margin".
        inputs: Account codes or KPI names this formula consumes.
        output_name: The key under which the result is stored (used for
            dependency resolution).
        fn: The deterministic callable. Signature must match the declared
            ``inputs`` (keyword arguments with Decimal values). Returns Decimal.
    """

    def __init__(
        self,
        name: str,
        description: str,
        category: str,
        inputs: list[str],
        output_name: str,
        fn: Callable[..., Decimal],
    ) -> None:
        self.name = name
        self.description = description
        self.category = category
        self.inputs = list(inputs)
        self.output_name = output_name
        self.fn = fn

    def __repr__(self) -> str:
        return (
            f"Formula(name={self.name!r}, category={self.category!r}, "
            f"inputs={self.inputs!r}, output_name={self.output_name!r})"
        )


class FormulaRegistry:
    """Registry of all known financial formulas.

    Provides registration, lookup, category filtering, and direct evaluation
    of individual formulas.
    """

    def __init__(self) -> None:
        self._registry: dict[str, Formula] = {}

    # ── Registration / Lookup ────────────────────────────────────────────────

    def register(self, formula: Formula) -> None:
        """Register a formula.

        Raises ValueError if a formula with the same ``name`` is already
        registered.
        """
        if formula.name in self._registry:
            raise ValueError(
                f"Formula '{formula.name}' already registered"
            )
        self._registry[formula.name] = formula

    def get(self, name: str) -> Formula:
        """Retrieve a formula by name.

        Raises KeyError if not found.
        """
        if name not in self._registry:
            raise KeyError(f"Formula '{name}' not found in registry")
        return self._registry[name]

    def list_by_category(self, category: str) -> list[Formula]:
        """Return all formulas belonging to *category*."""
        return [f for f in self._registry.values() if f.category == category]

    def names(self) -> list[str]:
        """Return all registered formula names."""
        return list(self._registry.keys())

    # ── Direct evaluation ────────────────────────────────────────────────────

    def evaluate(self, name: str, inputs: dict[str, Decimal]) -> Decimal:
        """Evaluate a single formula by name with the given *inputs*.

        Raises KeyError if the formula or any required input is missing.
        """
        formula = self.get(name)
        missing = [k for k in formula.inputs if k not in inputs]
        if missing:
            raise KeyError(
                f"Missing inputs for '{name}': {missing}"
            )
        kwargs = {k: inputs[k] for k in formula.inputs}
        return formula.fn(**kwargs)

    def evaluate_all(
        self, inputs: dict[str, Decimal]
    ) -> dict[str, Decimal]:
        """Evaluate every registered formula, chaining outputs as inputs.

        Formulas are evaluated in topological order so that dependencies
        (one formula's output being another formula's input) are resolved
        correctly.

        Raises KeyError if any required input (seed or formula output)
        cannot be satisfied, or ValueError if a circular dependency is
        detected.
        """
        # ── Build dependency graph ────────────────────────────────────────
        dep_map: dict[str, set[str]] = {}
        for name, f in self._registry.items():
            deps: set[str] = set()
            for inp in f.inputs:
                for other_name, other in self._registry.items():
                    if other.output_name == inp:
                        deps.add(other_name)
            dep_map[name] = deps

        # ── Topological sort (Kahn's algorithm) ───────────────────────────
        in_degree: dict[str, int] = {
            name: len(deps) for name, deps in dep_map.items()
        }
        reverse_deps: dict[str, list[str]] = defaultdict(list)
        for name, deps in dep_map.items():
            for dep in deps:
                reverse_deps[dep].append(name)

        from collections import deque

        queue = deque(name for name, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while queue:
            name = queue.popleft()
            order.append(name)
            for dependent in reverse_deps.get(name, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._registry):
            raise ValueError(
                "Circular dependency detected in formula registry"
            )

        # ── Evaluate in order ─────────────────────────────────────────────
        results: dict[str, Decimal] = dict(inputs)
        for name in order:
            formula = self._registry[name]
            kwargs = {k: results[k] for k in formula.inputs}
            results[formula.output_name] = formula.fn(**kwargs)

        # Return only formula outputs (strip seed inputs)
        return {
            f.output_name: results[f.output_name]
            for f in self._registry.values()
        }
