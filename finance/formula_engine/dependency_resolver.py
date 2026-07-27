"""Formula Dependency Resolver — determines evaluation order via topological sort.

The resolver computes which formulas depend on which by matching formula
``output_name`` values to other formula ``inputs``. This enables correct
evaluation ordering and cycle detection.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finance.formula_engine.formula_registry import FormulaRegistry


class DependencyResolver:
    """Resolves formula evaluation order so that dependencies are honoured.

    A formula *A* depends on formula *B* when *B*'s ``output_name`` appears in
    *A*'s ``inputs`` list.
    """

    # ── Public API ───────────────────────────────────────────────────────────

    def resolve(
        self, formula_registry: FormulaRegistry, seed_inputs: set[str]
    ) -> list[str]:
        """Return formula names in evaluation order (topological sort).

        *seed_inputs* are the names of raw input values (account codes, KPIs)
        that are provided externally and are NOT produced by any formula.

        Raises ``ValueError`` if a circular dependency is detected.
        """
        graph = self._build_graph(formula_registry)
        order = self._topological_sort(graph)
        return order

    def has_cycle(self, formula_registry: FormulaRegistry) -> bool:
        """Return True if the registry contains a circular dependency."""
        graph = self._build_graph(formula_registry)
        try:
            self._topological_sort(graph)
            return False
        except ValueError:
            return True

    def depends_on(
        self, formula_name: str, formula_registry: FormulaRegistry
    ) -> list[str]:
        """Return the list of formula names that *formula_name* depends on."""
        formula = formula_registry.get(formula_name)
        deps: list[str] = []
        for inp in formula.inputs:
            for other_name, other in formula_registry._registry.items():
                if other.output_name == inp:
                    deps.append(other_name)
        return deps

    # ── Internal helpers ────────────────────────────────────────────────────

    def _build_graph(
        self, formula_registry: FormulaRegistry
    ) -> dict[str, set[str]]:
        """Build adjacency list: formula → set of formulas it depends on."""
        graph: dict[str, set[str]] = {}
        for name, formula in formula_registry._registry.items():
            deps: set[str] = set()
            for inp in formula.inputs:
                for other_name, other in formula_registry._registry.items():
                    if other.output_name == inp:
                        deps.add(other_name)
            graph[name] = deps
        return graph

    def _topological_sort(self, graph: dict[str, set[str]]) -> list[str]:
        """Kahn's algorithm — returns names in dependency order."""
        in_degree: dict[str, int] = {
            name: len(deps) for name, deps in graph.items()
        }
        reverse_deps: dict[str, list[str]] = defaultdict(list)
        for name, deps in graph.items():
            for dep in deps:
                reverse_deps[dep].append(name)

        queue = deque(name for name, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while queue:
            name = queue.popleft()
            order.append(name)
            for dependent in reverse_deps.get(name, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(graph):
            raise ValueError(
                "Circular dependency detected in formula registry"
            )
        return order
