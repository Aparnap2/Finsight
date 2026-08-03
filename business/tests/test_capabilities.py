"""Tests for the elevated Business Capability layer.

Covers the lifecycle status enum, maturity-to-status derivation,
registry helpers, and the service-catalog wiring exports.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from business.capabilities import (
    CAPABILITIES,
    CAPABILITY_TREE,
    capabilities_by_status,
    implemented_capabilities,
    maturity_report,
)
from business.capabilities.models import (
    Capability,
    CapabilityMaturity,
    CapabilityStatus,
    CapabilityTree,
)


class TestCapabilityStatus:
    """Tests for the lifecycle enum."""

    def test_four_states(self) -> None:
        """The lifecycle has exactly four states."""
        values = {s.value for s in CapabilityStatus}
        assert values == {"discovery", "implemented", "production", "deprecated"}

    def test_ordering_monotonic(self) -> None:
        """The enum preserves the lifecycle order."""
        order = list(CapabilityStatus)
        assert order == [
            CapabilityStatus.DISCOVERY,
            CapabilityStatus.IMPLEMENTED,
            CapabilityStatus.PRODUCTION,
            CapabilityStatus.DEPRECATED,
        ]


class TestCapabilityModel:
    """Tests for the Capability model."""

    def test_minimal_capability_derives_status(self) -> None:
        """Status derives from maturity when not given."""
        cap = Capability(
            capability_id="cap.test",
            name="Test",
            description="A test capability",
        )
        assert cap.status == CapabilityStatus.DISCOVERY

    def test_production_maturity_maps_to_production(self) -> None:
        """A production-mature capability is lifecycle production."""
        cap = Capability(
            capability_id="cap.test",
            name="Test",
            description="A test capability",
            maturity="production",
        )
        assert cap.status == CapabilityStatus.PRODUCTION

    def test_partial_maturity_maps_to_implemented(self) -> None:
        """A partial-mature capability is lifecycle implemented."""
        cap = Capability(
            capability_id="cap.test",
            name="Test",
            description="A test capability",
            maturity="partial",
        )
        assert cap.status == CapabilityStatus.IMPLEMENTED

    def test_explicit_status_wins(self) -> None:
        """An explicitly provided status is preserved."""
        cap = Capability(
            capability_id="cap.test",
            name="Test",
            description="A test capability",
            maturity="planned",
            status=CapabilityStatus.DEPRECATED,
        )
        assert cap.status == CapabilityStatus.DEPRECATED

    def test_wiring_fields_default(self) -> None:
        """The wiring fields default to empty lists."""
        cap = Capability(
            capability_id="cap.test",
            name="Test",
            description="A test capability",
        )
        assert cap.apis == []
        assert cap.agent_tools == []
        assert cap.kpis == []
        assert cap.policies == []

    def test_invalid_maturity_rejected(self) -> None:
        """Unknown maturity values are rejected."""
        with pytest.raises(ValidationError):
            Capability(
                capability_id="cap.test",
                name="Test",
                description="A test capability",
                maturity="mature",
            )


class TestCapabilityMaturity:
    """Tests for maturity reporting helpers."""

    def test_lifecycle_summary_counts(self) -> None:
        """Lifecycle summary counts each state."""
        caps = [
            Capability(capability_id="c1", name="1", description="", maturity="planned"),
            Capability(capability_id="c2", name="2", description="", maturity="partial"),
            Capability(capability_id="c3", name="3", description="", maturity="production"),
            Capability(
                capability_id="c4",
                name="4",
                description="",
                status=CapabilityStatus.DEPRECATED,
            ),
        ]
        maturity = CapabilityMaturity(capabilities=caps)
        summary = maturity.lifecycle_summary()
        assert summary == {
            "discovery": 1,
            "implemented": 1,
            "production": 1,
            "deprecated": 1,
        }

    def test_implemented_filters(self) -> None:
        """Implemented returns production and implemented only."""
        caps = [
            Capability(capability_id="c1", name="1", description="", maturity="planned"),
            Capability(capability_id="c2", name="2", description="", maturity="partial"),
            Capability(capability_id="c3", name="3", description="", maturity="production"),
        ]
        maturity = CapabilityMaturity(capabilities=caps)
        ids = {c.capability_id for c in maturity.implemented()}
        assert ids == {"c2", "c3"}


class TestCapabilityTree:
    """Tests for tree-level helpers."""

    def test_by_status(self) -> None:
        """by_status filters by lifecycle state."""
        caps = [
            Capability(capability_id="c1", name="1", description="", maturity="planned"),
            Capability(capability_id="c2", name="2", description="", maturity="partial"),
        ]
        tree = CapabilityTree(capabilities=caps)
        discovered = [c.capability_id for c in tree.by_status(CapabilityStatus.DISCOVERY)]
        assert discovered == ["c1"]

    def test_implemented_capabilities_method(self) -> None:
        """implemented_capabilities returns implementable ids."""
        caps = [
            Capability(capability_id="c1", name="1", description="", maturity="planned"),
            Capability(capability_id="c2", name="2", description="", maturity="production"),
        ]
        tree = CapabilityTree(capabilities=caps)
        assert tree.implemented_capabilities() == [caps[1]]


class TestRegistryExports:
    """Tests for the populated capability registry."""

    def test_38_capabilities(self) -> None:
        """The registry holds 38 capabilities."""
        assert len(CAPABILITIES) == 38

    def test_maturity_report_shape(self) -> None:
        """maturity_report returns summary plus lifecycle counts."""
        report = maturity_report()
        assert report["total"] == 38
        assert report["implemented_count"] > 0
        assert set(report["lifecycle"].keys()) == {
            "discovery",
            "implemented",
            "production",
            "deprecated",
        }

    def test_implemented_capabilities_nonempty(self) -> None:
        """The service catalog exposes implemented capabilities."""
        impl = implemented_capabilities()
        assert len(impl) > 20
        assert all(cap_id.startswith("cap.") for cap_id in impl)

    def test_capabilities_by_status(self) -> None:
        """capabilities_by_status filters the full registry."""
        production = capabilities_by_status(CapabilityStatus.PRODUCTION)
        assert len(production) == 8
        assert all(c.status == CapabilityStatus.PRODUCTION for c in production)

    def test_tree_lookup(self) -> None:
        """The tree resolves capability ids."""
        cap = CAPABILITY_TREE.find_by_id("cap.planning.budget.create")
        assert cap is not None
        assert cap.name == "Budget Creation"
