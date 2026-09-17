"""Conflict escalation routing with read-only policy consults.

Conflicting authorities are INVESTIGATE ONLY: never auto-resolved,
never majority-voted, never last-write-wins. This module returns
routing info only; lifecycle transitions stay owned by the frozen
P6-02 state machine (no ``transition_to`` call happens here).
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from finance.business_rules.meridian import MeridianBusinessRules

_HUMAN_REVIEW_ROUTE = "HUMAN_REVIEW"
"""Conflicts always route to human-led review."""


class EscalationDecision(BaseModel):
    """Routing info for one conflicting-authorities finding."""

    model_config = ConfigDict(frozen=True, strict=True)

    route: str
    """Where the conflict goes; always human review."""

    requires_approval: bool
    """Always true for conflicts: auto-resolve is forbidden."""

    authority: str
    """Refund-tier authority consulted for the variance band."""

    reason: str
    """Human-readable routing reason naming the consulted policy."""

    @field_validator("route", "authority", "reason")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Require non-empty routing strings."""
        if not value.strip():
            raise ValueError("route, authority, and reason must be non-empty.")
        return value.strip()


def decide_escalation(
    *,
    variance: Decimal,
    legacy_involved: bool,
) -> EscalationDecision:
    """Route a conflict to human review consulting frozen policy.

    Consults ``legacy_always_requires_approval`` and the refund tiers
    read-only: neither the legacy flag nor the tier bands are mutated,
    and no lifecycle transition is performed.

    Args:
        variance: The disputed variance magnitude (Decimal only).
        legacy_involved: True when a legacy leg takes part.

    Returns:
        The immutable escalation routing decision.

    Raises:
        TypeError: If ``variance`` arrives as bool/float.
        ValueError: If ``variance`` is not a finite Decimal.
    """
    raw: Any = variance
    if isinstance(raw, bool | float):
        raise TypeError(
            "variance must be decimal.Decimal, got "
            f"{type(raw).__name__}: float/bool money is rejected."
        )
    if not isinstance(raw, Decimal) or not raw.is_finite():
        raise ValueError(
            "variance must be a finite Decimal, "
            f"got {type(raw).__name__}."
        )
    rules = MeridianBusinessRules()
    legacy_approval = rules.legacy_always_requires_approval()
    tier = rules.evaluate_refund(abs(raw))
    reason = (
        "Conflicting authorities: investigate only, never auto-resolve, "
        "never majority-vote, never last-write-wins. "
        f"Legacy approval required: {legacy_approval} "
        f"(legacy involved: {legacy_involved}); refund tier: {tier.value}."
    )
    return EscalationDecision(
        route=_HUMAN_REVIEW_ROUTE,
        requires_approval=True,
        authority=tier.value,
        reason=reason,
    )
