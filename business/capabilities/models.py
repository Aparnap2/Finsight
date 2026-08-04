"""Pydantic models for the FP&A Business Capability Map.

Defines :class:`Capability`, :class:`CapabilityTree`,
:class:`CapabilityMaturity`, and :class:`ProcessFlow` — the core
value objects that encode FinSight's understanding of which business
capabilities it supports and how they relate.

Capabilities carry a lifecycle status (see :class:`CapabilityStatus`)
as well as a finer-grained maturity rating, and are wired to the
services, events, agents, and KPIs that implement them so the registry
can feed routing and the service catalog.
"""

# mypy: disable-error-code="misc"

from __future__ import annotations

from collections.abc import Generator, Iterator
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MaturityLevel = Literal["planned", "partial", "full", "production"]


class CapabilityStatus(StrEnum):
    """Lifecycle state of a capability.

    The lifecycle is monotonic: a capability is *discovered*, then
    *implemented*, then promoted to *production*, and finally
    *deprecated*. See ``docs/14-platform/implementation-plan.md``.
    """

    DISCOVERY = "discovery"
    IMPLEMENTED = "implemented"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"


#: Mapping from the coarse maturity rating to the lifecycle status.
_MATURITY_TO_STATUS: dict[MaturityLevel, CapabilityStatus] = {
    "planned": CapabilityStatus.DISCOVERY,
    "partial": CapabilityStatus.IMPLEMENTED,
    "full": CapabilityStatus.IMPLEMENTED,
    "production": CapabilityStatus.PRODUCTION,
}


class Capability(BaseModel):
    """A single business capability in the FP&A domain.

    Each capability represents a discrete business function that
    FinSight supports. Capabilities form a tree via *parent_id*.

    Attributes:
        capability_id: Stable identifier e.g. ``cap.budgeting.create``.
        name: Human-readable name.
        description: Business description of what this capability does.
        parent_id: Identifier of the parent capability, or ``None``
            for root-level capabilities.
        supported_by: Engines and agents that implement this
            capability (e.g. ``"Variance Engine"``).
        events: Domain events this capability produces or consumes.
        maturity: How mature the implementation is.
        status: Lifecycle state; derived from *maturity* when not
            given explicitly.
        owner: Business owner (team or person).
        tags: Arbitrary classification tags.
        apis: API routes or services that expose this capability.
        agent_tools: Agent tools that exercise this capability.
        kpis: KPI identifiers this capability produces or consumes.
        policies: Policy identifiers that govern this capability.
    """

    capability_id: str = Field(
        description="Stable identifier e.g. cap.budgeting.create",
    )
    name: str = Field(description="Human-readable name")
    description: str = Field(description="Business description of this capability")
    parent_id: str | None = Field(
        default=None,
        description="Identifier of the parent capability, or None for root",
    )
    supported_by: list[str] = Field(
        default_factory=list,
        description="Engines and agents that implement this capability",
    )
    events: list[str] = Field(
        default_factory=list,
        description="Domain events this capability produces or consumes",
    )
    maturity: MaturityLevel = Field(
        default="planned",
        description="How mature the implementation is",
    )
    status: CapabilityStatus | None = Field(
        default=None,
        description="Lifecycle state; derived from maturity when not given",
    )
    owner: str = Field(
        default="FP&A Team",
        description="Business owner (team or person)",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary classification tags",
    )
    apis: list[str] = Field(
        default_factory=list,
        description="API routes or services that expose this capability",
    )
    agent_tools: list[str] = Field(
        default_factory=list,
        description="Agent tools that exercise this capability",
    )
    kpis: list[str] = Field(
        default_factory=list,
        description="KPI identifiers this capability produces or consumes",
    )
    policies: list[str] = Field(
        default_factory=list,
        description="Policy identifiers that govern this capability",
    )

    @model_validator(mode="after")
    def _derive_status(self) -> Capability:
        """Derive the lifecycle status from the maturity rating.

        Keeps the finer-grained maturity rating as the source of truth
        while exposing the four-state lifecycle used for reporting.
        """
        if self.status is None:
            self.status = _MATURITY_TO_STATUS.get(
                self.maturity,
                CapabilityStatus.DISCOVERY,
            )
        return self


class CapabilityTree(BaseModel):
    """A tree structure built from a flat list of :class:`Capability`.

    Provides traversal and query methods for navigating the FP&A
    capability hierarchy.

    Attributes:
        capabilities: Flat list of all capabilities in the tree.
    """

    capabilities: list[Capability] = Field(
        description="Flat list of all capabilities in the tree",
    )

    # ── internal caches ──────────────────────────────────────────
    _children_cache: dict[str, list[Capability]] = {}
    _parent_cache: dict[str, Capability | None] = {}
    _by_id_cache: dict[str, Capability] = {}

    def model_post_init(self, __context: Any) -> None:
        """Build internal caches after initialisation."""
        self._rebuild_caches()

    def _rebuild_caches(self) -> None:
        """Rebuild children, parent, and by-id lookup caches."""
        self._children_cache = {}
        self._parent_cache = {}
        self._by_id_cache = {}

        for cap in self.capabilities:
            self._by_id_cache[cap.capability_id] = cap

        for cap in self.capabilities:
            parent_id = cap.parent_id
            if parent_id is not None:
                self._children_cache.setdefault(parent_id, []).append(cap)
                self._parent_cache[cap.capability_id] = self._by_id_cache.get(parent_id)
            else:
                self._parent_cache[cap.capability_id] = None

    def find_by_id(self, capability_id: str) -> Capability | None:
        """Look up a capability by its identifier.

        Args:
            capability_id: The stable identifier to search for.

        Returns:
            The matching capability, or ``None`` if not found.
        """
        return self._by_id_cache.get(capability_id)

    def find_by_path(self, path: str, delimiter: str = " → ") -> list[Capability]:
        """Resolve a human-readable path to a list of capabilities.

        The path is matched by capability *name* (not id) using the
        given delimiter.  Only the first matching sequence is returned.

        Args:
            path: e.g. ``"Planning & Budgeting → Budget Creation"``.
            delimiter: Separator between names in the path.

        Returns:
            List of capabilities from root to leaf.  Empty if no match.
        """
        names = [n.strip() for n in path.split(delimiter)]
        if not names:
            return []

        def _walk(
            start: list[Capability],
            depth: int,
        ) -> list[Capability] | None:
            if depth >= len(names):
                return []
            for cap in start:
                if cap.name == names[depth]:
                    rest = _walk(self.children(cap.capability_id), depth + 1)
                    if rest is not None:
                        return [cap, *rest]
            return None

        roots = [c for c in self.capabilities if c.parent_id is None]
        result = _walk(roots, 0)
        return result or []

    def children(self, capability_id: str) -> list[Capability]:
        """Return the direct children of a capability.

        Args:
            capability_id: The parent capability's identifier.

        Returns:
            List of child capabilities (empty if leaf or unknown).
        """
        return list(self._children_cache.get(capability_id, []))

    def parents(self, capability_id: str) -> list[Capability]:
        """Return the ancestry chain from root to the given capability.

        Args:
            capability_id: Target capability identifier.

        Returns:
            Ordered list from root to the capability itself.
        """
        chain: list[Capability] = []
        current = self._by_id_cache.get(capability_id)
        while current is not None:
            chain.insert(0, current)
            pid = current.parent_id
            current = self._by_id_cache.get(pid) if pid is not None else None
        return chain

    def traverse(self, mode: str = "depth-first") -> Generator[Capability, None, None]:
        """Iterate over all capabilities in the requested order.

        Args:
            mode: ``"depth-first"`` (default) or ``"breadth-first"``.

        Yields:
            Capabilities in the specified traversal order.
        """
        roots = sorted(
            [c for c in self.capabilities if c.parent_id is None],
            key=lambda c: c.capability_id,
        )
        if mode == "breadth-first":
            yield from self._bfs(roots)
        else:
            yield from self._dfs(roots)

    def _dfs(self, nodes: list[Capability]) -> Generator[Capability, None, None]:
        """Depth-first traversal starting from *nodes*."""
        for node in nodes:
            yield node
            yield from self._dfs(
                sorted(
                    self.children(node.capability_id),
                    key=lambda c: c.capability_id,
                ),
            )

    def _bfs(self, nodes: list[Capability]) -> Generator[Capability, None, None]:
        """Breadth-first traversal starting from *nodes*."""
        queue: list[Capability] = list(nodes)
        while queue:
            node = queue.pop(0)
            yield node
            queue.extend(
                sorted(
                    self.children(node.capability_id),
                    key=lambda c: c.capability_id,
                ),
            )

    def __iter__(self) -> Iterator[Capability]:  # type: ignore[override]
        """Iterate over capabilities in depth-first order."""
        return self.traverse(mode="depth-first")

    def __len__(self) -> int:
        """Return the total number of capabilities."""
        return len(self.capabilities)

    def __contains__(self, item: object) -> bool:
        """Check membership by capability_id string or Capability object."""
        if isinstance(item, str):
            return self.find_by_id(item) is not None
        if isinstance(item, Capability):
            return self.find_by_id(item.capability_id) is not None
        return False

    def by_status(self, status: CapabilityStatus) -> list[Capability]:
        """Return capabilities currently in the given lifecycle state.

        Args:
            status: The lifecycle status to filter on.

        Returns:
            List of capabilities in that state.
        """
        return [cap for cap in self.capabilities if cap.status == status]

    def implemented_capabilities(self) -> list[Capability]:
        """Return capabilities that are at or beyond *implemented*.

        These are the capabilities the service catalog can route to:
        they are not merely discovered, they have working engines,
        agents, or tooling behind them.

        Returns:
            List of implemented capabilities.
        """
        return CapabilityMaturity(capabilities=self.capabilities).implemented()


class CapabilityMaturity(BaseModel):
    """Aggregate maturity reporting across capabilities.

    Computes counts and percentages per maturity level, optionally
    filtered by a tag or subtree.

    Attributes:
        capabilities: The capabilities to report on.
    """

    capabilities: list[Capability] = Field(
        description="The capabilities to report on",
    )

    def summary(self) -> dict[str, Any]:
        """Return a maturity summary dict with counts and percentages.

        Returns:
            Dict with keys ``"planned"``, ``"partial"``, ``"full"``,
            ``"production"``, ``"total"``, and ``"coverage_pct"``.
        """
        total = len(self.capabilities)
        if total == 0:
            return {
                "planned": 0,
                "partial": 0,
                "full": 0,
                "production": 0,
                "total": 0,
                "coverage_pct": 0.0,
            }

        levels: dict[str, int] = {
            "planned": 0,
            "partial": 0,
            "full": 0,
            "production": 0,
        }
        for cap in self.capabilities:
            levels[cap.maturity] = levels.get(cap.maturity, 0) + 1

        implemented = total - levels["planned"]
        coverage_pct = round(implemented / total * 100, 1)

        return {
            **levels,
            "total": total,
            "coverage_pct": coverage_pct,
        }

    def by_tag(self, tag: str) -> dict[str, Any]:
        """Return maturity summary filtered to capabilities with the given tag.

        Args:
            tag: Tag value to filter on.

        Returns:
            Same shape as :meth:`summary`.
        """
        filtered = [c for c in self.capabilities if tag in c.tags]
        return CapabilityMaturity(capabilities=filtered).summary()

    def by_owner(self, owner: str) -> dict[str, Any]:
        """Return maturity summary filtered to capabilities owned by *owner*.

        Args:
            owner: Owner name to filter on.

        Returns:
            Same shape as :meth:`summary`.
        """
        filtered = [c for c in self.capabilities if c.owner == owner]
        return CapabilityMaturity(capabilities=filtered).summary()

    def lifecycle_summary(self) -> dict[str, int]:
        """Return counts per lifecycle :class:`CapabilityStatus`.

        Returns:
            Dict keyed by status value (``"discovery"``,
            ``"implemented"``, ``"production"``, ``"deprecated"``)
            with the number of capabilities in that state.
        """
        counts: dict[str, int] = {status.value: 0 for status in CapabilityStatus}
        for cap in self.capabilities:
            # The after-validator guarantees status is set on instances,
            # but the field is typed Optional so fall back defensively.
            status = cap.status or CapabilityStatus.DISCOVERY
            counts[status.value] = counts.get(status.value, 0) + 1
        return counts

    def implemented(self) -> list[Capability]:
        """Return capabilities that are at or beyond *implemented*.

        A capability is counted as implemented when its lifecycle status
        is ``implemented`` or ``production`` (not merely discovered).

        Returns:
            List of implemented capabilities.
        """
        return [
            cap
            for cap in self.capabilities
            if cap.status in {CapabilityStatus.IMPLEMENTED, CapabilityStatus.PRODUCTION}
        ]


class ProcessStep(BaseModel):
    """A single step within a :class:`ProcessFlow`.

    Attributes:
        step_id: Stable step identifier.
        name: Human-readable step name.
        description: What happens in this step.
        capability_id: The capability that implements this step.
        depends_on: Step IDs that must complete before this one.
    """

    step_id: str = Field(description="Stable step identifier")
    name: str = Field(description="Human-readable step name")
    description: str = Field(description="What happens in this step")
    capability_id: str | None = Field(
        default=None,
        description="The capability that implements this step",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Step IDs that must complete before this one",
    )


class ProcessFlow(BaseModel):
    """A business process composed of ordered steps with capability links.

    Attributes:
        process_id: Stable process identifier.
        name: Human-readable process name.
        description: Business description of the process.
        steps: Ordered steps in this process.
        tags: Arbitrary classification tags.
    """

    process_id: str = Field(description="Stable process identifier")
    name: str = Field(description="Human-readable process name")
    description: str = Field(description="Business description of the process")
    steps: list[ProcessStep] = Field(
        description="Ordered steps in this process",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary classification tags",
    )

    def find_step(self, step_id: str) -> ProcessStep | None:
        """Look up a step by its identifier.

        Args:
            step_id: The step identifier to search for.

        Returns:
            The matching step, or ``None`` if not found.
        """
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def upstream(self, step_id: str) -> list[ProcessStep]:
        """Return all steps that must complete before the given step.

        Args:
            step_id: The step to find upstream dependencies for.

        Returns:
            List of upstream steps in dependency order.
        """
        step = self.find_step(step_id)
        if step is None:
            return []
        return [s for s in self.steps if s.step_id in step.depends_on]

    def downstream(self, step_id: str) -> list[ProcessStep]:
        """Return all steps that depend on the given step.

        Args:
            step_id: The step to find downstream dependents for.

        Returns:
            List of downstream steps.
        """
        return [s for s in self.steps if step_id in s.depends_on]
