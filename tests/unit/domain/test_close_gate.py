"""Enforced close/approval/evidence gate tests (P6-02 D1+D2+D3+D8).

Covers the new contract in ``finance/domain/verification.py``,
``finance/domain/financial_situation.py`` (``transition_to`` gates), and
``finance/domain/lifecycle.py`` (standalone predicates) against the golden
FS-231 situation: close with a bound accepted report succeeds; every
unbound or unaccepted close refuses; approval without a pinned proposal,
version, authorised decider, or tier conformance refuses; proposals
without evidence refuse; post-approval proposal swaps refuse; and the
caller-supplied ``closed_at`` is byte-deterministic.

Note (by design, not a test): the close path performs no clock reads —
there is no ``datetime.now`` anywhere on it, so identical inputs always
serialise to identical bytes. That is asserted through the determinism
test below, never through a source-grep test.

Zero network, no LLM.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.domain.lifecycle import require_proposal_frozen
from finance.domain.verification import VerificationReport, VerificationVerdict

SITUATION_ID = "FS-2026-0916-00231"
"""Golden FinancialSituation id from the process-model worked example."""

AT = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
"""Caller-supplied deterministic tz-aware close timestamp."""

CHECKED_AT = datetime(2026, 9, 16, 11, 55, tzinfo=UTC)
"""Deterministic tz-aware timestamp for the re-reconcile run."""


def _fs231(status: SituationStatus, **overrides: object) -> FinancialSituation:
    """Build the golden FS-231 aggregate at ``status`` with overrides."""
    fields: dict[str, object] = {
        "situation_id": SITUATION_ID,
        "company_id": "meridian",
        "expected": Decimal("1000000"),
        "razorpay_net": Decimal("972500"),
        "quickbooks": Decimal("982500"),
        "legacy": Decimal("982500"),
        "status": status,
    }
    fields.update(overrides)
    return FinancialSituation(**fields)  # type: ignore[arg-type]


def _report(
    situation_id: str = SITUATION_ID,
    execution_id: str = "EXEC-231-v1",
    legacy_total_after: Decimal = Decimal("992500"),
    variance_after: Decimal = Decimal("0"),
    verdict: VerificationVerdict = VerificationVerdict.VERIFIED,
) -> VerificationReport:
    """Build a verification report bound to FS-231 by default."""
    return VerificationReport(
        situation_id=situation_id,
        execution_id=execution_id,
        legacy_total_after=legacy_total_after,
        variance_after=variance_after,
        verdict=verdict,
        checked_at=CHECKED_AT,
    )


def _verifying() -> FinancialSituation:
    """Build FS-231 ready to close (status VERIFYING)."""
    return _fs231(SituationStatus.VERIFYING)


def _proposed_for_approval(**overrides: object) -> FinancialSituation:
    """Build FS-231 proposed with a pinned manager-approved proposal."""
    fields: dict[str, object] = {
        "proposal_hash": "PROP-HASH-231-v1",
        "proposal_version": 1,
        "decider_role": "manager",
    }
    fields.update(overrides)
    return _fs231(SituationStatus.PROPOSED, **fields)


def _explained_with_evidence(**overrides: object) -> FinancialSituation:
    """Build FS-231 explained with evidence and hypotheses recorded."""
    fields: dict[str, object] = {
        "evidence_ids": ("EV-231-batch", "EV-231-result"),
        "hypothesis_count": 1,
    }
    fields.update(overrides)
    return _fs231(SituationStatus.EXPLAINED, **fields)


@pytest.mark.parametrize("residual", [Decimal("0"), Decimal("50"), Decimal("100")])
def test_close_with_bound_accepted_report_succeeds(residual: Decimal) -> None:
    """VERIFYING closes with a bound VERIFIED report inside tolerance."""
    closed = _verifying().transition_to(
        SituationStatus.CLOSED, at=AT, verification=_report(variance_after=residual)
    )
    assert closed.status is SituationStatus.CLOSED
    assert closed.closed_at == AT
    assert closed.verification is not None
    assert closed.verification.situation_id == SITUATION_ID
    assert closed.verification.legacy_total_after == Decimal("992500")
    assert closed.verification.variance_after == residual


def test_close_without_at_raises() -> None:
    """Close without the caller-supplied timestamp refuses (no auto-stamp)."""
    with pytest.raises(ValueError, match="explicit close timestamp"):
        _verifying().transition_to(SituationStatus.CLOSED, verification=_report())


def test_close_with_naive_at_raises() -> None:
    """Close with a naive timestamp refuses (tz-aware only)."""
    naive = datetime(2026, 9, 16, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _verifying().transition_to(
            SituationStatus.CLOSED, at=naive, verification=_report()
        )


def test_close_without_verification_raises() -> None:
    """Close without a VerificationReport refuses."""
    with pytest.raises(ValueError, match="VerificationReport"):
        _verifying().transition_to(SituationStatus.CLOSED, at=AT)


def test_close_with_wrong_situation_id_raises() -> None:
    """Close with a report bound to another situation refuses."""
    other = _report(situation_id="FS-2026-0916-00232")
    with pytest.raises(ValueError, match="another situation"):
        _verifying().transition_to(SituationStatus.CLOSED, at=AT, verification=other)


def test_close_with_failed_verdict_raises() -> None:
    """Close with a FAILED verdict refuses (re-investigate instead)."""
    failed = _report(verdict=VerificationVerdict.FAILED)
    with pytest.raises(ValueError, match="unaccepted"):
        _verifying().transition_to(SituationStatus.CLOSED, at=AT, verification=failed)


def test_close_with_over_tolerance_residual_raises() -> None:
    """Close with residual 101 (above the minor tolerance 100) refuses."""
    residual = _report(variance_after=Decimal("101"))
    with pytest.raises(ValueError, match="unaccepted"):
        _verifying().transition_to(SituationStatus.CLOSED, at=AT, verification=residual)


def test_close_with_negative_over_tolerance_residual_raises() -> None:
    """The residual bound is absolute: -101 also refuses."""
    residual = _report(variance_after=Decimal("-101"))
    with pytest.raises(ValueError, match="unaccepted"):
        _verifying().transition_to(SituationStatus.CLOSED, at=AT, verification=residual)


@pytest.mark.parametrize("blank", ["", "   "])
def test_unbound_execution_report_rejected(blank: str) -> None:
    """A report with a blank execution_id is unbound and never built."""
    with pytest.raises(ValidationError, match="execution_id"):
        _report(execution_id=blank)


def test_report_checked_at_rejects_naive() -> None:
    """Naive checked_at is rejected at the report boundary."""
    with pytest.raises(ValidationError, match="checked_at"):
        VerificationReport(
            situation_id=SITUATION_ID,
            execution_id="EXEC-231-v1",
            legacy_total_after=Decimal("992500"),
            variance_after=Decimal("0"),
            verdict=VerificationVerdict.VERIFIED,
            checked_at=datetime(2026, 9, 16, 11, 55, 0),
        )


def test_report_rejects_float_money() -> None:
    """Float money is rejected at the report boundary (Decimal only)."""
    with pytest.raises(ValidationError):
        VerificationReport(
            situation_id=SITUATION_ID,
            execution_id="EXEC-231-v1",
            legacy_total_after=992500.0,  # type: ignore[arg-type]
            variance_after=Decimal("0"),
            verdict=VerificationVerdict.VERIFIED,
            checked_at=CHECKED_AT,
        )


def test_report_is_accepted_semantics() -> None:
    """is_accepted is VERIFIED plus residual within tolerance."""
    tolerance = Decimal("100")
    assert _report().is_accepted(tolerance) is True
    assert _report(variance_after=Decimal("100")).is_accepted(tolerance) is True
    assert _report(variance_after=Decimal("101")).is_accepted(tolerance) is False
    assert _report(verdict=VerificationVerdict.FAILED).is_accepted(tolerance) is False


def test_approve_with_pinned_manager_proposal_succeeds() -> None:
    """Variance 10000 sits in the manager band: a manager may approve."""
    approved = _proposed_for_approval().transition_to(SituationStatus.APPROVED)
    assert approved.status is SituationStatus.APPROVED
    assert approved.proposal_hash == "PROP-HASH-231-v1"
    assert approved.proposal_version == 1


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_approve_without_hash_fails(blank: str | None) -> None:
    """Approval without a pinned proposal hash refuses."""
    with pytest.raises(ValueError, match="proposal_hash"):
        _proposed_for_approval(proposal_hash=blank).transition_to(
            SituationStatus.APPROVED
        )


@pytest.mark.parametrize("version", [0, -1])
def test_approve_without_version_fails(version: int) -> None:
    """Approval below proposal version 1 refuses."""
    with pytest.raises(ValueError, match="proposal_version"):
        _proposed_for_approval(proposal_version=version).transition_to(
            SituationStatus.APPROVED
        )


@pytest.mark.parametrize("role", [None, "", "auto", "analyst", "MANAGER"])
def test_approve_without_authorised_role_fails(role: str | None) -> None:
    """Approval needs a recorded manager or director decider role."""
    with pytest.raises(ValueError, match="decider_role"):
        _proposed_for_approval(decider_role=role).transition_to(
            SituationStatus.APPROVED
        )


def test_approve_manager_above_band_fails_director_succeeds() -> None:
    """Variance 82500 needs a director: manager refuses, director passes."""
    big = _fs231(
        SituationStatus.PROPOSED,
        razorpay_net=Decimal("900000"),
        proposal_hash="PROP-HASH-BIG-v1",
        proposal_version=1,
        decider_role="manager",
    )
    assert big.variance() == Decimal("82500")
    with pytest.raises(ValueError, match="director"):
        big.transition_to(SituationStatus.APPROVED)
    director = big.model_copy(update={"decider_role": "director"})
    assert (
        director.transition_to(SituationStatus.APPROVED).status
        is SituationStatus.APPROVED
    )


def test_approve_director_may_decide_small_amount() -> None:
    """A director covers the manager band too (recorded conformance)."""
    approved = _proposed_for_approval(decider_role="director").transition_to(
        SituationStatus.APPROVED
    )
    assert approved.status is SituationStatus.APPROVED


def test_propose_with_evidence_succeeds() -> None:
    """Evidence plus a hypothesis opens the PROPOSED state."""
    proposed = _explained_with_evidence().transition_to(SituationStatus.PROPOSED)
    assert proposed.status is SituationStatus.PROPOSED
    assert len(proposed.evidence_ids) == 2


def test_propose_with_empty_evidence_fails() -> None:
    """A proposal with no evidence ids refuses (D3 enforced gate)."""
    with pytest.raises(ValueError, match="evidence"):
        _fs231(SituationStatus.EXPLAINED, hypothesis_count=2).transition_to(
            SituationStatus.PROPOSED
        )


def test_propose_without_hypothesis_fails() -> None:
    """Evidence alone is not enough: at least one hypothesis is required."""
    with pytest.raises(ValueError, match="hypothesis"):
        _fs231(
            SituationStatus.EXPLAINED, evidence_ids=("EV-231-batch",)
        ).transition_to(SituationStatus.PROPOSED)


def test_freeze_swap_hash_after_approved_fails() -> None:
    """Swapping the pinned hash after APPROVED refuses (D2 freeze)."""
    approved = _fs231(
        SituationStatus.PROPOSED,
        evidence_ids=("EV-231-batch",),
        hypothesis_count=1,
        proposal_hash="PROP-HASH-231-v1",
        proposal_version=1,
        decider_role="manager",
    ).transition_to(SituationStatus.APPROVED)
    assert approved.status is SituationStatus.APPROVED
    swapped = approved.model_copy(update={"proposal_hash": "PROP-HASH-OTHER"})
    with pytest.raises(ValueError, match="frozen"):
        require_proposal_frozen(swapped, approved)
    bumped = approved.model_copy(update={"proposal_version": 2})
    with pytest.raises(ValueError, match="frozen"):
        require_proposal_frozen(bumped, approved)


def test_freeze_preserved_on_legal_post_approval_move() -> None:
    """The legal APPROVED -> EXECUTING move carries the frozen pin."""
    approved = _fs231(
        SituationStatus.APPROVED,
        proposal_hash="PROP-HASH-231-v1",
        proposal_version=1,
        decider_role="manager",
    )
    executing = approved.transition_to(SituationStatus.EXECUTING)
    assert executing.status is SituationStatus.EXECUTING
    assert executing.proposal_hash == "PROP-HASH-231-v1"
    assert executing.proposal_version == 1


def test_close_is_byte_deterministic_for_same_inputs() -> None:
    """Two closes from the same inputs serialise to identical bytes."""
    first = _verifying().transition_to(
        SituationStatus.CLOSED, at=AT, verification=_report()
    )
    second = _verifying().transition_to(
        SituationStatus.CLOSED, at=AT, verification=_report()
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert first.model_dump() == second.model_dump()
    assert first == second
