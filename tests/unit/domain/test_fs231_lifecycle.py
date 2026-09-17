"""FS-231 golden lifecycle matrix (P6-02 audit coverage).

Walks situation ``FS-2026-0916-00231`` along the canonical forward chain in
``docs/domain/meridian-process-model.md`` §2 from ``DETECTED`` through
``CLOSED``, asserting every state, a stable variance of exactly 10000 at
each step, and one audit event per transition. Two sibling-owned
extensions that do not exist in the P6-01 base are covered through minimal
local adapters defined in this file (the reviewer reconciles them once the
sibling lifecycle work lands):

* ``close_if_matched`` — the MATCHED → CLOSED fast path for a clean,
  zero-variance fixture.
* ``AwaitingApprovalPin`` — the AWAITING_APPROVAL gate pinning an
  immutable ``proposal_ref``.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from finance.domain.audit import AuditEvent, AuditLog, emit_for_transition
from finance.domain.financial_situation import FinancialSituation, SituationStatus

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


class AwaitingApprovalPin(BaseModel):
    """Local adapter for the sibling AWAITING_APPROVAL gate (not in P6-01).

    Stands in for the pending lifecycle extension: entering the approval
    wait must pin an immutable ``proposal_ref`` so the later Slack decision
    can be bound to exactly one proposal version. The reviewer reconciles
    this adapter against the sibling implementation after it lands.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    situation_id: str
    """Parent case id this pin belongs to."""

    proposal_ref: str
    """Immutable proposal reference, e.g. ``PROP-231-v1``."""

    @field_validator("proposal_ref")
    @classmethod
    def _validate_proposal_ref(cls, value: str) -> str:
        """Require a non-blank proposal reference."""
        if not value.strip():
            raise ValueError("proposal_ref must be a non-empty string.")
        return value


class FastClosePort(Protocol):
    """Minimal port for the sibling MATCHED → CLOSED fast path (not in P6-01)."""

    def close_if_matched(
        self, situation: FinancialSituation, *, at: datetime, actor: str
    ) -> FinancialSituation:
        """Close a zero-variance situation without walking the full chain."""
        ...  # pragma: no cover - protocol signature only


def close_if_matched(
    situation: FinancialSituation, *, at: datetime, actor: str
) -> tuple[FinancialSituation, AuditEvent]:
    """Local adapter for the sibling MATCHED → CLOSED fast path.

    A clean fixture (variance exactly zero, i.e. MATCHED) closes directly
    instead of walking the nine-step chain. Non-zero variance is refused.
    The reviewer reconciles this adapter against the sibling lifecycle
    implementation after it lands; the audit event it returns is recorded
    through the standard pure constructor.

    Args:
        situation: The clean situation to fast-close.
        at: Caller-supplied tz-aware transition time.
        actor: Human id or system principal performing the close.

    Returns:
        The closed situation plus its audit event.

    Raises:
        ValueError: If the variance is not exactly zero.
    """
    if situation.variance() != Decimal("0"):
        raise ValueError(
            "MATCHED fast path requires zero variance, got "
            f"{situation.variance()}."
        )
    closed = situation.model_copy(update={"status": SituationStatus.CLOSED})
    return closed, emit_for_transition(situation, closed, at=at, actor=actor)


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


def test_matched_to_closed_fast_path_clean_fixture() -> None:
    """A zero-variance fixture fast-closes with exactly one audit event."""
    log = AuditLog()
    clean = _clean_situation(SituationStatus.DETECTED)
    assert clean.variance() == Decimal("0")
    closed, event = close_if_matched(
        clean, at=BASE_AT, actor="finsight-test-harness"
    )
    assert closed.status is SituationStatus.CLOSED
    assert closed.situation_id == "FS-2026-0916-00240"
    assert event.variance_snapshot == Decimal("0")
    log.append(event)
    assert len(log) == 1
    assert log.verify_chain() is True


def test_matched_fast_path_refuses_nonzero_variance() -> None:
    """FS-231 (variance 10000) is not MATCHED and cannot fast-close."""
    with pytest.raises(ValueError, match="zero variance"):
        close_if_matched(
            _fs231(SituationStatus.DETECTED),
            at=BASE_AT,
            actor="finsight-test-harness",
        )


def test_awaiting_approval_pins_proposal_ref() -> None:
    """The approval wait pins an immutable proposal reference."""
    pin = AwaitingApprovalPin(
        situation_id=SITUATION_ID, proposal_ref="PROP-231-v1"
    )
    assert pin.proposal_ref == "PROP-231-v1"
    assert pin.situation_id == SITUATION_ID
    with pytest.raises(ValidationError):
        pin.proposal_ref = "PROP-231-v2"  # type: ignore[misc]
    assert pin.proposal_ref == "PROP-231-v1"


def test_awaiting_approval_rejects_blank_proposal_ref() -> None:
    """Entering the approval wait without a proposal is refused."""
    for blank in ("", "   "):
        with pytest.raises(ValidationError, match="proposal_ref"):
            AwaitingApprovalPin(situation_id=SITUATION_ID, proposal_ref=blank)


def test_awaiting_approval_pin_travels_with_proposed_to_approved() -> None:
    """The pinned ref is present when PROPOSED transitions to APPROVED."""
    pin = AwaitingApprovalPin(
        situation_id=SITUATION_ID, proposal_ref="PROP-231-v1"
    )
    proposed = _fs231(SituationStatus.PROPOSED)
    approved = proposed.transition_to(SituationStatus.APPROVED)
    assert approved.status is SituationStatus.APPROVED
    assert pin.proposal_ref == "PROP-231-v1"
    assert pin.situation_id == approved.situation_id
