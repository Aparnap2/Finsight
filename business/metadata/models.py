"""Metadata Registry models for the Business Semantic Layer.

The Metadata Registry is the single authoritative catalog of every
entity in the platform that carries a lifecycle: formulas, policies,
connectors, datasets, schemas, features, and capabilities. Each entry
records identity, semantic version, ownership, lifecycle status, and
the dependency/reference links that make the platform auditable.

This module is Layer 0: it depends only on the standard library and
Pydantic v2. The registry implementation lives in
:mod:`business.metadata.registry`.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums & literals
# ---------------------------------------------------------------------------


class RegistryEntryKind(StrEnum):
    """The kind of entity a registry entry describes."""

    FORMULA = "formula"
    POLICY = "policy"
    CONNECTOR = "connector"
    DATASET = "dataset"
    SCHEMA = "schema"
    FEATURE = "feature"
    CAPABILITY = "capability"


class RegistryEntryStatus(StrEnum):
    """Lifecycle status of a registry entry.

    Mirrors the capability lifecycle (Discovery -> Implemented ->
    Production -> Deprecated) so every entity kind shares one status
    vocabulary.
    """

    DISCOVERY = "discovery"
    IMPLEMENTED = "implemented"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"


EntryKind = Literal["formula", "policy", "connector", "dataset", "schema", "feature", "capability"]
EntryStatus = Literal["discovery", "implemented", "production", "deprecated"]


def _now_utc() -> datetime:
    """Return the current UTC datetime (naive, for storage compatibility)."""
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# RegistryEntry
# ---------------------------------------------------------------------------


class RegistryEntry(BaseModel):
    """A single metadata record in the platform registry.

    Attributes:
        id: Stable unique identifier (e.g. ``formula:gross_margin``).
        kind: What kind of entity this entry describes.
        version: Semantic version string (``MAJOR.MINOR.PATCH``).
        owner: Business owner (team or role).
        status: Lifecycle status of the entry.
        created_at: When the entry was first registered.
        updated_at: When the entry was last modified.
        dependencies: List of other entry ``id`` values this entry
            depends on.
        references: External standards/docs this entry cites
            (e.g. ``"IAS 7"``, ``"GAAP"``, ``"IFRS 15"``).
        description: Human-readable description of the entity.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    id: str = Field(
        description="Stable unique identifier (e.g. formula:gross_margin)",
        min_length=1,
    )
    kind: EntryKind = Field(description="Kind of entity this entry describes")
    version: str = Field(
        default="1.0.0",
        description="Semantic version string",
        pattern=r"^\d+\.\d+\.\d+$",
    )
    owner: str = Field(description="Business owner (team or role)", min_length=1)
    status: EntryStatus = Field(
        default="discovery",
        description="Lifecycle status of the entry",
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        description="Registration timestamp",
    )
    updated_at: datetime = Field(
        default_factory=_now_utc,
        description="Last modification timestamp",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Entry ids this entry depends on",
    )
    references: list[str] = Field(
        default_factory=list,
        description="External standards/docs this entry cites (e.g. IAS 7, GAAP)",
    )
    description: str = Field(default="", description="Human-readable description")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        """Reject versions that are not three-part semantic versions."""
        parts = value.split(".")
        if len(parts) != 3 or any(not p.isdigit() for p in parts):
            msg = f"version must be MAJOR.MINOR.PATCH, got '{value}'"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_timestamps(self) -> RegistryEntry:
        """Ensure created_at never follows updated_at."""
        if self.updated_at < self.created_at:
            msg = "updated_at must not precede created_at"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# MetadataRegistry
# ---------------------------------------------------------------------------


class MetadataRegistry:
    """In-memory registry of :class:`RegistryEntry` records.

    Tracks the current entry per id together with every version that has
    been seen, so that duplicate registrations with *conflicting* versions
    are surfaced by :meth:`validate_versions` rather than silently lost.

    Typical usage::

        registry = MetadataRegistry()
        registry.register(RegistryEntry(id="formula:gross_margin", kind="formula", ...))
        registry.validate_versions()
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._entries: dict[str, RegistryEntry] = {}
        self._versions: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, entry: RegistryEntry) -> None:
        """Register a single entry.

        Args:
            entry: The ``RegistryEntry`` to register.

        Raises:
            ValueError: If an entry with the same id and version is
                already registered (an exact duplicate).
        """
        existing = self._entries.get(entry.id)
        if existing is not None and existing.version == entry.version:
            msg = (
                f"Entry '{entry.id}' is already registered at version "
                f"'{entry.version}'"
            )
            raise ValueError(msg)

        self._versions.setdefault(entry.id, set()).add(entry.version)
        self._entries[entry.id] = entry

    def _set(self, entry: RegistryEntry) -> None:
        """Force-replace an entry without conflict tracking (discovery use).

        Args:
            entry: The ``RegistryEntry`` to store.
        """
        self._entries[entry.id] = entry

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, entry_id: str) -> RegistryEntry | None:
        """Look up the current entry by id.

        Args:
            entry_id: The entry identifier.

        Returns:
            The current ``RegistryEntry`` or ``None`` if unknown.
        """
        return self._entries.get(entry_id)

    def get_by_kind(self, kind: EntryKind) -> list[RegistryEntry]:
        """Return all entries of a given kind, sorted by id.

        Args:
            kind: The entry kind to filter by.

        Returns:
            Matching entries sorted by id.
        """
        return sorted(
            (e for e in self._entries.values() if e.kind == kind),
            key=lambda e: e.id,
        )

    def all(self) -> list[RegistryEntry]:
        """Return every registered entry sorted by id.

        Returns:
            All entries sorted by id.
        """
        return sorted(self._entries.values(), key=lambda e: e.id)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_versions(self) -> list[str]:
        """Detect ids that have been registered under conflicting versions.

        Returns:
            A list of human-readable problem strings; empty when clean.
        """
        problems: list[str] = []
        for entry_id, versions in sorted(self._versions.items()):
            if len(versions) > 1:
                rendered = ", ".join(sorted(versions))
                problems.append(
                    f"entry '{entry_id}' registered with conflicting versions: {rendered}"
                )
        return problems

    def validate_dependencies(self) -> list[str]:
        """Detect dependencies that reference unknown entry ids.

        Returns:
            A list of human-readable problem strings; empty when clean.
        """
        problems: list[str] = []
        known = set(self._entries)
        for entry in self._entries.values():
            for dep in entry.dependencies:
                if dep not in known:
                    problems.append(
                        f"entry '{entry.id}' depends on unknown '{dep}'"
                    )
        return problems

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of currently registered entries."""
        return len(self._entries)

    def __len__(self) -> int:
        """Return the number of currently registered entries."""
        return len(self._entries)

    def __contains__(self, entry_id: str) -> bool:
        """Check whether an entry id is registered."""
        return entry_id in self._entries
