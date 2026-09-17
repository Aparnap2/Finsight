"""Canonical FinancialSituation lifecycle table and invariants (P6-02).

Single source of truth for the forward chain in section 2 of
``docs/domain/meridian-process-model.md``::

    DETECTED -> TRIAGED -> INVESTIGATING -> CORRELATED -> EXPLAINED
      -> PROPOSED -> APPROVED -> EXECUTING -> VERIFYING -> CLOSED

Side states ``ESCALATED`` (needs higher authority) and ``REJECTED``
(terminal refusal for a proposal version) re-enter the chain only via a
new proposal version. ``REJECTED`` and ``CLOSED`` are terminal.

The table is keyed by plain state-name strings so this module stays
importable without pulling in the aggregate (and vice versa): the
``SituationStatus`` enum itself continues to live in
``finance/domain/financial_situation.py``. State arguments accept either
the enum member or its raw string value. Lifecycle state only: this
module never writes ledgers, never calls the network, never uses an LLM.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finance.domain.financial_situation import FinancialSituation

StateLike = str | StrEnum
"""A lifecycle state given as its name or as a ``StrEnum`` member."""

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DETECTED": frozenset({"TRIAGED"}),
    "TRIAGED": frozenset({"INVESTIGATING"}),
    "INVESTIGATING": frozenset({"CORRELATED", "ESCALATED"}),
    "CORRELATED": frozenset({"EXPLAINED", "ESCALATED"}),
    "EXPLAINED": frozenset({"PROPOSED", "ESCALATED"}),
    "PROPOSED": frozenset({"APPROVED", "REJECTED", "ESCALATED"}),
    "APPROVED": frozenset({"EXECUTING", "ESCALATED"}),
    "EXECUTING": frozenset({"VERIFYING", "ESCALATED"}),
    "VERIFYING": frozenset({"CLOSED", "INVESTIGATING", "ESCALATED"}),
    "ESCALATED": frozenset({"INVESTIGATING", "PROPOSED"}),
    "REJECTED": frozenset(),
    "CLOSED": frozenset(),
}
"""Canonical allowed-transition table mirroring spec section 2.1.

Every non-terminal state may escalate; ``ESCALATED`` re-enters only via
``INVESTIGATING`` or ``PROPOSED`` (a new proposal version). The only
backward step on the main chain is ``VERIFYING -> INVESTIGATING`` (a
``FAILED`` re-reconcile verdict reopens the investigation). ``REJECTED``
and ``CLOSED`` are terminal: re-entry happens through a new version,
never through a transition on the same aggregate.
"""

TERMINAL_STATES: frozenset[str] = frozenset({"REJECTED", "CLOSED"})
"""States with no outgoing transitions (immutable once reached)."""

BANNED_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("INVESTIGATING", "EXECUTING"),
    ("PROPOSED", "EXECUTING"),
    ("DETECTED", "CLOSED"),
    ("TRIAGED", "CLOSED"),
    ("INVESTIGATING", "CLOSED"),
    ("CORRELATED", "CLOSED"),
    ("EXPLAINED", "CLOSED"),
    ("PROPOSED", "CLOSED"),
    ("APPROVED", "CLOSED"),
    ("EXECUTING", "CLOSED"),
    ("ESCALATED", "CLOSED"),
    ("CLOSED", "INVESTIGATING"),
    ("CLOSED", "CLOSED"),
    ("REJECTED", "PROPOSED"),
    ("REJECTED", "INVESTIGATING"),
    ("REJECTED", "REJECTED"),
    ("TRIAGED", "DETECTED"),
    ("CORRELATED", "INVESTIGATING"),
    ("EXPLAINED", "CORRELATED"),
    ("APPROVED", "PROPOSED"),
    ("EXECUTING", "APPROVED"),
    ("VERIFYING", "EXECUTING"),
    ("ESCALATED", "EXECUTING"),
    ("ESCALATED", "APPROVED"),
    ("DETECTED", "INVESTIGATING"),
    ("EXPLAINED", "APPROVED"),
)
"""Curated banned pairs from spec section 2.2 plus terminal/backward guards.

Execution without approval, close without terminal verification, every
exit from a terminal state, backward steps on the main chain, and
forward skip-ahead jumps are all refused. Each pair is absent from
:data:`ALLOWED_TRANSITIONS` (asserted by the unit tests).
"""


def _state_name(state: StateLike) -> str:
    """Normalise an enum member or raw string to its state-name string."""
    if isinstance(state, StrEnum):
        return state.value
    return str(state)


def is_allowed(source: StateLike, target: StateLike) -> bool:
    """Return True when ``source -> target`` is in the canonical table."""
    return _state_name(target) in ALLOWED_TRANSITIONS.get(_state_name(source), frozenset())


def assert_transition_allowed(source: StateLike, target: StateLike) -> None:
    """Raise ValueError unless ``source -> target`` is in the canonical table.

    Args:
        source: The current lifecycle state.
        target: The lifecycle state to move into.

    Raises:
        ValueError: If the move is banned, backward (outside the two
            sanctioned re-entries), or exits a terminal state.
    """
    source_name = _state_name(source)
    target_name = _state_name(target)
    allowed = ALLOWED_TRANSITIONS.get(source_name, frozenset())
    if target_name not in allowed:
        raise ValueError(
            f"Transition {source_name} -> {target_name} is not allowed; "
            f"permitted targets are {sorted(allowed)}."
        )


def require_verified_total_for_close(situation: FinancialSituation) -> None:
    """Require recorded verification evidence before closing.

    Args:
        situation: The aggregate proposed for ``CLOSED``.

    Raises:
        ValueError: If ``verified_total`` is not set (close without the
            deterministic ``EXECUTION_VERIFIED`` re-reconcile is banned).
    """
    if situation.verified_total is None:
        raise ValueError(
            "Cannot close without verified_total: record_verification() "
            "must store the deterministic re-reconcile total first."
        )


def require_proposal_ref_for_approval(situation: FinancialSituation) -> None:
    """Require a pinned proposal reference before approval.

    Args:
        situation: The aggregate proposed for ``APPROVED``.

    Raises:
        ValueError: If ``proposal_ref`` is missing or blank (Slack
            approval must pin the immutable proposal hash).
    """
    if not situation.proposal_ref or not situation.proposal_ref.strip():
        raise ValueError(
            "Cannot approve without proposal_ref: approval must pin "
            "the immutable proposal hash."
        )


def require_rejection_reason_for_reject(situation: FinancialSituation) -> None:
    """Require a reason when refusing a proposal version.

    Args:
        situation: The aggregate proposed for ``REJECTED``.

    Raises:
        ValueError: If ``rejection_reason`` is missing or blank.
    """
    if not situation.rejection_reason or not situation.rejection_reason.strip():
        raise ValueError(
            "Cannot reject without rejection_reason: the refusal must "
            "be recorded for the audit trail."
        )


def require_tz_aware_closed_at(situation: FinancialSituation) -> None:
    """Require ``closed_at`` to be timezone-aware once it is set.

    Args:
        situation: The aggregate to inspect.

    Raises:
        ValueError: If ``closed_at`` is set but naive.
    """
    closed_at = situation.closed_at
    if closed_at is not None and (
        closed_at.tzinfo is None or closed_at.utcoffset() is None
    ):
        raise ValueError("closed_at must be timezone-aware when set.")
