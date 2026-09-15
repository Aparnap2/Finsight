"""Unit gates for the P3.3 rule-based proposal builder (13 tests).

All boundaries are in-memory: no database, no network, no LLM. Amounts
are recomputed from canonical ``PaymentRecord`` legs; ``amount`` is
never accepted as an argument.
"""

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.accounting.errors import UnsupportedActionError
from finance.exceptions.aggregate import ExceptionAggregate
from finance.proposals.builder import (
    EmptyEvidenceError,
    UnverifiedEvidenceError,
    build_proposal,
    mutate_proposal,
    verify_hash,
)
from finance.proposals.proposal import Proposal, ProposalAction
from finance.reconciliation.models import ExceptionCode, PaymentStatus

_FIXED_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _record(**overrides: object) -> object:
    """Build a deterministic PaymentRecord with a valid net invariant."""
    from finance.reconciliation.models import PaymentRecord

    base: dict[str, object] = {
        "payment_id": "pay-001",
        "provider": "stripe",
        "provider_event_id": "evt-001",
        "idempotency_key": "idem-001",
        "gross": Decimal("100000.00"),
        "fee": Decimal("2500.00"),
        "refund": Decimal("0.00"),
        "net": Decimal("97500.00"),
        "currency": "USD",
        "status": PaymentStatus.SETTLED,
        "occurred_at": _FIXED_AT,
        "tenant_id": "tenant-acme",
    }
    base.update(overrides)
    return PaymentRecord(**base)  # type: ignore[arg-type]


def _snapshot(
    exception_type: object = ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
    tenant_id: str = "tenant-acme",
    exception_id: str = "exc-001",
    evidence: tuple[str, ...] = ("ev-1", "ev-2"),
) -> ExceptionAggregate:
    """Build an aggregate sealed at EVIDENCE_VERIFIED via the legal chain."""
    agg = ExceptionAggregate.create(
        exception_id=exception_id,
        tenant_id=tenant_id,
        reconciliation_result_id="recon-001",
        exception_type=exception_type,  # type: ignore[arg-type]
        severity="HIGH",
        evidence_ids=(),
        created_at=_FIXED_AT,
    )
    agg = agg.open_investigation(1, actor="t")
    agg = agg.mark_evidence_ready(2, list(evidence), actor="t")
    return agg.verify_evidence(3, actor="t")


def _refund_pair() -> tuple[object, object]:
    """Expected/observed legs whose net diff recomputes to exactly 15000."""
    expected = _record()
    observed = _record(
        payment_id="pay-001-obs",
        provider_event_id="evt-001-obs",
        idempotency_key="idem-002",
        refund=Decimal("15000.00"),
        net=Decimal("82500.00"),
    )
    return expected, observed


class TestBuildProposal:
    """Gates 1-6: routing, evidence gates, and v1 shape."""

    def test_1_refund_lag_builds_with_recomputed_15000_amount(self) -> None:
        snap = _snapshot()
        proposal = build_proposal(snap, list(_refund_pair()), ("ev-1", "ev-2"))
        assert proposal.action is ProposalAction.CREATE_CORRECTING_ENTRY
        assert proposal.amount == Decimal("15000.00")
        assert (proposal.debit_account, proposal.credit_account) == (
            "4100-refunds",
            "1100-ar",
        )

    def test_2_duplicate_builds_void_action(self) -> None:
        snap = _snapshot(exception_type=ExceptionCode.DUPLICATE_LEDGER_ENTRY)
        proposal = build_proposal(snap, [_record()], ("ev-1",))
        assert proposal.action is ProposalAction.VOID_DUPLICATE
        assert proposal.amount == Decimal("97500.00")

    def test_3_fee_mismatch_raises_unsupported(self) -> None:
        snap = _snapshot(exception_type=ExceptionCode.FEE_MISMATCH)
        with pytest.raises(UnsupportedActionError):
            build_proposal(snap, [_record()], ("ev-1", "ev-2"))

    def test_4_unverified_evidence_rejected(self) -> None:
        snap = ExceptionAggregate.create(
            exception_id="exc-009",
            tenant_id="tenant-acme",
            reconciliation_result_id="recon-009",
            exception_type=ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
            severity="HIGH",
            evidence_ids=(),
            created_at=_FIXED_AT,
        )
        with pytest.raises(UnverifiedEvidenceError):
            build_proposal(snap, list(_refund_pair()), ("ev-1",))

    def test_5_empty_evidence_rejected(self) -> None:
        snap = _snapshot()
        with pytest.raises(EmptyEvidenceError):
            build_proposal(snap, list(_refund_pair()), ())

    def test_6_version_starts_at_1(self) -> None:
        proposal = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        assert proposal.version == 1
        assert proposal.supersedes is None
        assert proposal.requires_hitl is True


class TestHistoryAndHash:
    """Gates 7-10: immutable history and hash binding."""

    def test_7_mutate_bumps_version_and_changes_hash(self) -> None:
        proposal = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        mutated = mutate_proposal(proposal, rationale="Updated rationale.")
        assert mutated.version == proposal.version + 1
        assert mutated.content_hash != proposal.content_hash
        assert mutated.supersedes == proposal.content_hash

    def test_8_old_version_object_unchanged(self) -> None:
        proposal = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        before = (proposal.version, proposal.content_hash, proposal.rationale)
        mutate_proposal(proposal, rationale="Changed.")
        assert (proposal.version, proposal.content_hash, proposal.rationale) == before

    def test_9_verify_hash_true_on_intact(self) -> None:
        proposal = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        assert verify_hash(proposal) is True
        assert proposal.verifies() is True

    def test_10_tampered_copy_fails_verify(self) -> None:
        proposal = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        tampered = dataclasses.replace(proposal, amount=Decimal("1.00"))
        assert verify_hash(tampered) is False


class TestInvariants:
    """Gates 11-13: Decimal-only money, determinism, tenant namespace."""

    def test_11_float_amount_rejected(self) -> None:
        with pytest.raises(TypeError):
            Proposal(
                proposal_id="prop_x",
                exception_id="exc-001",
                version=1,
                action=ProposalAction.CREATE_CORRECTING_ENTRY,
                amount=15000.0,  # type: ignore[arg-type]
                debit_account="4100-refunds",
                credit_account="1100-ar",
                evidence_ids=("ev-1",),
                rationale="r",
                content_hash="",
            )

    def test_12_same_inputs_deterministic_hash(self) -> None:
        first = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        second = build_proposal(_snapshot(), list(_refund_pair()), ("ev-1",))
        assert first.content_hash == second.content_hash
        assert first.proposal_id == second.proposal_id

    def test_13_different_tenant_different_proposal_id(self) -> None:
        left_records = [
            dataclasses.replace(r, tenant_id="tenant-a")  # type: ignore[attr-defined]
            for r in _refund_pair()
        ]
        left = build_proposal(_snapshot(tenant_id="tenant-a"), left_records, ("ev-1",))
        right_records = [
            dataclasses.replace(r, tenant_id="tenant-b")  # type: ignore[attr-defined]
            for r in _refund_pair()
        ]
        right = build_proposal(_snapshot(tenant_id="tenant-b"), right_records, ("ev-1",))
        assert left.proposal_id != right.proposal_id
