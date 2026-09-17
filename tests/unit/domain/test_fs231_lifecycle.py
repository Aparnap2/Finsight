"""FS-231 golden lifecycle matrix (P6-02 audit coverage).

Walks situation ``FS-2026-0916-00231`` along the canonical forward chain in
``docs/domain/meridian-process-model.md`` §2 from ``DETECTED`` through
``CLOSED``, asserting every state, a stable variance of exactly 10000 at
each step, and one audit event per transition. The clean zero-variance
fixture closes through the same legal chain (no fast path exists in the
frozen contract). Approval gating uses the landed
``require_proposal_ref_for_approval`` invariant — no invented states.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finance.domain.audit import AuditLog, emit_for_transition
from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.domain.lifecycle import require_proposal_ref_for_approval

SITUATION_ID = "FS-2026-0916-00231"
"""Golden FinancialSituation id from the process-model worked example."""

BASE_AT = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
"""Deterministic tz-aware anchor for emitted events."""

FULL_CHAIN = (
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
)
"""Canonical forward chain from spec §2 (9 transitions, 10 states)."""


def _fs231(status: SituationStatus) -> FinancialSituation:
    """Build the golden FS-231 aggregate (variance exactly 10000)."""
    return FinancialSituation(
        situation_id=SITUATION_ID,
        company_id="meridian",
        expected=Decimal("1000000"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=status,
    )


def _clean_situation(status: SituationStatus) -> FinancialSituation:
    """Build a zero-variance fixture (all four legs agree at 1000000)."""
    return FinancialSituation(
        situation_id="FS-2026-0916-00240",
        company_id="meridian",
        expected=Decimal("1000000"),
        razorpay_net=Decimal("1000000"),
        quickbooks=Decimal("1000000"),
        legacy=Decimal("1000000"),
        status=status,
    )





def test_fs231_golden_matrix_every_state_variance_and_audit() -> None:
    """FS-231 walks DETECTED → CLOSED with variance 10000 and 9 audit events."""
    log = AuditLog()
    situation = _fs231(FULL_CHAIN[0])
    assert situation.variance() == Decimal("10000")

    for step, target in enumerate(FULL_CHAIN[1:], start=1):
        before = situation
        situation = situation.transition_to(target)
        assert situation.status is target
        assert situation.situation_id == SITUATION_ID
        assert situation.variance() == Decimal("10000")
        event = emit_for_transition(
            before,
            situation,
            at=BASE_AT + timedelta(minutes=step),
            actor="finsight-test-harness",
        )
        log.append(event)
        assert event.from_status == FULL_CHAIN[step - 1]
        assert event.to_status == target
        assert event.variance_snapshot == Decimal("10000")

    assert situation.status is SituationStatus.CLOSED
    assert len(log) == len(FULL_CHAIN) - 1 == 9
    assert len(log.events_for(SITUATION_ID)) == 9
    assert log.verify_chain() is True


def test_fs231_variance_stable_at_each_chain_state() -> None:
    """Variance stays exactly 10000 at every chain state (no drift)."""
    for status in FULL_CHAIN:
        assert _fs231(status).variance() == Decimal("10000")


def test_clean_zero_variance_closes_through_legal_chain() -> None:
    """A clean fixture closes via the canonical chain (no fast path)."""
    log = AuditLog()
    situation = _clean_situation(FULL_CHAIN[0])
    assert situation.variance() == Decimal("0")

    for step, target in enumerate(FULL_CHAIN[1:], start=1):
        before = situation
        situation = situation.transition_to(target)
        assert situation.status is target
        assert situation.variance() == Decimal("0")
        event = emit_for_transition(
            before,
            situation,
            at=BASE_AT + timedelta(minutes=step),
            actor="finsight-test-harness",
        )
        log.append(event)
        assert event.variance_snapshot == Decimal("0")

    assert situation.status is SituationStatus.CLOSED
    assert situation.situation_id == "FS-2026-0916-00240"
    assert len(log) == len(FULL_CHAIN) - 1 == 9
    assert log.verify_chain() is True


def test_clean_fixture_cannot_skip_chain() -> None:
    """Even a zero-variance case must walk the chain to close."""
    clean = _clean_situation(SituationStatus.DETECTED)
    with pytest.raises(ValueError, match="CLOSED"):
        clean.transition_to(SituationStatus.CLOSED)


def test_approval_requires_pinned_proposal_ref() -> None:
    """PROPOSED without a proposal_ref fails the landed approval gate."""
    proposed = _fs231(SituationStatus.PROPOSED)
    with pytest.raises(ValueError, match="proposal_ref"):
        require_proposal_ref_for_approval(proposed)
    pinned = proposed.model_copy(update={"proposal_ref": "PROP-231-v1"})
    require_proposal_ref_for_approval(pinned)
    assert pinned.transition_to(SituationStatus.APPROVED).status is (
        SituationStatus.APPROVED
    )


def test_approval_rejects_blank_proposal_ref() -> None:
    """Blank proposal refs fail the landed approval gate."""
    for blank in ("", "   "):
        proposed = _fs231(SituationStatus.PROPOSED).model_copy(
            update={"proposal_ref": blank}
        )
        with pytest.raises(ValueError, match="proposal_ref"):
            require_proposal_ref_for_approval(proposed)


def test_pinned_ref_travels_proposed_to_approved() -> None:
    """The pinned ref survives the PROPOSED → APPROVED transition."""
    proposed = _fs231(SituationStatus.PROPOSED).model_copy(
        update={"proposal_ref": "PROP-231-v1"}
    )
    require_proposal_ref_for_approval(proposed)
    approved = proposed.transition_to(SituationStatus.APPROVED)
    assert approved.status is SituationStatus.APPROVED
    assert approved.proposal_ref == "PROP-231-v1"
    assert approved.situation_id == SITUATION_ID
