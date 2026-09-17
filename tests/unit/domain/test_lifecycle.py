"""Unit tests for the P6-02 FinancialSituation executable lifecycle.

Covers ``finance/domain/lifecycle.py`` (canonical transition table from
``docs/domain/meridian-process-model.md`` section 2) and the P6-02
extension of ``finance/domain/financial_situation.py`` (optional
``proposal_ref``, ``verified_total``, ``closed_at``, ``rejection_reason``
plus the ``record_verification`` helper). Follows the frozen spec
exactly: no new states, no ``MATCHED`` fast path, no ledger writes.
Zero network, no LLM.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain import lifecycle
from finance.domain.financial_situation import FinancialSituation, SituationStatus

SITUATION_ID = "FS-2026-0916-00231"
"""Golden FinancialSituation id from the process-model worked example."""

FULL_CHAIN = [
    SituationStatus.DETECTED,
    SituationStatus.TRIAGED,
    SituationStatus.INVESTIGATING,
    SituationStatus.CORRELATED,
    SituationStatus.EXPLAINED,
    SituationStatus.PROPOSED,
    SituationStatus.APPROVED,
    SituationStatus.EXECUTING,
    SituationStatus.VERIFYING,
    SituationStatus.CLOSED,
]
"""Canonical forward chain from spec section 2 (FS-231 walk)."""


def _fs231(**overrides: object) -> FinancialSituation:
    """Build the golden FS-231 FinancialSituation (status DETECTED)."""
    fields: dict[str, object] = {
        "situation_id": SITUATION_ID,
        "company_id": "meridian",
        "expected": Decimal("1000000"),
        "razorpay_net": Decimal("972500"),
        "quickbooks": Decimal("982500"),
        "legacy": Decimal("982500"),
        "status": SituationStatus.DETECTED,
    }
    fields.update(overrides)
    return FinancialSituation(**fields)  # type: ignore[arg-type]


def test_canonical_chain_covers_spec_section_2() -> None:
    """Every spec section 2.1 row is present in the canonical table."""
    assert {
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
    } == lifecycle.ALLOWED_TRANSITIONS


def test_allowed_transitions_covers_every_status() -> None:
    """The table keys are exactly the SituationStatus member values."""
    assert set(lifecycle.ALLOWED_TRANSITIONS) == {item.value for item in SituationStatus}


def test_transition_table_is_canonical_single_source() -> None:
    """FinancialSituation validates against the lifecycle.py table object."""
    import finance.domain.financial_situation as situation_module

    assert situation_module.ALLOWED_TRANSITIONS is lifecycle.ALLOWED_TRANSITIONS


def test_full_legal_chain_fs231_detected_to_closed() -> None:
    """FS-231 walks DETECTED all the way to CLOSED with evidence attached."""
    situation = _fs231(status=SituationStatus.DETECTED)
    for target in [
        SituationStatus.TRIAGED,
        SituationStatus.INVESTIGATING,
        SituationStatus.CORRELATED,
        SituationStatus.EXPLAINED,
    ]:
        situation = situation.transition_to(target)
    situation = situation.model_copy(update={"proposal_ref": "PROP-FS-231-v1"})
    situation = situation.transition_to(SituationStatus.PROPOSED)
    for target in [SituationStatus.APPROVED, SituationStatus.EXECUTING]:
        situation = situation.transition_to(target)
    situation = situation.transition_to(SituationStatus.VERIFYING)
    situation = situation.record_verification(Decimal("10000"))
    lifecycle.require_verified_total_for_close(situation)
    situation = situation.transition_to(SituationStatus.CLOSED)
    assert situation.status is SituationStatus.CLOSED
    assert situation.verified_total == Decimal("10000")
    assert situation.situation_id == SITUATION_ID


def test_escalation_and_return_paths() -> None:
    """Active states escalate; ESCALATED re-enters via INVESTIGATING/PROPOSED."""
    for source in [
        SituationStatus.INVESTIGATING,
        SituationStatus.CORRELATED,
        SituationStatus.EXPLAINED,
        SituationStatus.PROPOSED,
        SituationStatus.APPROVED,
        SituationStatus.EXECUTING,
        SituationStatus.VERIFYING,
    ]:
        escalated = _fs231(status=source).transition_to(SituationStatus.ESCALATED)
        assert escalated.status is SituationStatus.ESCALATED
    escalated = _fs231(status=SituationStatus.INVESTIGATING).transition_to(
        SituationStatus.ESCALATED
    )
    assert (
        escalated.transition_to(SituationStatus.INVESTIGATING).status
        is SituationStatus.INVESTIGATING
    )
    assert (
        escalated.transition_to(SituationStatus.PROPOSED).status
        is SituationStatus.PROPOSED
    )


def test_verifying_may_reinvestigate() -> None:
    """VERIFYING -> INVESTIGATING reopens work after a FAILED verdict."""
    reopened = _fs231(status=SituationStatus.VERIFYING).transition_to(
        SituationStatus.INVESTIGATING
    )
    assert reopened.status is SituationStatus.INVESTIGATING


def test_proposed_may_reject() -> None:
    """PROPOSED -> REJECTED is the terminal refusal path for a version."""
    refused = _fs231(status=SituationStatus.PROPOSED).transition_to(
        SituationStatus.REJECTED
    )
    assert refused.status is SituationStatus.REJECTED


@pytest.mark.parametrize("terminal", [SituationStatus.CLOSED, SituationStatus.REJECTED])
@pytest.mark.parametrize(
    "target",
    [
        SituationStatus.DETECTED,
        SituationStatus.INVESTIGATING,
        SituationStatus.PROPOSED,
        SituationStatus.EXECUTING,
        SituationStatus.CLOSED,
    ],
)
def test_terminal_states_immutable(
    terminal: SituationStatus, target: SituationStatus
) -> None:
    """Terminal states accept no exit, including self-transitions."""
    with pytest.raises(ValueError, match="not allowed"):
        _fs231(status=terminal).transition_to(target)


@pytest.mark.parametrize("pair", sorted(lifecycle.BANNED_TRANSITIONS))
def test_every_banned_transition_raises(pair: tuple[str, str]) -> None:
    """Each curated banned pair in section 2.2 raises on transition_to."""
    source = SituationStatus(pair[0])
    target = SituationStatus(pair[1])
    with pytest.raises(ValueError, match="not allowed"):
        _fs231(status=source).transition_to(target)


def test_banned_pairs_absent_from_allowed_table() -> None:
    """No banned pair is reachable in the canonical table (meta-guard)."""
    for source, target in lifecycle.BANNED_TRANSITIONS:
        assert not lifecycle.is_allowed(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (SituationStatus.TRIAGED, SituationStatus.DETECTED),
        (SituationStatus.CORRELATED, SituationStatus.INVESTIGATING),
        (SituationStatus.EXPLAINED, SituationStatus.CORRELATED),
        (SituationStatus.APPROVED, SituationStatus.PROPOSED),
        (SituationStatus.EXECUTING, SituationStatus.APPROVED),
        (SituationStatus.VERIFYING, SituationStatus.EXECUTING),
        (SituationStatus.ESCALATED, SituationStatus.EXECUTING),
        (SituationStatus.ESCALATED, SituationStatus.CLOSED),
    ],
)
def test_backward_moves_rejected(
    source: SituationStatus, target: SituationStatus
) -> None:
    """Only ESCALATED -> INVESTIGATING and VERIFYING -> INVESTIGATING go back."""
    with pytest.raises(ValueError, match="not allowed"):
        _fs231(status=source).transition_to(target)


def test_close_without_verified_total_raises() -> None:
    """The close invariant requires verified_total to be set."""
    with pytest.raises(ValueError, match="verified_total"):
        lifecycle.require_verified_total_for_close(
            _fs231(status=SituationStatus.VERIFYING)
        )


def test_close_with_verified_total_passes() -> None:
    """The close invariant passes once verification evidence is recorded."""
    situation = _fs231(status=SituationStatus.VERIFYING).record_verification(
        Decimal("10000")
    )
    lifecycle.require_verified_total_for_close(situation)


def test_approve_without_proposal_ref_raises() -> None:
    """Approval must pin a proposal reference (immutable proposal hash)."""
    with pytest.raises(ValueError, match="proposal_ref"):
        lifecycle.require_proposal_ref_for_approval(_fs231(status=SituationStatus.PROPOSED))


def test_approve_with_proposal_ref_passes() -> None:
    """Approval invariant passes once the proposal reference is attached."""
    situation = _fs231(status=SituationStatus.PROPOSED).model_copy(
        update={"proposal_ref": "PROP-FS-231-v1"}
    )
    lifecycle.require_proposal_ref_for_approval(situation)


def test_reject_without_reason_raises() -> None:
    """Rejection must carry a reason for the audit trail."""
    with pytest.raises(ValueError, match="rejection_reason"):
        lifecycle.require_rejection_reason_for_reject(
            _fs231(status=SituationStatus.PROPOSED)
        )


def test_record_verification_requires_verifying_state() -> None:
    """Verification evidence is recorded only in VERIFYING (spec section 2)."""
    for status in [
        SituationStatus.DETECTED,
        SituationStatus.INVESTIGATING,
        SituationStatus.EXPLAINED,
        SituationStatus.PROPOSED,
        SituationStatus.EXECUTING,
        SituationStatus.CLOSED,
    ]:
        with pytest.raises(ValueError, match="VERIFYING"):
            _fs231(status=status).record_verification(Decimal("10000"))


def test_record_verification_sets_total_stays_verifying() -> None:
    """record_verification stores the total; the state stays VERIFYING."""
    before = _fs231(status=SituationStatus.VERIFYING)
    after = before.record_verification(Decimal("10000"))
    assert after.status is SituationStatus.VERIFYING
    assert after.verified_total == Decimal("10000")
    assert before.verified_total is None


def test_record_verification_rejects_float() -> None:
    """Float money is rejected by record_verification (Decimal only)."""
    with pytest.raises((TypeError, ValueError)):
        _situation = _fs231(status=SituationStatus.VERIFYING)
        _situation.record_verification(10000.0)  # type: ignore[arg-type]


def test_closed_at_auto_stamped_on_close_tz_aware() -> None:
    """Transitioning to CLOSED stamps a tz-aware closed_at when unset."""
    before = datetime.now(UTC)
    closed = _fs231(status=SituationStatus.VERIFYING).transition_to(
        SituationStatus.CLOSED
    )
    assert closed.closed_at is not None
    assert closed.closed_at.tzinfo is not None
    assert closed.closed_at.utcoffset() is not None
    assert closed.closed_at >= before


def test_closed_at_rejects_naive() -> None:
    """Naive datetimes are rejected for closed_at (tz-aware only)."""
    with pytest.raises(ValidationError):
        _fs231(closed_at=datetime(2026, 9, 16, 12, 0, 0))


def test_verified_total_rejects_float_at_boundary() -> None:
    """Float money is rejected at the Pydantic boundary (Decimal only)."""
    with pytest.raises(ValidationError):
        _fs231(verified_total=10000.0)


def test_backward_compat_p601_construction() -> None:
    """P6-01 seven-field construction stays valid with None lifecycle extras."""
    situation = _fs231()
    assert situation.situation_id == SITUATION_ID
    assert situation.company_id == "meridian"
    assert situation.variance() == Decimal("10000")
    assert situation.proposal_ref is None
    assert situation.verified_total is None
    assert situation.closed_at is None
    assert situation.rejection_reason is None


def test_aggregate_stays_frozen() -> None:
    """New lifecycle fields do not weaken the frozen aggregate."""
    situation = _fs231()
    with pytest.raises(ValidationError):
        situation.proposal_ref = "PROP-X"  # type: ignore[misc]
