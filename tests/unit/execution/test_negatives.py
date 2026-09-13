"""Negative-path tests for the frozen execution boundary (v2 resolution).

Covers the four refusal/failure edges the happy-path suites never touch:

(a) validation-refusal ``FAILED`` -> ``ESCALATED``: an approved proposal
    carrying a legitimately invalid account (via the real
    ``mutate_proposal`` + approval + executor + adapter path) is refused
    by the adapter with no booking;
(b) guard denials: (b1) a non-``APPROVED`` snapshot is refused before any
    side effect; (b2) a skewed approval pin is refused with no mutation;
(c) production-environment refusal through the real
    ``ExecutionGuard(environment=...)`` seam threaded into the executor;
(d) direct ``FAILED`` -> ``CLOSED`` is banned through ``repo.apply``.

Arrange-Act-Assert, Decimal-only money, typed, no waiting. If any test
exposes a real implementation defect, it is left failing and reported
with file:line instead of being fixed or weakened here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import finance.execution.executor as executor_mod
from finance.accounting.mock import MockQuickBooksAdapter
from finance.approvals.decision import ApprovalCommand, ApprovalRecord
from finance.approvals.service import ApprovalService
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.errors import IllegalTransitionError
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.execution.executor import Executor
from finance.execution.models import ExecutionRow
from finance.proposals.builder import build_proposal, mutate_proposal
from finance.proposals.proposal import Proposal
from finance.reconciliation.models import ExceptionCode, PaymentRecord
from shared.safety.execution_guard import ExecutionCommand, ExecutionGuard

_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
_TENANT = "tenant-acme"
_EVIDENCE = ("ev-1", "ev-2")
_THRESHOLD = Decimal("20000.00")
_GROSS = Decimal("50000.00")
_REFUND = Decimal("15000.00")
_NET_PROC = Decimal("35000.00")
_NET_LEDGER = Decimal("50000.00")
_ZERO = Decimal("0.00")


def _engine() -> Engine:
    """Build a shared in-memory SQLite engine for negative-path tests."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _records() -> tuple[PaymentRecord, PaymentRecord]:
    """Processor net 35k (50k-15k refund) vs stale ledger net 50k."""
    processor = PaymentRecord(
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
    ledger = PaymentRecord(
        payment_id="pay-ledger-50k",
        provider="stripe",
        provider_event_id="evt-ledger-1",
        idempotency_key="idem-ledger-1",
        gross=_GROSS,
        fee=_ZERO,
        refund=_ZERO,
        net=_NET_LEDGER,
        currency="USD",
        status="SETTLED",
        occurred_at=_AT,
        tenant_id=_TENANT,
    )
    return (processor, ledger)


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
    proposal = build_proposal(snapshot, _records(), ("ev-1",))
    assert proposal.amount == Decimal("15000.00")
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
    key: str,
) -> ApprovalCommand:
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
    engine: Engine,
    repo: ExceptionRepository,
    exc_id: str,
    approval_key: str,
) -> tuple[ExceptionAggregate, Proposal, ApprovalRecord]:
    """Arrange AWAITING then approve; return snapshot, proposal, record."""
    snapshot, proposal = _awaiting(repo, exc_id)
    record = ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
        _cmd(snapshot, proposal, key=approval_key),
        repo,
        {proposal.proposal_id: proposal},
    )
    approved = repo.get(exc_id)
    assert approved is not None
    assert approved.state is ExceptionState.APPROVED
    return approved, proposal, record


def _execution_row(engine: Engine, key: str) -> ExecutionRow | None:
    """Read one execution record by key without touching executor privates."""
    with Session(engine) as session:
        row = session.get(ExecutionRow, key)
        if row is None:
            return None
        session.expunge(row)
        return row


class _NoEscalateExecutor(Executor):
    """Executor halting the FAILED->ESCALATED edge to hold FAILED for (d).

    The aggregate still reaches ``FAILED`` through the real path (intent
    persist, adapter refusal, FAILED CAS); only the final escalation is
    withheld so the banned ``FAILED`` -> ``CLOSED`` move can be probed.
    """

    def _cas(self, snapshot: Any, target: ExceptionState, *, actor: str) -> Any:
        """CAS-advance unless the target is the withheld ESCALATED edge."""
        if target is ExceptionState.ESCALATED:
            return snapshot
        return super()._cas(snapshot, target, actor=actor)


class TestExecutionNegatives:
    """Four negative-path probes over the frozen execution boundary."""

    def test_a_validation_refusal_fails_and_escalates_without_write(self) -> None:
        """Approved invalid-account proposal fails closed, never booking."""
        # Arrange: approved proposal with a chart-unknown debit account via
        # the real mutate -> approve path (policy admits distinct legs).
        engine = _engine()
        repo = ExceptionRepository(engine)
        snap, built = _awaiting(repo, "exc-neg-a")
        bad = mutate_proposal(built, debit_account="9999-bogus")
        record = ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
            _cmd(snap, bad, key="appr-neg-a"),
            repo,
            {bad.proposal_id: bad},
        )
        live = repo.get("exc-neg-a")
        assert live is not None
        assert live.state is ExceptionState.APPROVED
        adapter = MockQuickBooksAdapter()
        executor = Executor(adapter, engine)
        # Act: run the frozen executor over the invalid-legged proposal.
        result: Any = executor.run(live, bad, record, "exec-neg-a")
        # Assert: FAILED + MISMATCH, ESCALATED never CLOSED, zero bookings,
        # audit present with monotonic versions (+3: intent, fail, esc).
        assert str(result.result) == "FAILED"
        assert str(result.post_verify) == "MISMATCH"
        current = repo.get("exc-neg-a")
        assert current is not None
        assert current.state is ExceptionState.ESCALATED
        assert current.state is not ExceptionState.CLOSED
        assert adapter.entry_count == 0
        refusals = [c for c in adapter.calls if str(c.outcome) == "VALIDATION_FAILURE"]
        assert len(refusals) >= 1
        assert current.state_version == live.state_version + 3
        trail = repo.audit_trail("exc-neg-a")
        assert len(trail) > 0
        versions = [row.actual_version for row in trail]
        assert versions == sorted(versions)

    def test_b_guard_denials_refused_without_mutation(self) -> None:
        """Non-APPROVED snapshot and skewed pin both refuse with no write."""
        # Arrange (b1): AWAITING aggregate plus another case's approval, so
        # the fresh APPROVED state gate refuses before any pin comparison.
        engine = _engine()
        repo = ExceptionRepository(engine)
        stale, stale_proposal = _awaiting(repo, "exc-neg-b1")
        _, _, other_approval = _approve(engine, repo, "exc-neg-b1-x", "a-x")
        adapter_b1 = MockQuickBooksAdapter()
        executor_b1 = Executor(adapter_b1, engine)
        # Act (b1): run against the never-approved snapshot.
        result_b1: Any = executor_b1.run(stale, stale_proposal, other_approval, "exec-neg-b1")
        # Assert (b1): REJECTED, zero adapter calls, state/version intact.
        assert str(result_b1.result) == "REJECTED"
        assert adapter_b1.calls == []
        assert adapter_b1.entry_count == 0
        assert _execution_row(engine, "exec-neg-b1") is None
        current_b1 = repo.get("exc-neg-b1")
        assert current_b1 is not None
        assert current_b1.state is ExceptionState.AWAITING_APPROVAL
        assert current_b1.state_version == stale.state_version
        assert executor_b1.unsafe_action_count == 0
        # Arrange (b2): approved triple, then the proposal drifts post-pin.
        approved, proposal, approval = _approve(engine, repo, "exc-neg-b2", "a-b2")
        skewed = mutate_proposal(proposal, rationale="drifted after approval")
        adapter_b2 = MockQuickBooksAdapter()
        executor_b2 = Executor(adapter_b2, engine)
        # Act (b2): run with a pin that no longer matches the live triple.
        result_b2: Any = executor_b2.run(approved, skewed, approval, "exec-neg-b2")
        # Assert (b2): REJECTED, no mutation, no write, skew counted once.
        assert str(result_b2.result) == "REJECTED"
        assert adapter_b2.calls == []
        assert adapter_b2.entry_count == 0
        assert _execution_row(engine, "exec-neg-b2") is None
        current_b2 = repo.get("exc-neg-b2")
        assert current_b2 is not None
        assert current_b2.state is ExceptionState.APPROVED
        assert current_b2.state_version == approved.state_version
        assert executor_b2.unsafe_action_count == 1

    def test_c_production_environment_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production-guarded runs refuse before any intent or write."""
        # Arrange: approved triple plus the real production guard seam.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-neg-c", "a-c")

        def _production_guard() -> ExecutionGuard:
            """Thread environment="production" through the executor seam."""
            return ExecutionGuard(environment="production")

        monkeypatch.setattr(executor_mod, "ExecutionGuard", _production_guard)
        direct = ExecutionGuard(environment="production").check(
            ExecutionCommand(
                exception_id=approved.exception_id,
                proposal_id=proposal.proposal_id,
                approval_id=approval.approval_id,
                idempotency_key="exec-neg-c",
                amount=proposal.amount,
            )
        )
        assert direct.allowed is False
        assert direct.unsafe > 0
        adapter = MockQuickBooksAdapter()
        executor = Executor(adapter, engine)
        # Act: run with every command denied by the production guard.
        result: Any = executor.run(approved, proposal, approval, "exec-neg-c")
        # Assert: REJECTED, adapter silent, no intent row or transition.
        assert str(result.result) == "REJECTED"
        assert adapter.calls == []
        assert adapter.entry_count == 0
        assert _execution_row(engine, "exec-neg-c") is None
        current = repo.get("exc-neg-c")
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.state_version == approved.state_version
        assert executor.unsafe_action_count > 0

    def test_d_failed_to_closed_directly_rejected(self) -> None:
        """FAILED->CLOSED through repo.apply is banned, audited, unmutated."""
        # Arrange: drive one aggregate to FAILED via the real refusal path.
        engine = _engine()
        repo = ExceptionRepository(engine)
        snap, built = _awaiting(repo, "exc-neg-d")
        bad = mutate_proposal(built, debit_account="9999-bogus")
        record = ApprovalService(engine, amount_threshold=_THRESHOLD).decide(
            _cmd(snap, bad, key="appr-neg-d"),
            repo,
            {bad.proposal_id: bad},
        )
        live = repo.get("exc-neg-d")
        assert live is not None
        adapter = MockQuickBooksAdapter()
        executor = _NoEscalateExecutor(adapter, engine)
        result: Any = executor.run(live, bad, record, "exec-neg-d")
        assert str(result.result) == "FAILED"
        failed = repo.get("exc-neg-d")
        assert failed is not None
        assert failed.state is ExceptionState.FAILED
        version_before = failed.state_version
        # Act: attempt the banned direct close through the CAS repository.
        with pytest.raises(IllegalTransitionError):
            repo.apply(failed, ExceptionState.CLOSED, actor="tester")
        # Assert: rejection audited, state and version unchanged.
        current = repo.get("exc-neg-d")
        assert current is not None
        assert current.state is ExceptionState.FAILED
        assert current.state_version == version_before
        trail = repo.audit_trail("exc-neg-d")
        bans = [
            row
            for row in trail
            if row.outcome == "REJECTED"
            and row.attempted_state == ExceptionState.CLOSED.value
            and row.from_state == ExceptionState.FAILED.value
        ]
        assert len(bans) >= 1
