"""Approval tier resolver over MeridianBusinessRules (P6-06 G4 policy).

This module is a thin delegation layer: amount bands come ONLY from
``MeridianBusinessRules.evaluate_refund`` (never reimplemented, never
hardcoded here). The legacy-human-only rule maps a legacy ``AUTO`` routing
up to ``MANAGER`` so legacy corrections always need a human (A10).

STALE REFERENCE WARNING: ``reference-data/approval_limits/defaults.yaml``
(manager 5k / director 25k / cfo 100k) is STALE and is NOT an authority for
this engine. It is never read here; thresholds come exclusively from
``MeridianBusinessRules`` (``REFUND_AUTO`` 5000 / ``REFUND_MANAGER`` 50000).
Do not read or fix that file as part of approval work.
"""

from __future__ import annotations

from decimal import Decimal

from finance.business_rules.meridian import MeridianBusinessRules, RefundAuthority

KNOWN_ROLES: frozenset[str] = frozenset(
    {"analyst", "payment-ops", "manager", "director", "auditor", "agent"}
)
"""Roles named by the A6 role/action matrix (unknown roles fail closed)."""

APPROVER_ROLES: frozenset[str] = frozenset({"manager", "director"})
"""Roles holding approve rights under A6 (mirrors lifecycle decider roles)."""


def required_authority(
    amount: Decimal, *, is_legacy: bool, rules: MeridianBusinessRules | None = None
) -> RefundAuthority:
    """Return the approving tier for an amount, enforcing legacy-human-only.

    Args:
        amount: Proposal amount in INR (``Decimal`` only; enforced inside
            ``evaluate_refund``).
        is_legacy: True for legacy corrections, which are never ``AUTO``.
        rules: Injected rules instance (defaults to ``MeridianBusinessRules``).

    Returns:
        ``AUTO`` below 5000, ``MANAGER`` from 5000 to 50000 inclusive,
        ``DIRECTOR`` above 50000, except legacy amounts below 5000 which
        route to ``MANAGER`` (human approval always required).
    """
    active = rules if rules is not None else MeridianBusinessRules()
    authority = active.evaluate_refund(amount)
    if is_legacy and authority is RefundAuthority.AUTO:
        return RefundAuthority.MANAGER
    return authority


def role_may_approve(role: str, required: RefundAuthority) -> bool:
    """Return True when ``role`` covers the ``required`` tier (A6 + A9).

    Directors cover every tier; managers cover ``AUTO`` and ``MANAGER``
    only; all other roles never approve.

    Args:
        role: The decider role claim (e.g. ``manager``).
        required: The tier required by :func:`required_authority`.

    Returns:
        True when the role may record a decision at the required tier.
    """
    if role == "director":
        return True
    if role == "manager":
        return required is not RefundAuthority.DIRECTOR
    return False
