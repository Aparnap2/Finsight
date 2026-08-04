"""Formula Registry models for the Enterprise Semantic Layer.

This module defines the authoritative data structures for every derived
financial metric in the FinSight platform. These are Layer 0 models with
zero internal dependencies beyond the standard library and Pydantic v2.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Data types & source system literals
# ---------------------------------------------------------------------------

DataType = Literal["Money", "Percentage", "Ratio", "Count", "Days"]
"""Canonical value types a formula can produce."""

SourceType = Literal["formula_engine", "kpi_engine", "manual"]
"""Authoritative source system that computes or maintains this formula."""


class FormulaCategory(StrEnum):
    """Business category grouping for financial formulas."""

    REVENUE = "Revenue"
    EXPENSE = "Expense"
    PROFITABILITY = "Profitability"
    LIQUIDITY = "Liquidity"
    EFFICIENCY = "Efficiency"
    BUDGETING = "Budgeting"
    VARIANCE = "Variance"
    BALANCE_SHEET = "BalanceSheet"
    CASH_FLOW = "CashFlow"
    FORECASTING = "Forecasting"


# ---------------------------------------------------------------------------
# FormulaDefinition
# ---------------------------------------------------------------------------


class FormulaDefinition(BaseModel):
    """Metadata for a single derived financial metric.

    This is a **frozen** model — once constructed it is immutable. Every
    formula carries its own dependency list, versioning window, business
    owner, and compliance classification.

    Attributes:
        formula_id: Stable unique identifier (e.g. ``"gross_margin"``).
        name: Human-readable display name.
        description: One- to two-sentence business definition.
        expression: Canonical mathematical expression referencing other
            ``formula_id`` values by name.
        depends_on: List of ``formula_id`` values this formula depends on.
        data_type: The kind of value this formula produces.
        category: Business category grouping.
        owner: Business owner (team or role).
        version: Semantic version string (default ``"1.0.0"``).
        valid_from: Date this formula version became active.
        valid_until: Optional expiry date (``None`` means currently active).
        tags: Classification and discoverability tags.
        source: Authoritative source system.
        sox_relevant: Whether this metric is subject to SOX controls.
    """

    model_config = {"frozen": True}

    formula_id: str = Field(
        description="Stable unique identifier for the formula",
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(description="Human-readable display name", min_length=1)
    description: str = Field(description="Business definition")
    expression: str = Field(
        description="Canonical formula expression referencing formula_ids",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="formula_ids this formula depends on",
    )
    data_type: DataType = Field(description="Type of value produced")
    category: FormulaCategory = Field(description="Business category")
    owner: str = Field(description="Business owner", min_length=1)
    version: str = Field(
        default="1.0.0",
        description="Semantic version string",
        pattern=r"^\d+\.\d+\.\d+$",
    )
    valid_from: date = Field(description="Date this version became active")
    valid_until: date | None = Field(
        default=None,
        description="Date superseded (None = currently active)",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Classification and discoverability tags",
    )
    source: SourceType = Field(
        description="Authoritative source system",
    )
    sox_relevant: bool = Field(
        default=False,
        description="Subject to Sarbanes-Oxley controls",
    )

    @model_validator(mode="after")
    def _validate_dates(self) -> FormulaDefinition:
        """Ensure valid_from precedes valid_until when both are set."""
        if self.valid_until is not None and self.valid_from > self.valid_until:
            msg = (
                f"valid_from ({self.valid_from}) must be before "
                f"valid_until ({self.valid_until}) for '{self.formula_id}'"
            )
            raise ValueError(msg)
        return self

    def __hash__(self) -> int:
        return hash(self.formula_id)


# ---------------------------------------------------------------------------
# FormulaDependencyGraph
# ---------------------------------------------------------------------------


class FormulaDependencyGraph:
    """Dependency DAG for formula evaluation ordering and cycle detection.

    Builds an in-memory directed graph from each formula's ``depends_on``
    list, detects cycles via DFS, and computes topological sort order for
    safe evaluation.
    """

    def __init__(self, formulas: dict[str, FormulaDefinition]) -> None:
        """Initialise the graph from a formula dictionary.

        Args:
            formulas: Mapping of ``formula_id`` → ``FormulaDefinition``.
        """
        self._formulas = formulas
        self._graph: dict[str, list[str]] = {}
        for fid, fdef in formulas.items():
            self._graph[fid] = list(fdef.depends_on)

    # ------------------------------------------------------------------
    # Cycle detection
    # ------------------------------------------------------------------

    def detect_cycles(self) -> list[list[str]]:
        """Find all elementary cycles in the dependency graph.

        Uses a standard DFS-based backtracking approach. Each returned
        list is a cycle represented as a sequence of ``formula_id``
        values where the last node depends on the first.

        Returns:
            A list of cycles, each a list of ``formula_id`` strings.
            Returns an empty list if the graph is acyclic.
        """
        cycles: list[list[str]] = []
        adjacency = self._graph

        def dfs(start: str, current: str, path: list[str], visited: set[str]) -> None:
            for neighbour in adjacency.get(current, []):
                if neighbour == start:
                    cycles.append(path + [start])
                    continue
                if neighbour not in visited:
                    visited.add(neighbour)
                    dfs(start, neighbour, path + [neighbour], visited)
                    visited.discard(neighbour)

        for node in self._graph:
            dfs(node, node, [node], set())

        # Deduplicate: keep only canonical cycle representation
        canonical: set[str] = set()
        unique_cycles: list[list[str]] = []
        for cycle in cycles:
            key = "->".join(sorted(cycle))
            if key not in canonical:
                canonical.add(key)
                unique_cycles.append(cycle)

        return unique_cycles

    # ------------------------------------------------------------------
    # Topological sort
    # ------------------------------------------------------------------

    def topological_sort(self) -> list[FormulaDefinition]:
        """Return formulas in dependency order (dependencies before dependents).

        Uses Kahn's algorithm. Raises ``ValueError`` if the graph contains
        a cycle.

        Returns:
            List of ``FormulaDefinition`` in safe evaluation order.

        Raises:
            ValueError: If a cycle is detected in the dependency graph.
        """
        cycles = self.detect_cycles()
        if cycles:
            cycle_str = "; ".join(" -> ".join(c) for c in cycles)
            msg = f"Circular dependencies detected: {cycle_str}"
            raise ValueError(msg)

        # Build in-degree map
        in_degree: dict[str, int] = {fid: 0 for fid in self._graph}
        for fid, deps in self._graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[fid] = in_degree.get(fid, 0) + 1

        # Start with nodes that have no dependencies
        queue: list[str] = [fid for fid, deg in in_degree.items() if deg == 0]
        sorted_ids: list[str] = []

        while queue:
            node = queue.pop(0)
            sorted_ids.append(node)
            for fid, deps in self._graph.items():
                if node in deps:
                    in_degree[fid] -= 1
                    if in_degree[fid] == 0:
                        queue.append(fid)

        if len(sorted_ids) != len(self._graph):
            msg = "Failed to compute topological sort — graph may contain a cycle"
            raise ValueError(msg)

        return [self._formulas[fid] for fid in sorted_ids]

    # ------------------------------------------------------------------
    # Dependency / impact analysis
    # ------------------------------------------------------------------

    def dependencies_of(self, formula_id: str) -> list[FormulaDefinition]:
        """Return all transitive dependencies of a formula.

        Args:
            formula_id: The formula to look up.

        Returns:
            List of ``FormulaDefinition`` that ``formula_id`` depends on
            (directly or transitively), in topological order.
        """
        visited: set[str] = set()
        result: list[FormulaDefinition] = []

        def _walk(fid: str) -> None:
            for dep in self._graph.get(fid, []):
                if dep not in visited:
                    visited.add(dep)
                    _walk(dep)
                    result.append(self._formulas[dep])

        _walk(formula_id)
        return result

    def dependents_of(self, formula_id: str) -> list[FormulaDefinition]:
        """Return all formulas that directly depend on the given formula.

        Args:
            formula_id: The formula to look up.

        Returns:
            List of ``FormulaDefinition`` that directly reference
            ``formula_id`` in their ``depends_on``.
        """
        return [
            fdef
            for fdef in self._formulas.values()
            if formula_id in fdef.depends_on
        ]

    def impact_analysis(self, formula_id: str) -> dict[str, Any]:
        """Run a full impact analysis for changing a formula.

        Returns the chain of formulas that would be affected, grouped by
        the distance (degree of separation) from the changed formula.

        Args:
            formula_id: The formula being changed.

        Returns:
            Dict with keys ``"changed"``, ``"direct_dependents"``,
            ``"transitive_dependents"``, and ``"all_affected"``.
        """
        changed = self._formulas[formula_id]
        direct = self.dependents_of(formula_id)

        transitive: set[str] = set()
        queue: list[str] = [f.formula_id for f in direct]
        while queue:
            fid = queue.pop(0)
            if fid in transitive:
                continue
            transitive.add(fid)
            for dep_fid, dep_fdef in self._formulas.items():
                if fid in dep_fdef.depends_on:
                    queue.append(dep_fid)

        all_affected = {f.formula_id for f in direct} | transitive

        return {
            "changed": changed,
            "direct_dependents": direct,
            "transitive_dependents": [
                self._formulas[fid] for fid in sorted(transitive)
            ],
            "all_affected": [
                self._formulas[fid] for fid in sorted(all_affected)
            ],
        }


# ---------------------------------------------------------------------------
# FormulaRegistry
# ---------------------------------------------------------------------------


class FormulaRegistry:
    """Authoritative catalog of every derived financial metric.

    The registry validates that:
    - Each ``formula_id`` is unique
    - Every ``depends_on`` reference points to an already-registered formula
    - ``valid_from`` precedes ``valid_until`` (enforced by ``FormulaDefinition``)
    - Once frozen, no further registrations are allowed

    Typical usage::

        registry = FormulaRegistry()
        registry.register(FormulaDefinition(...))
        registry.freeze()
    """

    def __init__(self) -> None:
        self._formulas: dict[str, FormulaDefinition] = {}
        self._frozen: bool = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, formula: FormulaDefinition) -> None:
        """Register a single formula definition.

        Args:
            formula: The ``FormulaDefinition`` to register.

        Raises:
            RuntimeError: If the registry has been frozen.
            ValueError: If the ``formula_id`` is a duplicate or a
                dependency references an unknown formula.
        """
        if self._frozen:
            msg = "Cannot register — FormulaRegistry is frozen"
            raise RuntimeError(msg)

        if formula.formula_id in self._formulas:
            msg = f"Formula '{formula.formula_id}' is already registered"
            raise ValueError(msg)

        # Validate that all dependencies exist
        for dep_id in formula.depends_on:
            if dep_id not in self._formulas:
                msg = (
                    f"Formula '{formula.formula_id}' depends on "
                    f"'{dep_id}' which is not yet registered"
                )
                raise ValueError(msg)

        self._formulas[formula.formula_id] = formula

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, formula_id: str) -> FormulaDefinition:
        """Retrieve a formula by its identifier.

        Args:
            formula_id: The unique formula identifier.

        Returns:
            The matching ``FormulaDefinition``.

        Raises:
            KeyError: If the formula is not found.
        """
        if formula_id not in self._formulas:
            msg = f"Formula '{formula_id}' not found in registry"
            raise KeyError(msg)
        return self._formulas[formula_id]

    def __getitem__(self, formula_id: str) -> FormulaDefinition:
        return self.lookup(formula_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_by_category(
        self,
        category: FormulaCategory,
    ) -> list[FormulaDefinition]:
        """Return all formulas in a given category.

        Args:
            category: The ``FormulaCategory`` to filter by.

        Returns:
            List of ``FormulaDefinition`` in the category.
        """
        return [f for f in self._formulas.values() if f.category == category]

    def list_by_tag(self, tag: str) -> list[FormulaDefinition]:
        """Return all formulas that have a given tag.

        Args:
            tag: The tag value to filter by.

        Returns:
            List of ``FormulaDefinition`` containing the tag.
        """
        return [f for f in self._formulas.values() if tag in f.tags]

    def list_by_owner(self, owner: str) -> list[FormulaDefinition]:
        """Return all formulas owned by a given team or role.

        Args:
            owner: The owner name to filter by.

        Returns:
            List of ``FormulaDefinition`` owned by ``owner``.
        """
        return [f for f in self._formulas.values() if f.owner == owner]

    def search(self, query: str) -> list[FormulaDefinition]:
        """Case-insensitive search across formula name and description.

        Args:
            query: Search string.

        Returns:
            List of matching ``FormulaDefinition``.
        """
        q = query.lower()
        return [
            f
            for f in self._formulas.values()
            if q in f.name.lower() or q in f.description.lower()
        ]

    # ------------------------------------------------------------------
    # Dependency resolution
    # ------------------------------------------------------------------

    def resolve_dependencies(
        self,
        formula_id: str,
    ) -> list[FormulaDefinition]:
        """Resolve all dependencies for a formula in evaluation order.

        Uses ``FormulaDependencyGraph`` to compute the topological sort
        of all transitive dependencies.

        Args:
            formula_id: The formula to resolve dependencies for.

        Returns:
            List of ``FormulaDefinition`` in topological order
            (dependencies first, requested formula last).

        Raises:
            KeyError: If ``formula_id`` is not found.
            ValueError: If circular dependencies are detected.
        """
        if formula_id not in self._formulas:
            msg = f"Formula '{formula_id}' not found in registry"
            raise KeyError(msg)

        graph = FormulaDependencyGraph(self._formulas)
        topo = graph.topological_sort()

        # Return everything from the topological sort that is either the
        # requested formula or a transitive dependency of it. We slice
        # from the first occurrence of a dependency through the formula.
        all_deps: set[str] = {formula_id}
        for dep in graph.dependencies_of(formula_id):
            all_deps.add(dep.formula_id)

        return [f for f in topo if f.formula_id in all_deps]

    # ------------------------------------------------------------------
    # Freeze / lifecycle
    # ------------------------------------------------------------------

    def freeze(self) -> None:
        """Lock the registry against further modifications."""
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        """Whether the registry has been frozen."""
        return self._frozen

    @property
    def all(self) -> list[FormulaDefinition]:
        """Return every registered formula definition."""
        return list(self._formulas.values())

    @property
    def size(self) -> int:
        """Number of registered formulas."""
        return len(self._formulas)

    @property
    def graph(self) -> FormulaDependencyGraph:
        """Dependency graph for the entire registry."""
        return FormulaDependencyGraph(self._formulas)

    # ------------------------------------------------------------------
    # Bulk registration
    # ------------------------------------------------------------------

    def register_many(self, formulas: list[FormulaDefinition]) -> None:
        """Register multiple formulas in dependency-safe order.

        Sorts formulas topologically before registering so that
        dependencies are registered before their dependents.

        Args:
            formulas: Formulas to register. Must include all dependencies.

        Raises:
            RuntimeError: If registry is frozen.
            ValueError: If a formula_id is duplicate or a dependency
                is missing.
        """
        if self._frozen:
            msg = "Cannot register — FormulaRegistry is frozen"
            raise RuntimeError(msg)

        # Pre-register into a scratch dict to validate cross-references
        scratch: dict[str, FormulaDefinition] = dict(self._formulas)
        for f in formulas:
            if f.formula_id in scratch:
                msg = f"Formula '{f.formula_id}' is already registered"
                raise ValueError(msg)
            for dep_id in f.depends_on:
                if dep_id not in scratch:
                    msg = (
                        f"Formula '{f.formula_id}' depends on "
                        f"'{dep_id}' which is not in the batch"
                    )
                    raise ValueError(msg)
            scratch[f.formula_id] = f

        # Topologically sort before committing
        graph = FormulaDependencyGraph(scratch)
        ordered = graph.topological_sort()

        for f in ordered:
            if f.formula_id not in self._formulas:
                self._formulas[f.formula_id] = f

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Export the entire registry as a YAML string.

        Requires ``PyYAML`` to be installed.

        Returns:
            YAML-formatted string of all registered formulas.
        """
        import yaml

        records: list[dict[str, Any]] = []
        for formula in self._formulas.values():
            record: dict[str, Any] = formula.model_dump(
                mode="json",
                exclude_none=True,
                by_alias=True,
            )
            record["valid_from"] = str(record["valid_from"])
            if "valid_until" in record and record["valid_until"] is not None:
                record["valid_until"] = str(record["valid_until"])
            records.append(record)

        result: Any = yaml.dump(
            {"formulas": records},
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        )
        return str(result)
