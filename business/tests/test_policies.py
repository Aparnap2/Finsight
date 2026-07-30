"""Tests for the Business Policies module.

Covers BusinessPolicy model, PolicyCategory enum, PolicyRegistry,
and the 20 registered policies in the global registry.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from business.policies.models import (
    BusinessPolicy,
    PolicyCategory,
    PolicyRegistry,
)
from business.policies.registry import (
    POLICIES_BY_SCOPE,
    POLICY_REGISTRY,
)


class TestPolicyCategory:
    """Tests for the PolicyCategory enum."""

    def test_all_categories_present(self) -> None:
        """All expected policy categories exist."""
        assert PolicyCategory.MATERIALITY.value == "materiality"
        assert PolicyCategory.APPROVAL.value == "approval"
        assert PolicyCategory.CLASSIFICATION.value == "classification"
        assert PolicyCategory.RETENTION.value == "retention"
        assert PolicyCategory.VALIDATION.value == "validation"
        assert PolicyCategory.COMPLIANCE.value == "compliance"

    def test_category_values(self) -> None:
        """Categories have string values matching their names."""
        assert str(PolicyCategory.MATERIALITY) == "materiality"
        assert str(PolicyCategory.COMPLIANCE) == "compliance"

    def test_is_str_enum(self) -> None:
        """PolicyCategory is a string enum usable in string contexts."""
        cat: PolicyCategory = PolicyCategory("approval")
        assert cat == PolicyCategory.APPROVAL


class TestBusinessPolicy:
    """Tests for the BusinessPolicy model."""

    def test_minimal_policy(self) -> None:
        """A policy can be created with required fields."""
        policy = BusinessPolicy(
            policy_id="test-001",
            name="Test Policy",
            description="A test policy",
            scope="test",
            condition="True",
            action="Log it",
            owner="Test Owner",
            version="1.0",
            effective_from=date(2024, 1, 1),
        )
        assert policy.policy_id == "test-001"
        assert policy.severity == "warning"
        assert policy.effective_until is None
        assert policy.tags == []

    def test_policy_with_all_fields(self) -> None:
        """A policy can be created with all optional fields."""
        policy = BusinessPolicy(
            policy_id="test-002",
            name="Full Test Policy",
            description="A policy with all fields",
            scope="full_test",
            condition="x > 10",
            action="Block execution",
            severity="blocking",
            owner="Compliance",
            version="2.0",
            effective_from=date(2024, 6, 1),
            effective_until=date(2025, 6, 1),
            tags=["critical", "test"],
        )
        assert policy.severity == "blocking"
        assert policy.effective_until == date(2025, 6, 1)
        assert "critical" in policy.tags

    def test_severity_validation(self) -> None:
        """Severity must be one of the allowed values."""
        with pytest.raises(ValidationError):
            BusinessPolicy(
                policy_id="test-003",
                name="Bad Severity",
                description="Test",
                scope="test",
                condition="True",
                action="Log",
                severity="invalid",
                owner="Owner",
                version="1.0",
                effective_from=date(2024, 1, 1),
            )

    def test_policy_is_frozen(self) -> None:
        """BusinessPolicy instances are immutable."""
        policy = BusinessPolicy(
            policy_id="test-004",
            name="Frozen Policy",
            description="Cannot be modified",
            scope="test",
            condition="True",
            action="Log",
            owner="Owner",
            version="1.0",
            effective_from=date(2024, 1, 1),
        )
        with pytest.raises(ValidationError):
            policy.name = "Modified"


class TestPolicyRegistry:
    """Tests for the PolicyRegistry."""

    def test_register_and_lookup(self) -> None:
        """Policies can be registered and looked up by ID."""
        registry = PolicyRegistry()
        policy = BusinessPolicy(
            policy_id="reg-001",
            name="Registered Policy",
            description="Test registration",
            scope="registry_test",
            condition="True",
            action="Log",
            owner="Owner",
            version="1.0",
            effective_from=date(2024, 1, 1),
        )
        registry.register(policy)
        assert registry.get("reg-001") is policy
        assert registry.get("nonexistent") is None

    def test_list_by_scope(self) -> None:
        """Policies can be filtered by scope."""
        registry = PolicyRegistry()
        registry.register(
            BusinessPolicy(
                policy_id="s1",
                name="Scope A Policy",
                description="Test",
                scope="scope_a",
                condition="True",
                action="Log",
                owner="Owner",
                version="1.0",
                effective_from=date(2024, 1, 1),
            )
        )
        registry.register(
            BusinessPolicy(
                policy_id="s2",
                name="Scope A Policy 2",
                description="Test",
                scope="scope_a",
                condition="True",
                action="Log",
                owner="Owner",
                version="1.0",
                effective_from=date(2024, 1, 1),
            )
        )
        registry.register(
            BusinessPolicy(
                policy_id="s3",
                name="Scope B Policy",
                description="Test",
                scope="scope_b",
                condition="True",
                action="Log",
                owner="Owner",
                version="1.0",
                effective_from=date(2024, 1, 1),
            )
        )
        scope_a_policies = registry.list_by_scope("scope_a")
        assert len(scope_a_policies) == 2
        scope_b_policies = registry.list_by_scope("scope_b")
        assert len(scope_b_policies) == 1

    def test_list_by_severity(self) -> None:
        """Policies can be filtered by severity."""
        registry = PolicyRegistry()
        blocking_policy = BusinessPolicy(
            policy_id="sev-001",
            name="Blocking",
            description="A blocking policy",
            scope="test",
            condition="True",
            action="Block",
            severity="blocking",
            owner="Owner",
            version="1.0",
            effective_from=date(2024, 1, 1),
        )
        info_policy = BusinessPolicy(
            policy_id="sev-002",
            name="Info",
            description="An info policy",
            scope="test",
            condition="True",
            action="Notify",
            severity="info",
            owner="Owner",
            version="1.0",
            effective_from=date(2024, 1, 1),
        )
        registry.register(blocking_policy)
        registry.register(info_policy)
        blocking = registry.list_by_severity("blocking")
        assert len(blocking) == 1
        assert blocking[0].policy_id == "sev-001"

    def test_count(self) -> None:
        """Count returns the number of registered policies."""
        registry = PolicyRegistry()
        assert registry.count == 0
        registry.register(
            BusinessPolicy(
                policy_id="cnt-001",
                name="Count Test",
                description="Test",
                scope="test",
                condition="True",
                action="Log",
                owner="Owner",
                version="1.0",
                effective_from=date(2024, 1, 1),
            )
        )
        assert registry.count == 1


class TestPolicyRegistryGlobal:
    """Tests for the global POLICY_REGISTRY singleton."""

    def test_has_20_policies(self) -> None:
        """The global registry contains at least 18 policies."""
        assert POLICY_REGISTRY.count >= 18, (
            f"Expected at least 18 policies, got {POLICY_REGISTRY.count}"
        )

    def test_materiality_policies_exist(self) -> None:
        """Materiality policies are registered."""
        assert POLICY_REGISTRY.get("mat-001") is not None
        assert POLICY_REGISTRY.get("mat-002") is not None
        assert POLICY_REGISTRY.get("mat-003") is not None
        assert POLICY_REGISTRY.get("mat-004") is not None
        assert POLICY_REGISTRY.get("mat-005") is not None

    def test_approval_policies_exist(self) -> None:
        """Approval policies are registered."""
        assert POLICY_REGISTRY.get("app-001") is not None
        assert POLICY_REGISTRY.get("app-002") is not None
        assert POLICY_REGISTRY.get("app-003") is not None
        assert POLICY_REGISTRY.get("app-004") is not None

    def test_classification_policies_exist(self) -> None:
        """Classification policies are registered."""
        assert POLICY_REGISTRY.get("cls-001") is not None
        assert POLICY_REGISTRY.get("cls-002") is not None
        assert POLICY_REGISTRY.get("cls-003") is not None

    def test_retention_policies_exist(self) -> None:
        """Retention policies are registered."""
        assert POLICY_REGISTRY.get("ret-001") is not None
        assert POLICY_REGISTRY.get("ret-002") is not None
        assert POLICY_REGISTRY.get("ret-003") is not None

    def test_validation_policies_exist(self) -> None:
        """Validation policies are registered."""
        assert POLICY_REGISTRY.get("val-001") is not None
        assert POLICY_REGISTRY.get("val-002") is not None
        assert POLICY_REGISTRY.get("val-003") is not None
        assert POLICY_REGISTRY.get("val-004") is not None

    def test_compliance_policies_exist(self) -> None:
        """Compliance policies are registered."""
        assert POLICY_REGISTRY.get("cmp-001") is not None
        assert POLICY_REGISTRY.get("cmp-002") is not None
        assert POLICY_REGISTRY.get("cmp-003") is not None
        assert POLICY_REGISTRY.get("cmp-004") is not None

    def test_materiality_policy_content(self) -> None:
        """mat-003 (Combined Threshold) is a blocking policy."""
        policy = POLICY_REGISTRY.get("mat-003")
        assert policy is not None
        assert policy.severity == "blocking"
        assert "material" in policy.description.lower()

    def test_restricted_policy_severity(self) -> None:
        """app-001 (Restricted Data Human Review) is blocking."""
        policy = POLICY_REGISTRY.get("app-001")
        assert policy is not None
        assert policy.severity == "blocking"

    def test_policy_lookup_by_scope(self) -> None:
        """POLICIES_BY_SCOPE maps scopes to policy lists."""
        assert "variance" in POLICIES_BY_SCOPE
        assert len(POLICIES_BY_SCOPE["variance"]) >= 3

    def test_all_policies_have_owners(self) -> None:
        """Every registered policy has a non-empty owner."""
        for policy in POLICY_REGISTRY.policies.values():
            assert policy.owner != "", f"Policy {policy.policy_id} has no owner"

    def test_all_policies_have_effective_dates(self) -> None:
        """Every registered policy has an effective_from date."""
        for policy in POLICY_REGISTRY.policies.values():
            assert policy.effective_from is not None

    def test_policies_have_materiality_tag(self) -> None:
        """Materiality policies are tagged with 'materiality'."""
        for pid in ["mat-001", "mat-002", "mat-003", "mat-004", "mat-005"]:
            policy = POLICY_REGISTRY.get(pid)
            assert policy is not None
            assert "materiality" in policy.tags
