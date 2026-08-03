"""Formula lineage — dependency graph over the elevated formula registry.

The lineage answers three questions for any formula:

* *Upstream*: which formulas feed into it (its dependency closure)?
* *Downstream*: which formulas consume it (its dependents)?
* *Impact*: if a formula changes, what else is affected?

The lineage operates on registry-v1 records loaded from ``registry.yaml``
(see :mod:`business.formula_registry.loader`), which carry an explicit
``dependencies`` list of ``formula_id`` values. Cycles are detected and
reported rather than silently swallowed.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

# DFS colouring states used by :meth:`FormulaLineage.detect_cycles`.
_WHITE = 0  # unvisited
_GREY = 1  # on the current DFS stack
_BLACK = 2  # fully explored

# ---------------------------------------------------------------------------
# Lineage graph
# ---------------------------------------------------------------------------


class FormulaLineage:
    """Dependency lineage built from a list of registry records.

    Attributes:
        records: Mapping of ``formula_id`` → record dict.
    """

    def __init__(self, records: list[dict[str, Any]]) -> None:
        """Build the lineage graph from registry records.

        Args:
            records: List of registry-v1 formula records.

        Raises:
            ValueError: If records contain duplicate ids or a dependency
                references an unknown formula.
        """
        self.records: dict[str, dict[str, Any]] = {}
        for record in records:
            formula_id = str(record["id"])
            if formula_id in self.records:
                msg = f"Duplicate formula id '{formula_id}' in lineage"
                raise ValueError(msg)
            self.records[formula_id] = record

        # Build adjacency: parent → children (dependents), child → parents.
        self._dependents: dict[str, list[str]] = defaultdict(list)
        for formula_id, record in self.records.items():
            for dep in record.get("dependencies", []):
                dep_id = str(dep)
                if dep_id not in self.records:
                    msg = (
                        f"Formula '{formula_id}' depends on unknown "
                        f"'{dep_id}'"
                    )
                    raise ValueError(msg)
                self._dependents[dep_id].append(formula_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def dependencies_of(self, formula_id: str) -> list[str]:
        """Return the transitive dependency closure of a formula.

        Args:
            formula_id: The formula to resolve upstream.

        Returns:
            Sorted list of ``formula_id`` values it depends on (direct
            or transitive), excluding itself.

        Raises:
            KeyError: If the formula is unknown.
        """
        self._require(formula_id)
        seen: set[str] = set()
        queue = deque(self.records[formula_id].get("dependencies", []))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.records[current].get("dependencies", []))
        return sorted(seen)

    def dependents_of(self, formula_id: str) -> list[str]:
        """Return the formulas that directly depend on a formula.

        Args:
            formula_id: The formula to resolve downstream.

        Returns:
            Sorted list of ``formula_id`` values that consume it.

        Raises:
            KeyError: If the formula is unknown.
        """
        self._require(formula_id)
        return sorted(self._dependents.get(formula_id, []))

    def find_leaves(self) -> list[str]:
        """Return formulas that no other formula depends on.

        Leaves are the top-level metrics consumed by reports and agents
        (nothing upstream of them in the registry).

        Returns:
            Sorted list of leaf ``formula_id`` values.
        """
        return sorted(
            formula_id
            for formula_id in self.records
            if not self._dependents.get(formula_id)
        )

    def impact_analysis(self, formula_id: str) -> dict[str, Any]:
        """Return the blast radius of changing a formula.

        Args:
            formula_id: The formula being changed.

        Returns:
            Dict with ``changed``, ``direct_dependents``,
            ``transitive_dependents``, and ``all_affected`` keys.

        Raises:
            KeyError: If the formula is unknown.
        """
        self._require(formula_id)
        direct = self.dependents_of(formula_id)

        transitive: set[str] = set()
        queue = deque(direct)
        while queue:
            current = queue.popleft()
            if current in transitive:
                continue
            transitive.add(current)
            queue.extend(self.dependents_of(current))

        all_affected = set(direct) | transitive
        return {
            "changed": formula_id,
            "direct_dependents": direct,
            "transitive_dependents": sorted(transitive - set(direct)),
            "all_affected": sorted(all_affected),
        }

    def detect_cycles(self) -> list[list[str]]:
        """Detect dependency cycles via DFS colouring.

        Returns:
            List of cycles, each a list of ``formula_id`` values in
            cycle order. Empty when the graph is acyclic.
        """
        colour: dict[str, int] = {fid: _WHITE for fid in self.records}
        stack: list[str] = []
        cycles: list[list[str]] = []

        def visit(node: str) -> None:
            colour[node] = _GREY
            stack.append(node)
            for dep in self.records[node].get("dependencies", []):
                if colour[dep] == _GREY:
                    start = stack.index(dep)
                    cycles.append(stack[start:] + [dep])
                elif colour[dep] == _WHITE:
                    visit(dep)
            stack.pop()
            colour[node] = _BLACK

        for node in self.records:
            if colour[node] == _WHITE:
                visit(node)

        # De-duplicate cycles with identical node sets.
        seen: set[str] = set()
        unique: list[list[str]] = []
        for cycle in cycles:
            key = "->".join(sorted(cycle))
            if key not in seen:
                seen.add(key)
                unique.append(cycle)
        return unique

    def __contains__(self, formula_id: str) -> bool:
        """Check whether a formula id is present in the lineage."""
        return formula_id in self.records

    def __len__(self) -> int:
        """Return the number of formulas in the lineage."""
        return len(self.records)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require(self, formula_id: str) -> None:
        """Raise ``KeyError`` if a formula id is unknown.

        Args:
            formula_id: The id to check.

        Raises:
            KeyError: If the id is not in the lineage.
        """
        if formula_id not in self.records:
            msg = f"Formula '{formula_id}' not found in lineage"
            raise KeyError(msg)
