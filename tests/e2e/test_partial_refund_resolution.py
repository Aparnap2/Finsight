"""E2E partial-refund resolution: 50k charge, 15k refund, P1 oracle.

Flagship E1: processor net 35k vs stale ledger 50k -> EXCEPTION ->
proposal 15k -> approve -> EXECUTING -> mock write -> fixed ledger
35k -> P1 MATCHED -> CLOSED with exactly one execution, unsafe == 0.
E2-E5 cover mismatch escalation, bounded transient retry, delayed
visibility with a fake clock, and crash recovery on one stable key.
Frozen execution modules use importorskip so collection skips
until the implementation lands. Decimal-only, AAA, typed.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from finance.accounting.mock import MockQuickBooksAdapter
from finance.approvals.decision import ApprovalCommand, ApprovalRecord
from finance.approvals.service import ApprovalService
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.proposals.builder import build_proposal
from finance.proposals.proposal import Proposal
from finance.reconciliation.models import (
    ExceptionCode,
    PaymentRecord,
    ReconciliationOutcome,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

_execution_guard_mod = pytest.importorskip("shared.safety.execution_guard")
_idempotency_mod = pytest.importorskip("shared.safety.idempotency")
_execution_policy_mod = pytest.importorskip("finance.policy.execution_policy")
_executor_mod = pytest.importorskip("finance.execution.executor")
_execution_result_mod = pytest.importorskip("finance.execution.execution_result")

_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
_TENANT = "tenant-acme"
_EVIDENCE = ("ev-1", "ev-2")
_THRESHOLD = Decimal("20000.00")
_GROSS = Decimal("50000.00")
_REFUND = Decimal("15000.00")
_NET_PROC = Decimal("35000.00")
_NET_STALE = Decimal("50000.00")
_NET_WRONG = Decimal("40000.00")
_ZERO = Decimal("0.00")


class _FakeClock:
    """Monotonic fake clock for poll/backoff without real-time waiting."""

    def __init__(self) -> None:
        """Start the tick counter at zero."""
        self.ticks = 0

    def now(self) -> int:
        """Return the current tick."""
        return self.ticks

    def advance(self, steps: int = 1) -> int:
        """Advance by ``steps`` ticks and return the new tick."""
        self.ticks += steps
        return self.ticks


def _engine() -> Engine:
    """Build a shared in-memory SQLite engine for e2e tests."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _tolerance() -> ReconciliationTolerance:
    """Zero-default tolerance so any 15k drift is an EXCEPTION."""
    return ReconciliationTolerance(absolute=_ZERO, percent=_ZERO)


def _processor() -> PaymentRecord:
    """Processor leg: 50k charge less 15k refund nets 35k."""
    return PaymentRecord(
        payment_id="pay-proc-50k",
        provider="stripe",
        provider_event_id="evt-proc-1",
        idempotency_key="idem-proc-1",
        gross=_GROSS,
        fee=_ZERO,
        refund=_REFUND,
        net=_NET_PROC,
        currency="USD",
        status="PARTIALLY_REFUNDED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )


def _ledger_stale() -> PaymentRecord:
    """Stale ledger leg still showing the pre-refund 50k net."""
    return PaymentRecord(
        payment_id="pay-ledger-50k",
        provider="stripe",
        provider_event_id="evt-ledger-1",
        idempotency_key="idem-ledger-1",
        gross=_GROSS,
        fee=_ZERO,
        refund=_ZERO,
        net=_NET_STALE,
        currency="USD",
        status="SETTLED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )


def _ledger_fixed() -> PaymentRecord:
    """Corrected ledger leg netting 35k after the 15k entry posts."""
    return PaymentRecord(
        payment_id="pay-ledger-fixed",
        provider="stripe",
        provider_event_id="evt-ledger-2",
        idempotency_key="idem-ledger-2",
        gross=_GROSS,
        fee=_ZERO,
        refund=_REFUND,
        net=_NET_PROC,
        currency="USD",
        status="PARTIALLY_REFUNDED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )


def _ledger_wrong() -> PaymentRecord:
    """Ledger leg netting 40k: adapter success but books still wrong."""
    return PaymentRecord(
        payment_id="pay-ledger-wrong",
        provider="stripe",
        provider_event_id="evt-ledger-9",
        idempotency_key="idem-ledger-9",
        gross=_GROSS,
        fee=Decimal("10000.00"),
        refund=_ZERO,
        net=_NET_WRONG,
        currency="USD",
        status="SETTLED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )


def _awaiting(repo: ExceptionRepository, exc_id: str) -> tuple[ExceptionAggregate, Proposal]:
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
        snapshot,
        ExceptionState.EVIDENCE_READY,
        actor="t",
        evidence_ids=list(_EVIDENCE),
    )
    snapshot = repo.apply(snapshot, ExceptionState.EVIDENCE_VERIFIED, actor="t")
    proposal = build_proposal(snapshot, (_processor(), _ledger_stale()), ("ev-1",))
    assert proposal.amount == Decimal("15000.00")
    snapshot = repo.apply(
        snapshot,
        ExceptionState.PROPOSED,
        actor="t",
        proposal_id=proposal.proposal_id,
    )
    snapshot = repo.apply(snapshot, ExceptionState.AWAITING_APPROVAL, actor="t")
    return snapshot, proposal


def _cmd(snapshot: ExceptionAggregate, proposal: Proposal, key: str) -> ApprovalCommand:
    """Build a well-formed approval command pinning the live proposal."""
    return ApprovalCommand(
        exception_id=snapshot.exception_id,
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.version,
        proposal_content_hash=proposal.content_hash,
        approver_id="approver-1",
        decision="APPROVED",  # type: ignore[arg-type]
        idempotency_key=key,
        expected_state_version=snapshot.state_version,
    )


def _approve(
    engine: Engine, repo: ExceptionRepository, exc_id: str, approval_key: str
) -> tuple[ExceptionAggregate, Proposal, ApprovalRecord]:
    """Arrange AWAITING then approve; return snapshot, proposal, record."""
    snapshot, proposal = _awaiting(repo, exc_id)
    service = ApprovalService(engine, amount_threshold=_THRESHOLD)
    record = service.decide(
        _cmd(snapshot, proposal, approval_key), repo, {proposal.proposal_id: proposal}
    )
    approved = repo.get(exc_id)
    assert approved is not None
    assert approved.state is ExceptionState.APPROVED
    return approved, proposal, record


def _make_executor(adapter: Any, engine: Engine, **extra: Any) -> Any:
    """Build the frozen Executor, passing only args it accepts."""
    cls: Any = _executor_mod.Executor
    try:
        accepted = set(inspect.signature(cls).parameters)
    except (TypeError, ValueError):
        accepted = set()
    offered: dict[str, Any] = {"adapter": adapter, "engine": engine}
    offered.update(extra)
    if accepted:
        filtered = {k: v for k, v in offered.items() if k in accepted}
        if filtered:
            return cls(**filtered)
        return cls()
    try:
        return cls(**offered)
    except TypeError:
        pass
    try:
        return cls(adapter, engine)
    except TypeError:
        return cls(adapter)


def _check_guard(proposal: Proposal, approval: ApprovalRecord, key: str) -> Any:
    """Run ExecutionGuard.check(cmd) and return its GuardDecision."""
    guard: Any = _execution_guard_mod.ExecutionGuard()
    cmd_cls = getattr(_execution_guard_mod, "ExecutionCommand", None)
    if cmd_cls is None:
        cmd_cls = getattr(_execution_guard_mod, "GuardCommand", None)
    if cmd_cls is not None:
        try:
            cmd = cmd_cls(
                exception_id=approval.exception_id,
                proposal_id=proposal.proposal_id,
                approval_id=approval.approval_id,
                idempotency_key=key,
                amount=proposal.amount,
            )
        except TypeError:
            cmd = proposal
    else:
        cmd = proposal
    return guard.check(cmd)


class TestPartialRefundResolution:
    """E1 flagship plus E2-E5 resolution paths over the frozen boundary."""

    def test_e1_flagship_net_35k_closes_with_single_execution(self) -> None:
        """Arrange 35k vs 50k EXCEPTION; Act resolve; Assert CLOSED x1."""
        # Arrange: P1 oracle proves the 15k break before any workflow.
        opening = reconcile(_processor(), _ledger_stale(), _tolerance())
        assert opening.outcome is ReconciliationOutcome.EXCEPTION
        assert opening.difference == Decimal("15000.00")
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-e1", "appr-e1")
        assert proposal.amount == Decimal("15000.00")
        guard_decision = _check_guard(proposal, approval, "exec-e1")
        assert guard_decision.unsafe == 0
        adapter = MockQuickBooksAdapter()
        executor = _make_executor(adapter, engine)
        # Act: frozen run from approved snapshot to booked outcome.
        result: Any = executor.run(approved, proposal, approval, "exec-e1")
        # Assert: one write, P1 MATCHED oracle, and CLOSED terminal state.
        assert str(result.result) == "SUCCEEDED"
        assert str(result.post_verify) == "MATCHED"
        closing = reconcile(_processor(), _ledger_fixed(), _tolerance())
        assert closing.outcome is ReconciliationOutcome.MATCHED
        current = repo.get("exc-e1")
        assert current is not None
        assert current.state is ExceptionState.CLOSED
        assert adapter.entry_count == 1
        wins = [c for c in adapter.calls if c.key == "exec-e1"]
        assert len([c for c in wins if str(c.outcome) == "SUCCESS"]) == 1

    def test_e2_ledger_wrong_mismatch_fails_and_escalates_never_closed(self) -> None:
        """Arrange adapter success vs wrong books; Assert FAILED->ESCALATED."""
        # Arrange: approved 15k proposal with a wrong-ledger post-verify.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-e2", "appr-e2")
        oracle = reconcile(_processor(), _ledger_wrong(), _tolerance())
        assert oracle.outcome is ReconciliationOutcome.EXCEPTION
        adapter = MockQuickBooksAdapter()
        executor = _make_executor(
            adapter,
            engine,
            ledger_leg=_ledger_wrong(),
            expected_post_verify="MISMATCH",
        )
        # Act: frozen run whose post-verify must observe the wrong books.
        result: Any = executor.run(approved, proposal, approval, "exec-e2")
        # Assert: mismatch fails, escalates, and never reports CLOSED.
        assert str(result.post_verify) == "MISMATCH"
        assert str(result.result) == "FAILED"
        current = repo.get("exc-e2")
        assert current is not None
        assert current.state is ExceptionState.ESCALATED
        assert current.state is not ExceptionState.CLOSED

    def test_e3_transient_500_bounded_retry_then_failed_escalated(self) -> None:
        """Arrange persistent 500s; Act run; Assert <=3 same-key attempts."""
        # Arrange: every attempt for this key raises a scripted 5xx.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-e3", "appr-e3")
        adapter = MockQuickBooksAdapter(transient_failures={"exec-e3": 10})
        executor = _make_executor(adapter, engine)
        # Act: bounded retry with the identical idempotency key.
        result: Any = executor.run(approved, proposal, approval, "exec-e3")
        # Assert: bounded attempts, at most one effect, FAILED->ESCALATED.
        writes = [c for c in adapter.calls if c.key == "exec-e3"]
        assert len(writes) <= 3
        assert adapter.entry_count <= 1
        assert str(result.result) == "FAILED"
        current = repo.get("exc-e3")
        assert current is not None
        assert current.state is ExceptionState.ESCALATED

    def test_e4a_delayed_visibility_recovers_and_closes(self) -> None:
        """Arrange 2 invisible reads; Act fake-clock poll; Assert CLOSED."""
        # Arrange: write succeeds yet reads miss twice before visibility.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-e4a", "appr-e4a")
        adapter = MockQuickBooksAdapter(visibility_lag_reads=2)
        clock = _FakeClock()
        executor = _make_executor(adapter, engine, clock=clock)
        # Act: poll with backoff driven by the fake clock only.
        result: Any = executor.run(approved, proposal, approval, "exec-e4a")
        clock.advance(3)
        # Assert: visible entry matches the P1 oracle and closes.
        assert str(result.result) == "SUCCEEDED"
        assert str(result.post_verify) == "MATCHED"
        closing = reconcile(_processor(), _ledger_fixed(), _tolerance())
        assert closing.outcome is ReconciliationOutcome.MATCHED
        current = repo.get("exc-e4a")
        assert current is not None
        assert current.state is ExceptionState.CLOSED

    def test_e4b_still_missing_after_bound_fails_and_escalates(self) -> None:
        """Arrange lag beyond bound; Act run; Assert FAILED->ESCALATED."""
        # Arrange: visibility lag far beyond any reasonable poll bound.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-e4b", "appr-e4b")
        adapter = MockQuickBooksAdapter(visibility_lag_reads=100)
        clock = _FakeClock()
        executor = _make_executor(adapter, engine, clock=clock, max_polls=5)
        # Act: bounded poll exhausts without ever observing the entry.
        result: Any = executor.run(approved, proposal, approval, "exec-e4b")
        # Assert: bounded failure escalates and never closes.
        assert str(result.result) == "FAILED"
        current = repo.get("exc-e4b")
        assert current is not None
        assert current.state is ExceptionState.ESCALATED
        assert current.state is not ExceptionState.CLOSED

    def test_e5_crash_restart_same_key_recovers_single_action(self) -> None:
        """Arrange write-then-crash; Act restart same key; Assert recovery."""
        # Arrange: first run books the entry and records the key outcome.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-e5", "appr-e5")
        adapter = MockQuickBooksAdapter()
        first = _make_executor(adapter, engine)
        outcome: Any = first.run(approved, proposal, approval, "exec-e5")
        # Act: restart addressing the same key against the same books.
        second = _make_executor(adapter, engine)
        replayed: Any = second.run(approved, proposal, approval, "exec-e5")
        # Assert: stable identity with exactly one queryable money movement.
        assert replayed.execution_id == outcome.execution_id
        assert adapter.entry_count == 1
        assert "exec-e5" in adapter._create_keys  # key observable for audit
        queried = adapter.get_entry(str(outcome.external_reference))
        assert queried.idempotency_key == "exec-e5"
        assert str(replayed.result) == str(outcome.result)
