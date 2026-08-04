"""Tests for the Metadata Registry.

Covers the registry entry model, the singleton discovery process, and
the per-kind collection of formulas, capabilities, policies, and
datasets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from business.metadata.models import MetadataRegistry, RegistryEntry, RegistryEntryKind
from business.metadata.registry import METADATA_REGISTRY, build_entries, discover


class TestRegistryEntry:
    """Tests for the RegistryEntry model."""

    def test_minimal_entry(self) -> None:
        """An entry can be built with required fields."""
        entry = RegistryEntry(
            id="formula:gross_margin",
            kind="formula",
            owner="FP&A Team",
        )
        assert entry.id == "formula:gross_margin"
        assert entry.version == "1.0.0"
        assert entry.status == "discovery"
        assert isinstance(entry.created_at, datetime)

    def test_version_validation(self) -> None:
        """Versions must be three-part semantic versions."""
        with pytest.raises(ValueError):
            RegistryEntry(
                id="formula:test",
                kind="formula",
                version="1.0",
                owner="FP&A Team",
            )

    def test_extra_fields_forbidden(self) -> None:
        """Unknown fields are rejected."""
        kwargs: dict[str, Any] = {
            "id": "formula:test",
            "kind": "formula",
            "owner": "FP&A Team",
        }
        kwargs["bogus"] = "x"
        with pytest.raises(ValueError):
            RegistryEntry(**kwargs)

    def test_unknown_kind_rejected(self) -> None:
        """Kind must come from the canonical set."""
        with pytest.raises(ValueError):
            RegistryEntry(
                id="x:y",
                kind="widget",
                owner="FP&A Team",
            )


class TestMetadataRegistry:
    """Tests for the MetadataRegistry container."""

    def test_register_and_get(self) -> None:
        """Entries can be registered and retrieved."""
        registry = MetadataRegistry()
        entry = RegistryEntry(
            id="formula:test",
            kind="formula",
            owner="FP&A Team",
        )
        registry.register(entry)
        assert registry.get("formula:test") == entry
        assert "formula:test" in registry

    def test_re_registration_same_version_raises(self) -> None:
        """Registering the same id+version raises (conflict detection)."""
        registry = MetadataRegistry()
        entry = RegistryEntry(id="formula:test", kind="formula", owner="A")
        registry.register(entry)
        with pytest.raises(ValueError):
            registry.register(entry)

    def test_set_is_idempotent(self) -> None:
        """Force-set (discovery path) never raises on re-registration."""
        registry = MetadataRegistry()
        entry = RegistryEntry(id="formula:test", kind="formula", owner="A")
        registry._set(entry)  # noqa: SLF001 - testing the discovery guard
        registry._set(entry)  # noqa: SLF001 - must not raise
        assert len(registry) == 1

    def test_count_and_kind_lookup(self) -> None:
        """Entries are countable and filterable by kind."""
        registry = MetadataRegistry()
        for i in range(3):
            registry.register(
                RegistryEntry(id=f"formula:f{i}", kind="formula", owner="A")
            )
        registry.register(
            RegistryEntry(id="policy:p0", kind="policy", owner="A")
        )
        assert len(registry) == 4
        assert len(registry.get_by_kind("formula")) == 3
        assert len(registry.get_by_kind("policy")) == 1

    def test_validate_versions_clean(self) -> None:
        """A registry with consistent versions has no problems."""
        registry = MetadataRegistry()
        registry.register(
            RegistryEntry(id="formula:a", kind="formula", owner="A", version="1.0.0")
        )
        registry.register(
            RegistryEntry(id="formula:b", kind="formula", owner="A", version="1.0.0")
        )
        assert registry.validate_versions() == []

    def test_validate_dependencies_missing(self) -> None:
        """Missing dependency references are reported."""
        registry = MetadataRegistry()
        registry.register(
            RegistryEntry(
                id="formula:a",
                kind="formula",
                owner="A",
                dependencies=["formula:missing"],
            )
        )
        problems = registry.validate_dependencies()
        assert len(problems) == 1
        assert "formula:missing" in problems[0]


class TestDiscovery:
    """Tests for registry discovery from live data."""

    def test_build_entries_populated(self) -> None:
        """Build entries returns every supported kind."""
        entries = build_entries()
        kinds = {e.kind for e in entries}
        assert RegistryEntryKind.FORMULA in kinds
        assert RegistryEntryKind.CAPABILITY in kinds
        assert RegistryEntryKind.POLICY in kinds
        assert RegistryEntryKind.DATASET in kinds

    def test_discover_singleton(self) -> None:
        """Discover returns the shared singleton."""
        registry = discover()
        assert registry is METADATA_REGISTRY
        assert len(registry) > 100

    def test_formula_entries_carry_standards_references(self) -> None:
        """Formula entries cite GAAP/IAS references."""
        registry = discover()
        formulas = registry.get_by_kind("formula")
        assert formulas
        referenced = [e for e in formulas if e.references]
        assert referenced, "at least one formula must cite a standard"

    def test_capability_entries_status_matches_maturity(self) -> None:
        """Capability lifecycle status flows into the registry."""
        registry = discover()
        capabilities = registry.get_by_kind("capability")
        assert capabilities
        statuses = {e.status for e in capabilities}
        assert statuses <= {"discovery", "implemented", "production", "deprecated"}
