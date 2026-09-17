"""Adversarial transition tests for the P6-02 lifecycle audit.

Attempts every banned move from ``docs/domain/meridian-process-model.md``
§2.2 against the P6-01 base aggregate: jumps to ``CLOSED``, exits from
terminal states, approval without a proposal, close without a verified
total, cross-company tampering, garbage statuses, and a missing actor.
Two gates that the base table does not enforce yet (proposal presence for
approval, verified total for close) are covered through minimal local
adapters defined in this file — the audit layer itself never drives
transitions, so the adapters stand in for the pending sibling lifecycle
work and the reviewer reconciles them after it lands.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.audit import AuditLog, emit_for_transition
from finance.domain.financial_situation import FinancialSituation, SituationStatus

SITUATION_ID = "FS-2026-0916-00231"
"""Golden FinancialSituation id from the process-model worked example."""

BASE_AT = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
"""Deterministic tz-aware anchor for emitted events."""


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


def _require_proposal_for_approval(
    situation: FinancialSituation, proposal_ref: str | None
) -> FinancialSituation:
    """Local adapter for the sibling approval gate (not in P6-01).

    Stands in for the pending lifecycle rule that ``PROPOSED → APPROVED``
    requires a live proposal: a missing ``proposal_ref`` is refused before
    the move. The reviewer reconciles this against the sibling work.
    """
    if proposal_ref is None or not proposal_ref.strip():
        raise ValueError(
            f"Cannot approve {situation.situation_id}: no proposal pinned."
        )
    return situation.transition_to(SituationStatus.APPROVED)


def _require_verified_total_for_close(
    situation: FinancialSituation, verified_total: Decimal | None
) -> FinancialSituation:
    """Local adapter for the sibling close gate (not in P6-01).

    Stands in for the pending lifecycle rule that ``VERIFYING → CLOSED``
    requires a deterministic re-reconcile total (the ``EXECUTION_VERIFIED``
    verdict): a missing ``verified_total`` is refused before the move.
    The reviewer reconciles this against the sibling work.
    """
    if verified_total is None:
        raise ValueError(
            f"Cannot close {situation.situation_id}: no verified total."
        )
    if not isinstance(verified_total, Decimal):
        raise ValueError("verified_total must be a Decimal (money is exact).")
    return situation.transition_to(SituationStatus.CLOSED)


def test_detected_to_closed_jump_rejected() -> None:
    """Skipping the chain straight to CLOSED is banned."""
    with pytest.raises(ValueError, match="CLOSED"):
        _fs231(SituationStatus.DETECTED).transition_to(SituationStatus.CLOSED)


@pytest.mark.parametrize(
    "target",
    [
        SituationStatus.DETECTED,
        SituationStatus.TRIAGED,
        SituationStatus.INVESTIGATING,
        SituationStatus.VERIFYING,
        SituationStatus.ESCALATED,
    ],
)
def test_closed_to_anything_rejected(target: SituationStatus) -> None:
    """CLOSED is terminal: no exit to any other state."""
    with pytest.raises(ValueError, match=target.value):
        _fs231(SituationStatus.CLOSED).transition_to(target)


@pytest.mark.parametrize(
    "target",
    [SituationStatus.PROPOSED, SituationStatus.INVESTIGATING],
)
def test_rejected_is_terminal(target: SituationStatus) -> None:
    """REJECTED ends the version: re-entry needs a new proposal version."""
    with pytest.raises(ValueError, match=target.value):
        _fs231(SituationStatus.REJECTED).transition_to(target)


def test_execution_without_approval_rejected() -> None:
    """No execution without a proposal and its approval."""
    with pytest.raises(ValueError, match="EXECUTING"):
        _fs231(SituationStatus.INVESTIGATING).transition_to(
            SituationStatus.EXECUTING
        )
    with pytest.raises(ValueError, match="EXECUTING"):
        _fs231(SituationStatus.PROPOSED).transition_to(SituationStatus.EXECUTING)


def test_approved_without_proposal_rejected_by_gate() -> None:
    """Approval requires a pinned proposal (sibling gate adapter)."""
    proposed = _fs231(SituationStatus.PROPOSED)
    with pytest.raises(ValueError, match="no proposal"):
        _require_proposal_for_approval(proposed, None)
    with pytest.raises(ValueError, match="no proposal"):
        _require_proposal_for_approval(proposed, "   ")
    approved = _require_proposal_for_approval(proposed, "PROP-231-v1")
    assert approved.status is SituationStatus.APPROVED


def test_close_without_verified_total_rejected_by_gate() -> None:
    """Close requires a deterministic verified total (sibling gate adapter)."""
    verifying = _fs231(SituationStatus.VERIFYING)
    with pytest.raises(ValueError, match="no verified total"):
        _require_verified_total_for_close(verifying, None)
    with pytest.raises(ValueError, match="Decimal"):
        _require_verified_total_for_close(verifying, 992500.0)  # type: ignore[arg-type]
    closed = _require_verified_total_for_close(verifying, Decimal("992500"))
    assert closed.status is SituationStatus.CLOSED


def test_cross_company_transition_rejected() -> None:
    """company_id is immutable: tampered copies are rejected everywhere."""
    before = _fs231(SituationStatus.DETECTED)
    tampered = before.model_copy(update={"company_id": "acme"})
    assert tampered.company_id == "acme"
    assert tampered != before
    with pytest.raises(ValidationError, match="meridian"):
        FinancialSituation.model_validate(tampered.model_dump())
    with pytest.raises(ValueError, match="immutable"):
        emit_for_transition(before, tampered, at=BASE_AT, actor="mallory")
    with pytest.raises(ValidationError, match="meridian"):
        FinancialSituation(
            situation_id=SITUATION_ID,
            company_id="acme",
            expected=Decimal("1000000"),
            razorpay_net=Decimal("972500"),
            quickbooks=Decimal("982500"),
            legacy=Decimal("982500"),
            status=SituationStatus.DETECTED,
        )


def test_cross_company_audit_never_recorded() -> None:
    """A cross-company attempt leaves the audit log empty."""
    log = AuditLog()
    with pytest.raises(ValueError, match="immutable"):
        emit_for_transition(
            _fs231(SituationStatus.DETECTED),
            _fs231(SituationStatus.DETECTED).model_copy(
                update={"company_id": "acme", "status": SituationStatus.TRIAGED}
            ),
            at=BASE_AT,
            actor="mallory",
        )
    assert len(log) == 0


def test_garbage_status_strings_rejected() -> None:
    """Unknown statuses are rejected at the enum and model boundaries."""
    with pytest.raises(ValueError, match="BOGUS"):
        SituationStatus("BOGUS")
    with pytest.raises(ValidationError):
        FinancialSituation(
            situation_id=SITUATION_ID,
            company_id="meridian",
            expected=Decimal("1000000"),
            razorpay_net=Decimal("972500"),
            quickbooks=Decimal("982500"),
            legacy=Decimal("982500"),
            status="BOGUS",  # type: ignore[arg-type]
        )
    with pytest.raises((AttributeError, ValueError, ValidationError)):
        _fs231(SituationStatus.DETECTED).transition_to("BOGUS")  # type: ignore[arg-type]


def test_none_actor_rejected() -> None:
    """An audit event without an actor is refused."""
    with pytest.raises(ValueError, match="actor"):
        emit_for_transition(
            _fs231(SituationStatus.DETECTED),
            _fs231(SituationStatus.TRIAGED),
            at=BASE_AT,
            actor=None,  # type: ignore[arg-type]
        )


def test_mismatched_situation_ids_rejected() -> None:
    """One event records one situation: cross-case moves are refused."""
    other = FinancialSituation(
        situation_id="FS-2026-0916-00232",
        company_id="meridian",
        expected=Decimal("500000"),
        razorpay_net=Decimal("495000"),
        quickbooks=Decimal("495000"),
        legacy=Decimal("495000"),
        status=SituationStatus.TRIAGED,
    )
    with pytest.raises(ValueError, match="across situations"):
        emit_for_transition(
            _fs231(SituationStatus.DETECTED),
            other,
            at=BASE_AT,
            actor="finsight-test-harness",
        )


def test_noop_transition_records_nothing() -> None:
    """A record must move state: same-status pairs are refused."""
    with pytest.raises(ValueError, match="must differ"):
        emit_for_transition(
            _fs231(SituationStatus.DETECTED),
            _fs231(SituationStatus.DETECTED),
            at=BASE_AT,
            actor="finsight-test-harness",
        )
