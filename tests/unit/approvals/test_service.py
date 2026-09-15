"""Approval service tests: exactly ten gates, one test per gate.

Each test targets a single gate of ``ApprovalService.decide`` in order:
happy approval, version conflict, hash skew, unknown proposal,
non-awaiting rejection, terminal re-decision conflict, idempotent replay,
policy ceiling, evidence subset, and crash-resume durability. SQLite over
a shared StaticPool engine simulates concurrent handles.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from finance.approvals.decision import ApprovalCommand
from finance.approvals.service import ApprovalService
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.errors import (
    ApprovalSkewError,
    ConcurrencyConflictError,
    IllegalTransitionError,
)
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.proposals.builder import build_proposal, mutate_proposal
from finance.proposals.proposal import Proposal
from finance.reconciliation.models import ExceptionCode, PaymentRecord

_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
_TENANT = "tenant-acme"
_EVIDENCE = ("ev-1", "ev-2")
_THRESHOLD = Decimal("100.00")


def _engine() -> object:
    """Build a shared in-memory SQLite engine for approval tests."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _records() -> tuple[PaymentRecord, PaymentRecord]:
    """Two refund-lag legs with an 8.00 net diff under the threshold."""
    first = PaymentRecord(
        payment_id="pay-1",
        provider="stripe",
        provider_event_id="evt-1",
        idempotency_key="idem-1",
        gross=Decimal("100.00"),
        fee=Decimal("2.00"),
        refund=Decimal("0.00"),
        net=Decimal("98.00"),
        currency="USD",
        status="SETTLED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )
    second = PaymentRecord(
        payment_id="pay-2",
        provider="stripe",
        provider_event_id="evt-2",
        idempotency_key="idem-2",
        gross=Decimal("100.00"),
        fee=Decimal("2.00"),
        refund=Decimal("8.00"),
        net=Decimal("90.00"),
        currency="USD",
        status="PARTIALLY_REFUNDED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )
    return (first, second)


def _awaiting(
    repo: ExceptionRepository, exc_id: str = "exc-t2-1"
) -> tuple[ExceptionAggregate, Proposal]:
    """Drive one aggregate to AWAITING_APPROVAL and draft its proposal."""
    agg = ExceptionAggregate.create(
        exception_id=exc_id,
        tenant_id=_TENANT,
        reconciliation_result_id=f"recon-{exc_id}",
        exception_type=ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
        severity="HIGH",
        created_at=_AT,
    )
    repo.create(agg, actor="seeder")
    snapshot = repo.get(exc_id)
    assert snapshot is not None
    snapshot = repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="t")
    snapshot = repo.apply(
        snapshot, ExceptionState.EVIDENCE_READY, actor="t", evidence_ids=list(_EVIDENCE)
    )
    snapshot = repo.apply(snapshot, ExceptionState.EVIDENCE_VERIFIED, actor="t")
    proposal = build_proposal(snapshot, _records(), ("ev-1",))
    snapshot = repo.apply(
        snapshot,
        ExceptionState.PROPOSED,
        actor="t",
        proposal_id=proposal.proposal_id,
    )
    snapshot = repo.apply(snapshot, ExceptionState.AWAITING_APPROVAL, actor="t")
    assert snapshot.state_version == 6
    return snapshot, proposal


def _cmd(
    snapshot: ExceptionAggregate,
    proposal: Proposal,
    *,
    key: str = "key-1",
    decision: str = "APPROVED",
) -> ApprovalCommand:
    """Build a well-formed command pinning the live proposal."""
    return ApprovalCommand(
        exception_id=snapshot.exception_id,
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.version,
        proposal_content_hash=proposal.content_hash,
        approver_id="approver-1",
        decision=decision,  # type: ignore[arg-type]
        idempotency_key=key,
        expected_state_version=snapshot.state_version,
    )


def _service(engine: object, threshold: Decimal = _THRESHOLD) -> ApprovalService:
    """Build a service bound to the shared engine with a fixed ceiling."""
    return ApprovalService(engine, amount_threshold=threshold)  # type: ignore[arg-type]


class TestApprovalGates:
    """Ten gates in order, one measurable test each."""

    def test_1_approve_happy_transitions_to_approved_v_plus_1(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo)
        record = _service(engine).decide(
            _cmd(snapshot, proposal), repo, {proposal.proposal_id: proposal}
        )
        assert record.decision.value == "APPROVED"
        current = repo.get(snapshot.exception_id)
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.state_version == snapshot.state_version + 1
        assert current.approval_id == record.approval_id
        assert current.execution_id is None  # crash-safe: nothing scheduled

    def test_2_wrong_expected_version_conflicts(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo)
        stale = ApprovalCommand(
            exception_id=snapshot.exception_id,
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.version,
            proposal_content_hash=proposal.content_hash,
            approver_id="approver-1",
            decision="APPROVED",  # type: ignore[arg-type]
            idempotency_key="key-stale",
            expected_state_version=1,
        )
        with pytest.raises(ConcurrencyConflictError, match="CONCURRENCY_CONFLICT"):
            _service(engine).decide(stale, repo, {proposal.proposal_id: proposal})
        current = repo.get(snapshot.exception_id)
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.state_version == snapshot.state_version

    def test_3_wrong_hash_skew_without_mutation(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo)
        tampered = ApprovalCommand(
            exception_id=snapshot.exception_id,
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.version,
            proposal_content_hash="0" * 64,
            approver_id="approver-1",
            decision="APPROVED",  # type: ignore[arg-type]
            idempotency_key="key-skew",
            expected_state_version=snapshot.state_version,
        )
        with pytest.raises(ApprovalSkewError):
            _service(engine).decide(tampered, repo, {proposal.proposal_id: proposal})
        current = repo.get(snapshot.exception_id)
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.state_version == snapshot.state_version
        assert current.approval_id is None

    def test_4_unknown_proposal_rejected(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo)
        with pytest.raises(IllegalTransitionError, match="unknown proposal"):
            _service(engine).decide(_cmd(snapshot, proposal), repo, {})
        current = repo.get(snapshot.exception_id)
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL

    def test_5_not_awaiting_state_rejected(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        agg = ExceptionAggregate.create(
            exception_id="exc-t2-early",
            tenant_id=_TENANT,
            reconciliation_result_id="recon-early",
            exception_type=ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
            severity="HIGH",
            created_at=_AT,
        )
        repo.create(agg, actor="seeder")
        snapshot = repo.get("exc-t2-early")
        assert snapshot is not None
        snapshot = repo.apply(snapshot, ExceptionState.INVESTIGATING, actor="t")
        snapshot = repo.apply(
            snapshot, ExceptionState.EVIDENCE_READY, actor="t", evidence_ids=list(_EVIDENCE)
        )
        snapshot = repo.apply(snapshot, ExceptionState.EVIDENCE_VERIFIED, actor="t")
        proposal = build_proposal(snapshot, _records(), ("ev-1",))
        snapshot = repo.apply(
            snapshot, ExceptionState.PROPOSED, actor="t", proposal_id=proposal.proposal_id
        )
        with pytest.raises(IllegalTransitionError, match="not AWAITING_APPROVAL"):
            _service(engine).decide(
                _cmd(snapshot, proposal), repo, {proposal.proposal_id: proposal}
            )
        current = repo.get("exc-t2-early")
        assert current is not None
        assert current.state is ExceptionState.PROPOSED

    def test_6_second_terminal_decision_conflicts(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-t2-terminal")
        lookup = {proposal.proposal_id: proposal}
        _service(engine).decide(_cmd(snapshot, proposal, key="key-first"), repo, lookup)
        decided = repo.get("exc-t2-terminal")
        assert decided is not None
        retry = ApprovalCommand(
            exception_id=decided.exception_id,
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.version,
            proposal_content_hash=proposal.content_hash,
            approver_id="approver-1",
            decision="REJECTED",  # type: ignore[arg-type]
            idempotency_key="key-second",
            expected_state_version=decided.state_version,
        )
        with pytest.raises(ConcurrencyConflictError, match="already decided"):
            _service(engine).decide(retry, repo, lookup)
        current = repo.get("exc-t2-terminal")
        assert current is not None
        assert current.state is ExceptionState.APPROVED

    def test_7_same_idempotency_key_returns_prior_record(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-t2-idem")
        lookup = {proposal.proposal_id: proposal}
        service = _service(engine)
        first = service.decide(_cmd(snapshot, proposal, key="key-replay"), repo, lookup)
        second = service.decide(_cmd(snapshot, proposal, key="key-replay"), repo, lookup)
        assert second.approval_id == first.approval_id
        assert second.idempotency_key == first.idempotency_key
        assert len(service.get_for_exception("exc-t2-idem")) == 1
        current = repo.get("exc-t2-idem")
        assert current is not None
        assert current.state_version == snapshot.state_version + 1

    def test_8_over_threshold_policy_rejected(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-t2-policy")
        assert proposal.amount > Decimal("5.00")
        tight = _service(engine, threshold=Decimal("5.00"))
        with pytest.raises(IllegalTransitionError, match="policy denied"):
            tight.decide(_cmd(snapshot, proposal), repo, {proposal.proposal_id: proposal})
        current = repo.get("exc-t2-policy")
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.approval_id is None

    def test_9_evidence_unsatisfied_rejected(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-t2-evidence")
        drifted = mutate_proposal(proposal, evidence_ids=("ev-unknown",))
        assert drifted.version == proposal.version + 1
        cmd = ApprovalCommand(
            exception_id=snapshot.exception_id,
            proposal_id=drifted.proposal_id,
            proposal_version=drifted.version,
            proposal_content_hash=drifted.content_hash,
            approver_id="approver-1",
            decision="APPROVED",  # type: ignore[arg-type]
            idempotency_key="key-evidence",
            expected_state_version=snapshot.state_version,
        )
        with pytest.raises(IllegalTransitionError, match="evidence unsatisfied"):
            _service(engine).decide(cmd, repo, {drifted.proposal_id: drifted})
        current = repo.get("exc-t2-evidence")
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL

    def test_10_crash_sim_approved_persists_resumable(self) -> None:
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-t2-crash")
        record = _service(engine).decide(
            _cmd(snapshot, proposal, key="key-crash"),
            repo,
            {proposal.proposal_id: proposal},
        )
        # Simulate a crash: drop every handle, reopen fresh ones on one engine.
        fresh_repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        fresh_service = _service(engine)
        current = fresh_repo.get("exc-t2-crash")
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.state_version == snapshot.state_version + 1
        assert current.approval_id == record.approval_id
        assert current.execution_id is None  # worker resumes scheduling later
        resumed = fresh_service.get_by_idempotency_key("key-crash")
        assert resumed is not None
        assert resumed.approval_id == record.approval_id
        assert resumed.decision.value == "APPROVED"
        assert resumed.pin_triple() == proposal.pin_triple()
