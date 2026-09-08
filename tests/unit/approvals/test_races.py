"""Approval race tests (T3): losers conflict, pins stay immutable.

Measurable T3 gates, all deterministic over one shared ``StaticPool``
SQLite engine with two repository handles (no threads, no sleep, no
LLM): approve-vs-reject yields a single winner (R1), double-approve
leaves no version increment and at most one record (R2), and a stale v1
pin skews while the v3 approval stays an immutable history row after a
v4 mutation (R3). Helpers reuse the ``test_service.py`` shape.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from finance.approvals.decision import ApprovalCommand
from finance.approvals.service import ApprovalService
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.approval import ApprovalPin
from finance.exceptions.errors import ApprovalSkewError, ConcurrencyConflictError
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
    """Build a shared in-memory SQLite engine for approval races."""
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
    repo: ExceptionRepository, exc_id: str = "exc-race-0"
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


class TestApprovalRaces:
    """T3 race gates: one winner, no increment, immutable history."""

    def test_r1_approve_vs_reject_same_version_single_winner(self) -> None:
        """Approve and reject racing one version leave one terminal state."""
        # Arrange: two handles over one shared engine, one awaiting v6.
        engine = _engine()
        repo_a = ExceptionRepository(engine)  # type: ignore[arg-type]
        repo_b = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo_a, "exc-race-r1")
        contender = repo_b.get("exc-race-r1")
        assert contender is not None
        assert contender.state_version == snapshot.state_version
        lookup = {proposal.proposal_id: proposal}
        service = _service(engine)
        # Act: approve wins; reject on the same version loses.
        winner = service.decide(
            _cmd(snapshot, proposal, key="key-r1-approve", decision="APPROVED"),
            repo_a,
            lookup,
        )
        with pytest.raises(ConcurrencyConflictError, match="CONCURRENCY_CONFLICT"):
            service.decide(
                _cmd(contender, proposal, key="key-r1-reject", decision="REJECTED"),
                repo_b,
                lookup,
            )
        # Assert: exactly one terminal state, one record, version + 1.
        current = repo_a.get("exc-race-r1")
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.state_version == snapshot.state_version + 1
        assert current.approval_id == winner.approval_id
        assert current.execution_id is None
        records = service.get_for_exception("exc-race-r1")
        assert len(records) == 1
        assert records[0].approval_id == winner.approval_id

    def test_r2_double_approve_same_version_second_conflicts(self) -> None:
        """A replayed version never increments and never duplicates."""
        # Arrange: one awaiting aggregate at v6.
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-race-r2")
        lookup = {proposal.proposal_id: proposal}
        service = _service(engine)
        # Act: first approve wins; second approve on the same version loses.
        first = service.decide(_cmd(snapshot, proposal, key="key-r2-first"), repo, lookup)
        assert first.state_version == snapshot.state_version + 1
        with pytest.raises(ConcurrencyConflictError, match="CONCURRENCY_CONFLICT"):
            service.decide(_cmd(snapshot, proposal, key="key-r2-second"), repo, lookup)
        # Assert: no version increment, single record max, winner intact.
        current = repo.get("exc-race-r2")
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.state_version == snapshot.state_version + 1
        assert current.approval_id == first.approval_id
        records = service.get_for_exception("exc-race-r2")
        assert len(records) == 1
        assert records[0].approval_id == first.approval_id

    def test_r3_stale_v1_pin_skews_v3_approval_immutable_after_v4(self) -> None:
        """Stale v1 REJECT skews; the v3 approval survives a v4 mutation."""
        # Arrange: awaiting aggregate with a v1 -> v2 -> v3 (hashA) lineage.
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, v1 = _awaiting(repo, "exc-race-r3")
        v2 = mutate_proposal(v1, rationale="r3 second pass adds context.")
        v3 = mutate_proposal(v2, rationale="r3 third pass finalizes context.")
        assert (v1.version, v2.version, v3.version) == (1, 2, 3)
        assert v3.content_hash != v1.content_hash
        service = _service(engine)
        # Act: REJECT pinning stale v1 against HEAD v3 skews (gate 5/6).
        stale = ApprovalCommand(
            exception_id=snapshot.exception_id,
            proposal_id=v1.proposal_id,
            proposal_version=v1.version,
            proposal_content_hash=v1.content_hash,
            approver_id="approver-1",
            decision="REJECTED",  # type: ignore[arg-type]
            idempotency_key="key-r3-stale",
            expected_state_version=snapshot.state_version,
        )
        with pytest.raises(ApprovalSkewError):
            service.decide(stale, repo, {v3.proposal_id: v3})
        # Assert: skew mutates nothing while still awaiting.
        current = repo.get("exc-race-r3")
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.state_version == snapshot.state_version
        assert current.approval_id is None
        assert service.get_for_exception("exc-race-r3") == []
        # Act: approve HEAD v3 (hashA), then drift the proposal to v4 (hashB).
        record = service.decide(
            _cmd(snapshot, v3, key="key-r3-approve"), repo, {v3.proposal_id: v3}
        )
        assert record.decision.value == "APPROVED"
        assert record.pin_triple() == v3.pin_triple()
        v4 = mutate_proposal(v3, rationale="r3 post-approval drift.")
        assert v4.version == 4
        assert v4.content_hash != v3.content_hash
        # Assert: one immutable history row still pins v3, never v4.
        history = service.get_for_exception("exc-race-r3")
        assert len(history) == 1
        assert history[0].pin_triple() == v3.pin_triple()
        assert history[0].pin_triple() != v4.pin_triple()
        resumed = service.get_by_idempotency_key("key-r3-approve")
        assert resumed is not None
        assert resumed.approval_id == record.approval_id
        # Assert: the execution-equivalent pin check still skews v1 vs v4.
        stale_pin = ApprovalPin(
            proposal_id=v1.proposal_id,
            proposal_version=v1.version,
            content_hash=v1.content_hash,
            approval_id=record.approval_id,
        )
        with pytest.raises(ApprovalSkewError):
            stale_pin.verify(v4.proposal_id, v4.version, v4.content_hash)
        current = repo.get("exc-race-r3")
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.state_version == snapshot.state_version + 1
        assert current.approval_id == record.approval_id
        assert current.execution_id is None
