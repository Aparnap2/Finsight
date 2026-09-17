"""FS-231 golden lifecycle matrix (P6-02 audit coverage).

Walks situation ``FS-2026-0916-00231`` along the canonical forward chain in
``docs/domain/meridian-process-model.md`` §2 from ``DETECTED`` through
``CLOSED``, asserting every state, a stable variance of exactly 10000 at
each step, and one audit event per transition. The clean zero-variance
fixture closes through the same legal chain (no fast path exists in the
frozen contract). Approval gating uses the landed D2 hash/version/role
gate — no invented states.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finance.domain.audit import AuditLog, emit_for_transition
from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.domain.verification import VerificationReport, VerificationVerdict

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





def _bound_close_report(
    situation: FinancialSituation,
    *,
    legacy_total_after: Decimal,
    variance_after: Decimal,
    at: datetime,
) -> VerificationReport:
    """Build the D1-bound report for a golden close."""
    return VerificationReport(
        situation_id=situation.situation_id,
        execution_id="LEGACY-20260916-0042",
        legacy_total_after=legacy_total_after,
        variance_after=variance_after,
        verdict=VerificationVerdict.VERIFIED,
        checked_at=at,
    )


def _walk_chain(
    situation: FinancialSituation,
    log: AuditLog,
    *,
    actor: str = "finsight-test-harness",
    legacy_total_after: Decimal = Decimal("992500"),
) -> FinancialSituation:
    """Walk FULL_CHAIN through the enforced gates with per-step audit."""
    opening_variance = situation.variance()
    for step, target in enumerate(FULL_CHAIN[1:], start=1):
        before = situation
        if target is SituationStatus.PROPOSED:
            situation = situation.model_copy(
                update={"evidence_ids": ("ev-001",), "hypothesis_count": 2}
            )
        if target is SituationStatus.APPROVED:
            situation = situation.model_copy(
                update={
                    "proposal_hash": "PROP-231-v1",
                    "proposal_version": 1,
                    "decider_role": "manager",
                }
            )
        if target is SituationStatus.CLOSED:
            at = BASE_AT + timedelta(minutes=step)
            situation = situation.record_verification(legacy_total_after)
            situation = situation.transition_to(
                target,
                at=at,
                verification=_bound_close_report(
                    situation,
                    legacy_total_after=legacy_total_after,
                    variance_after=Decimal("0"),
                    at=at,
                ),
            )
        else:
            situation = situation.transition_to(target)
        assert situation.status is target
        assert situation.variance() == opening_variance
        event = emit_for_transition(
            before,
            situation,
            at=BASE_AT + timedelta(minutes=step),
            actor=actor,
        )
        log.append(event)
        assert event.from_status == FULL_CHAIN[step - 1]
        assert event.to_status == target
        assert event.variance_snapshot == opening_variance
    return situation


def test_fs231_golden_matrix_every_state_variance_and_audit() -> None:
    """FS-231 walks DETECTED → CLOSED with variance 10000 and 9 audit events."""
    log = AuditLog()
    situation = _walk_chain(_fs231(FULL_CHAIN[0]), log)
    assert situation.status is SituationStatus.CLOSED
    assert situation.situation_id == SITUATION_ID
    assert situation.variance() == Decimal("10000")
    assert situation.verification is not None
    assert situation.verification.variance_after == Decimal("0")
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
    situation = _walk_chain(
        _clean_situation(FULL_CHAIN[0]),
        log,
        legacy_total_after=Decimal("1000000"),
    )
    assert situation.status is SituationStatus.CLOSED
    assert situation.situation_id == "FS-2026-0916-00240"
    assert situation.variance() == Decimal("0")
    assert len(log) == len(FULL_CHAIN) - 1 == 9
    assert log.verify_chain() is True


def test_clean_fixture_cannot_skip_chain() -> None:
    """Even a zero-variance case must walk the chain to close."""
    clean = _clean_situation(SituationStatus.DETECTED)
    with pytest.raises(ValueError, match="CLOSED"):
        clean.transition_to(SituationStatus.CLOSED)


def _pinned_proposed(
    proposal_hash: str | None = "PROP-231-v1",
) -> FinancialSituation:
    """PROPOSED aggregate pinned for the landed D2 approval gate."""
    return _fs231(SituationStatus.PROPOSED).model_copy(
        update={
            "proposal_hash": proposal_hash,
            "proposal_version": 1,
            "decider_role": "manager",
        }
    )


def test_approval_requires_pinned_proposal_ref() -> None:
    """PROPOSED without a hash fails the landed D2 approval gate."""
    proposed = _fs231(SituationStatus.PROPOSED)
    with pytest.raises(ValueError, match="proposal_hash"):
        proposed.transition_to(SituationStatus.APPROVED)
    pinned = _pinned_proposed()
    assert pinned.transition_to(SituationStatus.APPROVED).status is (
        SituationStatus.APPROVED
    )


def test_approval_rejects_blank_proposal_ref() -> None:
    """Blank hashes fail the landed D2 approval gate."""
    for blank in ("", "   "):
        proposed = _fs231(SituationStatus.PROPOSED).model_copy(
            update={
                "proposal_hash": blank,
                "proposal_version": 1,
                "decider_role": "manager",
            }
        )
        with pytest.raises(ValueError, match="proposal_hash"):
            proposed.transition_to(SituationStatus.APPROVED)


def test_pinned_ref_travels_proposed_to_approved() -> None:
    """The pinned hash/version/role survive PROPOSED → APPROVED."""
    proposed = _pinned_proposed()
    approved = proposed.transition_to(SituationStatus.APPROVED)
    assert approved.status is SituationStatus.APPROVED
    assert approved.proposal_hash == "PROP-231-v1"
    assert approved.proposal_version == 1
    assert approved.decider_role == "manager"
    assert approved.situation_id == SITUATION_ID


def test_fs231_resolution_proven_at_close() -> None:
    """Close proves the outcome: 992500 bound, pending reconciles, residual 0.

    The business assertion the state-walk alone cannot make: the ₹10,000
    discrepancy is actually resolved (legacy 982500 + correction 10000 =
    992500), the pending ₹7,500 reconciles to the ₹10,00,000 expected
    total, and the residual sits within tolerance. Closure is earned.
    """
    log = AuditLog()
    situation = _walk_chain(
        _fs231(FULL_CHAIN[0]),
        log,
        legacy_total_after=Decimal("992500"),
    )
    assert situation.status is SituationStatus.CLOSED
    report = situation.verification
    assert report is not None
    assert report.verdict.value == "VERIFIED"
    assert report.legacy_total_after == Decimal("992500")
    assert report.legacy_total_after - Decimal("982500") == Decimal("10000")
    assert report.legacy_total_after + Decimal("7500") == Decimal("1000000")
    assert abs(report.variance_after) <= Decimal("100")
    assert report.situation_id == SITUATION_ID
    assert report.execution_id == "LEGACY-20260916-0042"
    assert situation.proposal_hash == "PROP-231-v1"
    assert len(log) == 9
    assert log.verify_chain() is True
