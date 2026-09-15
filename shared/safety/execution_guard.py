"""Sandbox execution guard: last-mile tripwire against autonomous action.

``ExecutionGuard.check`` inspects one pinned execution command before any
financial side effect. Each failed gate increments ``unsafe`` and appends
a reason; a fully pinned command yields ``unsafe == 0`` with
``allowed is True``. The check is duck-typed on purpose: callers may pass
:class:`ExecutionCommand` (or its ``GuardCommand``/``GuardRequest``
aliases) or any object carrying the same attribute names, and missing
attributes are treated as absent evidence rather than crashes.

Gates (each violation denies and counts one unsafe bypass attempt):

1. sandbox environment — the guard instance must run ``environment="sandbox"``;
2. pinned identities — ``exception_id``, ``proposal_id``, ``approval_id``
   are non-empty strings (an unapproved/direct call has no approval pin);
3. idempotency key present — replay safety requires a caller-supplied key;
4. Decimal-only positive amount — ``float``/``bool`` money is rejected;
5. approved decision — when the command carries a decision attribute it
   must read ``APPROVED`` (also accepts ``ALLOW``/``ALLOWED`` spellings);
6. non-terminal state — when the command carries a state attribute it
   must not already be terminal (no double execution off a closed case).

Only the Python standard library is used. This module imports nothing
from ``apps/``, ``agents/``, or ``finance/``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

#: States after which no further execution may start off the same command.
_TERMINAL_STATES = frozenset(
    {
        "EXECUTING",
        "POST_VERIFYING",
        "EXECUTION_VERIFIED",
        "FAILED",
        "CLOSED",
        "ESCALATED",
        "REJECTED",
    }
)

#: Decision spellings accepted as an approval to execute.
_APPROVED_DECISIONS = frozenset({"APPROVED", "ALLOW", "ALLOWED"})


def _blank(value: object) -> bool:
    """Return True when a required identifier is missing or empty."""
    return not isinstance(value, str) or not value.strip()


@dataclass(frozen=True)
class ExecutionCommand:
    """Pinned execution request: approval triple plus key plus amount.

    The command carries no authority of its own — ``approval_id`` must
    pin the HITL record produced by the approval phase, and the amount
    is informational (policy reads money from the proposal, never here).
    """

    exception_id: str
    proposal_id: str
    approval_id: str
    idempotency_key: str
    amount: Decimal

    def __post_init__(self) -> None:
        """Enforce identifier shapes and Decimal-only money at the boundary."""
        for field_name in (
            "exception_id",
            "proposal_id",
            "approval_id",
            "idempotency_key",
        ):
            if _blank(getattr(self, field_name)):
                raise ValueError(f"Field '{field_name}' must be a non-empty string.")
        amount: Any = self.amount
        if isinstance(amount, (bool, float)):
            raise TypeError("Field 'amount' must be Decimal: float/bool money is rejected.")
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise ValueError("Field 'amount' must be a finite Decimal.")


#: Alias probed by frozen callers preferring the guard vocabulary.
GuardCommand = ExecutionCommand

#: Alias probed by frozen callers preferring the request vocabulary.
GuardRequest = ExecutionCommand


@dataclass(frozen=True)
class GuardDecision:
    """Frozen verdict of one guard check.

    ``unsafe`` counts autonomous bypass attempts detected in the command;
    the ``unsafe_action_count == 0`` invariant holds exactly when every
    execution presented a fully pinned, approved, keyed command.
    """

    allowed: bool
    unsafe: int
    reasons: tuple[str, ...] = ()


class ExecutionGuard:
    """Last-mile tripwire: pinned approvals pass, bypass attempts count."""

    def __init__(self, *, environment: str = "sandbox") -> None:
        """Bind the guard to an environment name.

        Args:
            environment: Must stay ``"sandbox"`` — any other value denies
                every command, since production books are out of scope.
        """
        self._environment = environment

    @property
    def environment(self) -> str:
        """Return the environment this guard instance enforces."""
        return self._environment

    def check(self, cmd: object) -> GuardDecision:
        """Inspect one command and return the frozen verdict.

        Args:
            cmd: Pinned execution command (or any object carrying the
                same attribute names). Never raises on missing
                attributes — absent evidence counts as a violation.

        Returns:
            ``GuardDecision`` with ``unsafe == 0`` and ``allowed True``
            only when every gate passes.
        """
        reasons: list[str] = []
        unsafe = 0

        if self._environment != "sandbox":
            unsafe += 1
            reasons.append(f"non-sandbox environment {self._environment!r}: deny")

        for field_name in ("exception_id", "proposal_id", "approval_id"):
            if _blank(getattr(cmd, field_name, None)):
                unsafe += 1
                reasons.append(f"missing {field_name}: unapproved/direct call refused")
        if _blank(getattr(cmd, "idempotency_key", None)):
            unsafe += 1
            reasons.append("missing idempotency_key: replay-unsafe call refused")

        amount: Any = getattr(cmd, "amount", None)
        if (
            amount is None
            or isinstance(amount, (bool, float))
            or not isinstance(amount, Decimal)
            or not amount.is_finite()
            or amount <= Decimal("0")
        ):
            unsafe += 1
            reasons.append("amount must be a positive finite Decimal")

        for attr in ("decision", "approval_decision"):
            decision = getattr(cmd, attr, None)
            if decision is not None and str(decision).upper() not in _APPROVED_DECISIONS:
                unsafe += 1
                reasons.append(f"unapproved decision {decision!r}: execution refused")
                break

        state = getattr(cmd, "state", None)
        if state is not None and str(state).upper() in _TERMINAL_STATES:
            unsafe += 1
            reasons.append(f"terminal state {state!r}: re-execution refused")

        allowed = unsafe == 0
        logger.info(
            "guard check exception=%s allowed=%s unsafe=%s",
            getattr(cmd, "exception_id", "?"),
            allowed,
            unsafe,
        )
        return GuardDecision(allowed=allowed, unsafe=unsafe, reasons=tuple(reasons))
