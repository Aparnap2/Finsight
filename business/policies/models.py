"""Business policy models for the FP&A governance framework.

Defines the BusinessPolicy metadata model, PolicyCategory enum,
and PolicyRegistry for registering and looking up declarative
business policies across materiality, approval, classification,
retention, validation, and compliance domains.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Policy severity
# ---------------------------------------------------------------------------

PolicySeverity = Literal["info", "warning", "blocking"]


# ---------------------------------------------------------------------------
# Policy category
# ---------------------------------------------------------------------------


class PolicyCategory(StrEnum):
    """Enumeration of business policy categories.

    Each category represents a distinct domain of business governance.
    """

    MATERIALITY = "materiality"
    APPROVAL = "approval"
    CLASSIFICATION = "classification"
    RETENTION = "retention"
    VALIDATION = "validation"
    COMPLIANCE = "compliance"


# ---------------------------------------------------------------------------
# Business policy model
# ---------------------------------------------------------------------------


class BusinessPolicy(BaseModel):
    """A declarative business policy definition.

    Policies encode business rules as metadata — they define what
    SHOULD happen under given conditions, without implementing the
    evaluation logic itself. The policy engine consumes these
    definitions for routing, gating, and compliance decisions.

    Each policy has a human-readable condition and action expressed
    as plain-text descriptions, making them auditable by non-technical
    stakeholders.
    """

    policy_id: str = Field(..., description="Unique policy identifier (e.g. 'mat-001')")
    name: str = Field(..., description="Human-readable policy name")
    description: str = Field(..., description="Full business description of the policy")
    scope: str = Field(..., description="Scope this policy applies to (e.g. 'variance', 'budget')")
    condition: str = Field(
        ..., description="Condition under which this policy triggers, as business lang"
    )
    action: str = Field(..., description="Action to take when condition is met, as business lang")
    severity: PolicySeverity = Field(
        default="warning", description="How seriously violations are treated"
    )
    owner: str = Field(..., description="Business owner responsible for this policy")
    version: str = Field(default="1.0", description="Policy version identifier")
    effective_from: date = Field(..., description="Date from which this policy is effective")
    effective_until: date | None = Field(
        default=None,
        description="Date after which this policy expires (null = no expiry)",
    )
    tags: list[str] = Field(
        default_factory=list, description="Arbitrary tags for grouping and discovery"
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Policy registry
# ---------------------------------------------------------------------------


class PolicyRegistry(BaseModel):
    """Central registry of all business policies.

    Provides lookup by policy ID, scope, and category, as well as
    iteration over all registered policies.
    """

    policies: dict[str, BusinessPolicy] = Field(
        default_factory=dict,
        description="Policies keyed by policy_id",
    )

    def register(self, policy: BusinessPolicy) -> None:
        """Register a business policy.

        Args:
            policy: The BusinessPolicy to register.
        """
        self.policies[policy.policy_id] = policy

    def get(self, policy_id: str) -> BusinessPolicy | None:
        """Look up a policy by its identifier.

        Args:
            policy_id: The policy identifier (e.g. 'mat-001').

        Returns:
            The BusinessPolicy if found, None otherwise.
        """
        return self.policies.get(policy_id)

    def list_by_scope(self, scope: str) -> list[BusinessPolicy]:
        """Return all policies applicable to a given scope.

        Args:
            scope: The scope string (e.g. 'variance', 'budget').

        Returns:
            List of matching policies.
        """
        return [p for p in self.policies.values() if p.scope == scope]

    def list_by_category(self, category: str) -> list[BusinessPolicy]:
        """Return all policies in a given category.

        Args:
            category: The PolicyCategory value (e.g. 'materiality').

        Returns:
            List of matching policies.
        """
        return [p for p in self.policies.values() if p.scope == category or category in p.tags]

    def list_by_severity(self, severity: PolicySeverity) -> list[BusinessPolicy]:
        """Return all policies with a given severity.

        Args:
            severity: One of 'info', 'warning', 'blocking'.

        Returns:
            List of matching policies.
        """
        return [p for p in self.policies.values() if p.severity == severity]

    @property
    def count(self) -> int:
        """Total number of registered policies."""
        return len(self.policies)
