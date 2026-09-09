"""Deterministic finance policy gate for the execution boundary.

``check(proposal, approval)`` is a pure function of its two inputs plus
the amount threshold: no clock, no network, no database. It enforces,
in order:

1. terminal ``APPROVED`` decision on the approval record;
2. pinned triple — approval ``(proposal_id, proposal_version,
   content_hash)`` exactly matches the live proposal triple;
3. hash integrity — ``verify_hash`` passes, so ``amount`` is still the
   builder-recomputed value (any drift denies);
4. sandbox action — the action is bookable in the sandbox, which is also
   the action-allowed-for-exception-type gate (correcting entries serve
   refund-lag, voids serve duplicates, fee-mismatch is proposal-only and
   can never reach this gate);
5. amount ceiling — ``0 < amount <= threshold`` in exact Decimal;
6. balanced legs — distinct non-empty debit/credit accounts (the adapter
   re-verifies balance; policy refuses one-legged proposals early);
7. scope agreement — both records hang off the same exception.

Only the Python standard library plus ``finance.*`` are used. This
module imports nothing from ``apps/``, ``agents/``, or ``shared/``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from finance.proposals.builder import verify_hash

logger = logging.getLogger(__name__)

#: Exclusive policy ceiling default: mirrors the approval threshold used
#: across the frozen flagship fixtures (15k proposal under a 20k ceiling).
DEFAULT_AMOUNT_THRESHOLD = Decimal("20000.00")

#: Sandbox-bookable actions: correcting entries (refund-lag) and voids
#: (duplicates). Fee-mismatch never builds a bookable proposal.
_SANDBOX_ACTIONS = frozenset({"CREATE_CORRECTING_ENTRY", "VOID_DUPLICATE"})


@dataclass(frozen=True)
class PolicyDecision:
    """Frozen verdict of one policy check.

    ``allowed`` is the machine gate; ``decision`` carries the frozen
    ``ALLOW``/``DENY`` spelling for callers matching on words; ``reasons``
    records every failed gate for audit.
    """

    allowed: bool
    decision: str
    reasons: tuple[str, ...] = ()


def _proposal_triple(proposal: Any) -> tuple[Any, Any, Any] | None:
    """Read the live ``(proposal_id, version, content_hash)`` triple."""
    version = getattr(proposal, "proposal_version", None)
    if version is None:
        version = getattr(proposal, "version", None)
    return (
        getattr(proposal, "proposal_id", None),
        version,
        getattr(proposal, "content_hash", None),
    )


def _approval_triple(approval: Any) -> tuple[Any, Any, Any] | None:
    """Read the pinned ``(proposal_id, version, content_hash)`` triple."""
    pin = getattr(approval, "pin_triple", None)
    if callable(pin):
        triple = pin()
        if isinstance(triple, tuple) and len(triple) == 3:
            return (triple[0], triple[1], triple[2])
        return None
    return (
        getattr(approval, "proposal_id", None),
        getattr(approval, "proposal_version", None),
        getattr(approval, "content_hash", None),
    )


def check(
    proposal: Any,
    approval: Any,
    *,
    amount_threshold: Decimal = DEFAULT_AMOUNT_THRESHOLD,
) -> PolicyDecision:
    """Decide whether an approved proposal may execute.

    Args:
        proposal: Live proposal draft (amount recomputed by the builder).
        approval: Terminal HITL record pinning the proposal triple.
        amount_threshold: Exclusive policy ceiling; proposals with
            ``amount <= threshold`` pass the amount gate.

    Returns:
        ``PolicyDecision`` with ``allowed True`` and ``decision "ALLOW"``
        only when every gate passes, else ``allowed False`` / ``"DENY"``.
    """
    reasons: list[str] = []

    decision = getattr(approval, "decision", None)
    if decision is None or str(decision).upper() != "APPROVED":
        reasons.append(f"approval decision {decision!r} is not APPROVED")

    live = _proposal_triple(proposal)
    pinned = _approval_triple(approval)
    if live is None or pinned is None or live != pinned:
        reasons.append(f"pin skew: approval pins {pinned!r} but proposal is {live!r}")
    else:
        try:
            intact = verify_hash(proposal)
        except (TypeError, ValueError, AttributeError) as exc:
            reasons.append(f"hash verification unreadable: {exc}")
        else:
            if not intact:
                reasons.append("proposal content_hash drifted from canonical fields")

    action = getattr(proposal, "action", None)
    if action is None or str(action.value if hasattr(action, "value") else action) not in (
        _SANDBOX_ACTIONS
    ):
        reasons.append(f"action {action!r} is not sandbox-bookable")

    amount: Any = getattr(proposal, "amount", None)
    if (
        amount is None
        or isinstance(amount, (bool, float))
        or not isinstance(amount, Decimal)
        or not amount.is_finite()
        or amount <= Decimal("0")
    ):
        reasons.append("proposal amount must be a positive finite Decimal")
    elif amount > amount_threshold:
        reasons.append(f"proposal amount {amount} exceeds threshold {amount_threshold}")

    debit = getattr(proposal, "debit_account", None)
    credit = getattr(proposal, "credit_account", None)
    if (
        not isinstance(debit, str)
        or not debit.strip()
        or not isinstance(credit, str)
        or not credit.strip()
        or debit.strip() == credit.strip()
    ):
        reasons.append("proposal legs must name two distinct accounts")

    proposal_exc = getattr(proposal, "exception_id", None)
    approval_exc = getattr(approval, "exception_id", None)
    if proposal_exc is None or approval_exc is None or proposal_exc != approval_exc:
        reasons.append("proposal and approval hang off different exceptions")

    allowed = not reasons
    logger.info(
        "execution policy proposal=%s allowed=%s reasons=%s",
        getattr(proposal, "proposal_id", "?"),
        allowed,
        reasons,
    )
    return PolicyDecision(
        allowed=allowed,
        decision="ALLOW" if allowed else "DENY",
        reasons=tuple(reasons),
    )
