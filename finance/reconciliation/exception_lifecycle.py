"""Reconciliation exception lifecycle: state machine and transition validation.

Defines the legal state transitions for a ``ReconciliationException`` and the
mapping from a human ``DecisionType`` to the resulting status. The state
machine is the single source of truth; ``record_decision`` in
``finance.reconciliation.persistence`` validates against it before persisting.

Only the Python standard library is used.
"""

from __future__ import annotations

from finance.exceptions.errors import IllegalTransitionError
from finance.reconciliation.models import ExceptionStatus

# Legal transitions: (from_status, to_status) -> allowed decision types.
ALLOWED_TRANSITIONS: dict[tuple[ExceptionStatus, ExceptionStatus], frozenset[str]] = {
    (ExceptionStatus.OPEN, ExceptionStatus.INVESTIGATING): frozenset({"ASSIGN"}),
    (ExceptionStatus.OPEN, ExceptionStatus.UNDER_REVIEW): frozenset({"ASSIGN"}),
    (ExceptionStatus.INVESTIGATING, ExceptionStatus.UNDER_REVIEW): frozenset({"ASSIGN"}),
    (ExceptionStatus.INVESTIGATING, ExceptionStatus.RESOLVED): frozenset({"APPROVE"}),
    (ExceptionStatus.INVESTIGATING, ExceptionStatus.REOPENED): frozenset({"REJECT"}),
    (ExceptionStatus.UNDER_REVIEW, ExceptionStatus.RESOLVED): frozenset({"APPROVE"}),
    (ExceptionStatus.UNDER_REVIEW, ExceptionStatus.REOPENED): frozenset({"REJECT"}),
    (ExceptionStatus.UNDER_REVIEW, ExceptionStatus.INVESTIGATING): frozenset({"ASSIGN", "REOPEN"}),
    (ExceptionStatus.RESOLVED, ExceptionStatus.REOPENED): frozenset({"REOPEN"}),
    (ExceptionStatus.REOPENED, ExceptionStatus.INVESTIGATING): frozenset({"ASSIGN"}),
    (ExceptionStatus.REOPENED, ExceptionStatus.UNDER_REVIEW): frozenset({"ASSIGN"}),
}


def validate_transition(
    current: ExceptionStatus | str,
    target: ExceptionStatus | str,
    decision_type: str,
) -> None:
    """Validate a state transition for a reconciliation exception.

    Raises:
        IllegalTransitionError: If the transition is not allowed or the
            decision type does not match.
        ValueError: If the status strings are unknown.
    """
    try:
        current_status = (
            current if isinstance(current, ExceptionStatus) else ExceptionStatus(current)
        )
    except ValueError as exc:
        raise ValueError(f"Unknown current status: {current!r}") from exc
    try:
        target_status = target if isinstance(target, ExceptionStatus) else ExceptionStatus(target)
    except ValueError as exc:
        raise ValueError(f"Unknown target status: {target!r}") from exc

    if current_status == target_status:
        raise IllegalTransitionError(
            exception_id="",
            from_state=current_status.value,
            to_state=target_status.value,
            reason="no-op transition is not allowed",
        )

    allowed_decisions = ALLOWED_TRANSITIONS.get((current_status, target_status))
    if allowed_decisions is None:
        raise IllegalTransitionError(
            exception_id="",
            from_state=current_status.value,
            to_state=target_status.value,
            reason="transition not in the allowed set",
        )
    if decision_type not in allowed_decisions:
        raise IllegalTransitionError(
            exception_id="",
            from_state=current_status.value,
            to_state=target_status.value,
            reason=f"decision type {decision_type!r} not allowed for this transition",
        )


def is_terminal(status: ExceptionStatus | str) -> bool:
    """Return True if the status is a terminal state (no further transitions)."""
    try:
        s = status if isinstance(status, ExceptionStatus) else ExceptionStatus(status)
    except ValueError:
        return False
    return s in (ExceptionStatus.RESOLVED,)


def allowed_targets(current: ExceptionStatus | str) -> frozenset[ExceptionStatus]:
    """Return the set of statuses reachable from ``current``."""
    try:
        current_status = (
            current if isinstance(current, ExceptionStatus) else ExceptionStatus(current)
        )
    except ValueError:
        return frozenset()
    return frozenset(target for (src, target) in ALLOWED_TRANSITIONS if src == current_status)
