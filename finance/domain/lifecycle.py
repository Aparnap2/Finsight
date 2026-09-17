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

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from finance.business_rules.meridian import MeridianBusinessRules, RefundAuthority

if TYPE_CHECKING:
    from finance.domain.financial_situation import FinancialSituation
    from finance.domain.verification import VerificationReport

StateLike = str | StrEnum
"""A lifecycle state given as its name or as a ``StrEnum`` member."""

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DETECTED": frozenset({"TRIAGED", "ESCALATED"}),
    "TRIAGED": frozenset({"INVESTIGATING", "ESCALATED"}),
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

APPROVED_AND_LATER: frozenset[str] = frozenset(
    {"APPROVED", "EXECUTING", "VERIFYING", "CLOSED", "ESCALATED", "REJECTED"}
)
"""States at or after approval, where the proposal freeze (D2) applies.

The main chain past approval is ``APPROVED -> EXECUTING -> VERIFYING ->
CLOSED``; ``ESCALATED`` is included because an approved situation may
escalate and must carry the same pinned proposal, and ``REJECTED`` is
included for completeness (terminal, so the table refuses exits first).
"""

ALLOWED_DECIDER_ROLES: frozenset[str] = frozenset({"manager", "director"})
"""Human roles that may decide on a proposal (recorded, not verified)."""

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


def require_evidence_for_proposal(situation: FinancialSituation) -> None:
    """Require evidence and hypotheses before a proposal (D3 ENFORCED gate).

    The ``EXPLAINED -> PROPOSED`` move is refused unless the situation
    carries at least one evidence id and at least one hypothesis. This is
    an enforced predicate: ``FinancialSituation.transition_to`` calls it
    on the ``PROPOSED`` path, so the gate cannot be bypassed by design.

    Args:
        situation: The aggregate proposed for ``PROPOSED``.

    Raises:
        ValueError: If ``evidence_ids`` is empty or ``hypothesis_count``
            is below 1.
    """
    if len(situation.evidence_ids) < 1:
        raise ValueError(
            "Cannot propose without evidence: at least one evidence id "
            "must be recorded (D3 evidence gate)."
        )
    if situation.hypothesis_count < 1:
        raise ValueError(
            "Cannot propose without a hypothesis: hypothesis_count must "
            "be at least 1 (D3 evidence gate)."
        )


def require_decider_authority_for_approval(situation: FinancialSituation) -> None:
    """Require a pinned proposal plus tier-conformant decider (D8 gate).

    The ``PROPOSED -> APPROVED`` move is refused unless the situation
    pins a non-blank ``proposal_hash`` at ``proposal_version >= 1`` and
    records a ``decider_role`` of ``manager`` or ``director`` that conforms
    to the variance amount band. Band conformance reuses
    ``MeridianBusinessRules`` (amounts above the manager band require a
    director); no band thresholds are reimplemented here.

    D7 principle: the actor/authority is recorded, not verified. The tier
    check is a recorded conformance check against the deterministic
    variance — it confirms the recorded decider role covers the amount
    band; it does not authenticate the human behind the Slack signal.

    This is an enforced predicate: ``FinancialSituation.transition_to``
    calls it on the ``APPROVED`` path, so the gate cannot be bypassed.

    Args:
        situation: The aggregate proposed for ``APPROVED``.

    Raises:
        ValueError: If the proposal hash is missing or blank, the version
            is below 1, the decider role is unknown, or a manager decides
            an amount above the manager band (director required).
    """
    if not situation.proposal_hash or not situation.proposal_hash.strip():
        raise ValueError(
            "Cannot approve without proposal_hash: approval must pin "
            "the immutable proposal hash."
        )
    if situation.proposal_version < 1:
        raise ValueError(
            "Cannot approve without a proposal version: proposal_version "
            "must be at least 1."
        )
    if situation.decider_role not in ALLOWED_DECIDER_ROLES:
        raise ValueError(
            "Cannot approve without an authorised decider: decider_role "
            f"must be one of {sorted(ALLOWED_DECIDER_ROLES)} "
            "(recorded, not verified)."
        )
    authority = MeridianBusinessRules().evaluate_refund(abs(situation.variance()))
    if authority is RefundAuthority.DIRECTOR and situation.decider_role != "director":
        raise ValueError(
            "Cannot approve with a manager decider: the variance "
            f"{situation.variance()} sits above the manager band, "
            "so a director is required (recorded conformance check)."
        )


def require_proposal_frozen(
    situation: FinancialSituation, baseline: FinancialSituation
) -> None:
    """Require the pinned proposal to be unchanged past approval (D2 freeze).

    Once a situation is at or after ``APPROVED``, every subsequent
    transition must carry the same ``proposal_hash`` and
    ``proposal_version`` as the baseline it moves from: swapping the hash
    or bumping the version on the same aggregate is refused. A revised
    proposal re-enters only as a new version through the sanctioned
    re-entry states, never by mutating the approved pin in place.

    This is an enforced predicate: ``FinancialSituation.transition_to``
    consults it on every transition whose source is at or after
    ``APPROVED`` (comparing the post-transition copy against the source),
    so the freeze cannot be bypassed by design. Call it directly with an
    explicit baseline to test a suspected swap.

    Args:
        situation: The candidate aggregate (usually the post-transition
            copy) whose pin must match the baseline.
        baseline: The pre-transition aggregate the pin must match.

    Raises:
        ValueError: If the baseline is at or after ``APPROVED`` and the
            candidate carries a different ``proposal_hash`` or
            ``proposal_version``.
    """
    if _state_name(baseline.status) not in APPROVED_AND_LATER:
        return
    if (
        situation.proposal_hash != baseline.proposal_hash
        or situation.proposal_version != baseline.proposal_version
    ):
        raise ValueError(
            "Proposal pin is frozen past approval (D2): the transition "
            "carries a different proposal_hash/proposal_version than "
            "the approved baseline; revise via a new proposal version."
        )


def require_verification_for_close(
    situation: FinancialSituation,
    verification: VerificationReport | None,
    at: datetime | None,
    tolerance: Decimal,
) -> None:
    """Require a bound, accepted verification report to close (D1 gate).

    The ``VERIFYING -> CLOSED`` move is refused unless the caller supplies
    a timezone-aware ``at`` timestamp (there is no auto-stamp: callers
    record when the deterministic re-reconcile ran) and a
    ``VerificationReport`` bound to the same ``situation_id`` whose
    ``is_accepted(tolerance)`` holds — that is, verdict ``VERIFIED`` with
    ``abs(variance_after)`` within tolerance.

    This is an enforced predicate: ``FinancialSituation.transition_to``
    calls it on the ``CLOSED`` path, so the gate cannot be bypassed.

    Args:
        situation: The aggregate proposed for ``CLOSED``.
        verification: The deterministic re-reconcile report to store.
        at: Caller-supplied timezone-aware close timestamp.
        tolerance: Maximum acceptable absolute residual, normally
            ``CompanyConfiguration().tolerance_minor``.

    Raises:
        ValueError: If ``at`` is missing or naive, the report is missing,
            bound to another situation, or not accepted at ``tolerance``
            (``FAILED`` verdict or over-tolerance residual).
    """
    if at is None:
        raise ValueError(
            "Cannot close without an explicit close timestamp: pass "
            "a timezone-aware `at` (no auto-stamp on the close path)."
        )
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Cannot close with a naive `at`: it must be timezone-aware.")
    if verification is None:
        raise ValueError(
            "Cannot close without a VerificationReport: the deterministic "
            "post-execution re-reconcile must accept first."
        )
    if verification.situation_id != situation.situation_id:
        raise ValueError(
            "Cannot close with a report bound to another situation: "
            f"report is for {verification.situation_id!r}, "
            f"situation is {situation.situation_id!r}."
        )
    if not verification.is_accepted(tolerance):
        raise ValueError(
            "Cannot close with an unaccepted VerificationReport: verdict "
            f"{verification.verdict.value} with residual "
            f"{verification.variance_after} is not accepted at tolerance "
            f"{tolerance}."
        )
