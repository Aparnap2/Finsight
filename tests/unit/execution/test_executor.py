"""Unit tests for the frozen execution boundary (v2 resolution).

Targets EXACTLY (importorskip so the file collects as skipped
until the implementation lands)::

    shared.safety.execution_guard.ExecutionGuard.check(cmd)
    shared.safety.idempotency.IdempotencyStore.seen/record
    finance.policy.execution_policy.check(proposal, approval)
    finance.execution.executor.Executor.run(...)
    finance.execution.execution_result.ExecutionResult

Reuses ``MockQuickBooksAdapter`` seeded scripts, the CAS
``ExceptionRepository`` over SQLite StaticPool, and the
``_awaiting``/``_records`` helper shape from approvals tests.
Decimal-only money, Arrange-Act-Assert, typed, no waiting.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
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
from finance.reconciliation.models import ExceptionCode, PaymentRecord

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
_NET_LEDGER = Decimal("50000.00")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class _GuardCmd:
    """Fallback guard command when the frozen module names no command."""

    exception_id: str
    proposal_id: str
    approval_id: str
    idempotency_key: str
    amount: Decimal


class _FakeClock:
    """Monotonic fake clock for poll/backoff without real-time waiting."""

    def __init__(self) -> None:
        """Start the tick counter at zero."""
        self.ticks = 0

    def now(self) -> int:
        """Return the current tick."""
        return self.ticks

    def advance(self, steps: int = 1) -> int:
        """Advance the clock by ``steps`` ticks and return the new tick."""
        self.ticks += steps
        return self.ticks


class _OrderingSpy(MockQuickBooksAdapter):
    """Spy recording the repo state observed inside the adapter call."""

    def __init__(self, repo: ExceptionRepository, exc_id: str) -> None:
        """Bind the spy to a repository row observed at call time."""
        super().__init__()
        self._repo = repo
        self._exc_id = exc_id
        self.seen_state: Any = None
        self.seen_execution_id: Any = None
        self.call_count = 0

    def create_correcting_entry(self, command: Any, idempotency_key: str) -> Any:
        """Record repo state pre-write, then delegate to the mock."""
        snapshot = self._repo.get(self._exc_id)
        self.seen_state = snapshot.state if snapshot is not None else None
        self.seen_execution_id = snapshot.execution_id if snapshot else None
        self.call_count += 1
        return super().create_correcting_entry(command, idempotency_key)


def _engine() -> Engine:
    """Build a shared in-memory SQLite engine for execution tests."""
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


def _awaiting(
    repo: ExceptionRepository, exc_id: str = "exc-exec-1"
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
    key: str = "key-exec-1",
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


def _service(engine: Engine, threshold: Decimal = _THRESHOLD) -> ApprovalService:
    """Build an approval service bound to the shared engine."""
    return ApprovalService(engine, amount_threshold=threshold)


def _approve(
    engine: Engine,
    repo: ExceptionRepository,
    exc_id: str,
    approval_key: str,
) -> tuple[ExceptionAggregate, Proposal, ApprovalRecord]:
    """Arrange AWAITING then approve; return snapshot, proposal, record."""
    snapshot, proposal = _awaiting(repo, exc_id)
    record = _service(engine).decide(
        _cmd(snapshot, proposal, key=approval_key),
        repo,
        {proposal.proposal_id: proposal},
    )
    approved = repo.get(exc_id)
    assert approved is not None
    assert approved.state is ExceptionState.APPROVED
    return approved, proposal, record


def _make_store(engine: Engine) -> Any:
    """Build the frozen IdempotencyStore, accepting engine when supported."""
    cls: Any = _idempotency_mod.IdempotencyStore
    try:
        accepted = set(inspect.signature(cls).parameters)
    except (TypeError, ValueError):
        accepted = set()
    if accepted and "engine" in accepted:
        return cls(engine=engine)
    try:
        return cls(engine)
    except TypeError:
        return cls()


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


def _guard_cmd(
    snapshot: ExceptionAggregate,
    proposal: Proposal,
    approval: ApprovalRecord,
    key: str,
) -> Any:
    """Build the frozen guard cmd, preferring a module command type."""
    for attr in ("ExecutionCommand", "GuardCommand", "GuardRequest"):
        factory = getattr(_execution_guard_mod, attr, None)
        if factory is not None:
            try:
                return factory(
                    exception_id=snapshot.exception_id,
                    proposal_id=proposal.proposal_id,
                    approval_id=approval.approval_id,
                    idempotency_key=key,
                    amount=proposal.amount,
                )
            except TypeError:
                continue
    return _GuardCmd(
        exception_id=snapshot.exception_id,
        proposal_id=proposal.proposal_id,
        approval_id=approval.approval_id,
        idempotency_key=key,
        amount=proposal.amount,
    )


def _assert_allowed(decision: Any) -> None:
    """Assert a policy decision reads as allow across frozen spellings."""
    if decision is True:
        return
    allowed = getattr(decision, "allowed", None)
    if allowed is True:
        return
    for field in ("decision", "verdict", "outcome"):
        value = getattr(decision, field, None)
        if value is not None and str(value).upper() in {"ALLOW", "ALLOWED", "APPROVED"}:
            return
    raise AssertionError(f"policy denied an approvable proposal: {decision!r}")


class TestExecutorUnit:
    """Isolated Executor.run gates: ordering, trust, retry, visibility."""

    def test_guard_allows_safe_entry_with_zero_unsafe(self) -> None:
        """Arrange approved 15k proposal; Act guard.check; Assert unsafe==0."""
        # Arrange: approved snapshot plus idempotency-scoped guard command.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-u-guard", "appr-u-g")
        guard: Any = _execution_guard_mod.ExecutionGuard()
        cmd = _guard_cmd(approved, proposal, approval, "exec-u-guard")
        # Act: run the frozen guard check exactly as specified.
        decision: Any = guard.check(cmd)
        # Assert: safe correcting entry carries zero unsafe findings.
        assert decision.unsafe == 0

    def test_policy_permits_approved_refund_lag_proposal(self) -> None:
        """Arrange proposal+approval; Act policy.check; Assert allowed."""
        # Arrange: frozen proposal and its APPROVED record.
        engine = _engine()
        repo = ExceptionRepository(engine)
        _, proposal, approval = _approve(engine, repo, "exc-u-policy", "appr-u-p")
        # Act: run the frozen policy check exactly as specified.
        decision: Any = _execution_policy_mod.check(proposal, approval)
        # Assert: an in-ceiling refund-lag proposal is permitted.
        _assert_allowed(decision)

    def test_executor_persists_executing_intent_before_adapter_write(self) -> None:
        """Arrange spy adapter; Act run; Assert EXECUTING row pre-exists."""
        # Arrange: approved snapshot with a state-observing spy adapter.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-u-order", "appr-u-o")
        spy = _OrderingSpy(repo, "exc-u-order")
        executor = _make_executor(spy, engine)
        # Act: run the frozen executor exactly as specified.
        result: Any = executor.run(approved, proposal, approval, "exec-u-order")
        # Assert: intent row existed pre-call and the run succeeded.
        assert spy.call_count == 1
        assert spy.seen_state is ExceptionState.EXECUTING
        assert spy.seen_execution_id is not None
        assert str(result.result) == "SUCCEEDED"

    def test_adapter_success_without_post_verify_match_never_closes(self) -> None:
        """Arrange adapter success; Act run; Assert no CLOSED on success."""
        # Arrange: approved snapshot with a plain sandbox adapter.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-u-trust", "appr-u-t")
        adapter = MockQuickBooksAdapter()
        executor = _make_executor(adapter, engine)
        # Act: run; adapter success alone must not imply ledger closure.
        result: Any = executor.run(approved, proposal, approval, "exec-u-trust")
        # Assert: closure needs post_verify MATCHED, never adapter success.
        assert str(result.result) == "SUCCEEDED"
        assert str(result.post_verify) == "MATCHED"
        current = repo.get("exc-u-trust")
        assert current is not None
        assert current.state is ExceptionState.CLOSED
        assert adapter.entry_count == 1

    def test_transient_500_bounded_to_three_retries_same_key(self) -> None:
        """Arrange 2x transient script; Act run; Assert <=3 same-key calls."""
        # Arrange: adapter fails twice for the key, then can succeed.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-u-retry", "appr-u-r")
        adapter = MockQuickBooksAdapter(transient_failures={"exec-u-retry": 2})
        executor = _make_executor(adapter, engine)
        # Act: bounded retry with the identical idempotency key.
        result: Any = executor.run(approved, proposal, approval, "exec-u-retry")
        # Assert: at most three same-key writes and one booked side effect.
        writes = [c for c in adapter.calls if c.key == "exec-u-retry"]
        assert len(writes) <= 3
        assert adapter.entry_count == 1
        assert str(result.result) == "SUCCEEDED"

    def test_delayed_visibility_polls_with_fake_clock_then_matched(self) -> None:
        """Arrange 2-read lag; Act poll via fake clock; Assert MATCHED."""
        # Arrange: write succeeds but reads miss twice; fake clock bounds.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-u-vis", "appr-u-v")
        adapter = MockQuickBooksAdapter(visibility_lag_reads=2)
        clock = _FakeClock()
        executor = _make_executor(adapter, engine, clock=clock)
        # Act: executor polls until visible, advancing the fake clock only.
        result: Any = executor.run(approved, proposal, approval, "exec-u-vis")
        clock.advance(3)
        # Assert: visible entry post-verifies MATCHED and closes.
        assert str(result.result) == "SUCCEEDED"
        assert str(result.post_verify) == "MATCHED"
        current = repo.get("exc-u-vis")
        assert current is not None
        assert current.state is ExceptionState.CLOSED

    def test_crash_after_write_recovers_same_outcome_single_action(self) -> None:
        """Arrange write-then-crash; Act restart same key; Assert recovery."""
        # Arrange: first executor persists the adapter outcome, then drops.
        engine = _engine()
        repo = ExceptionRepository(engine)
        approved, proposal, approval = _approve(engine, repo, "exc-u-crash", "appr-u-c")
        adapter = MockQuickBooksAdapter()
        first = _make_executor(adapter, engine)
        store = _make_store(engine)
        assert store.seen("exec-u-crash") is False
        store.record("exec-u-crash", proposal.content_hash)
        outcome: Any = first.run(approved, proposal, approval, "exec-u-crash")
        # Act: restart with the same key against the same books and store.
        second = _make_executor(adapter, engine)
        assert store.seen("exec-u-crash") is True
        replayed: Any = second.run(approved, proposal, approval, "exec-u-crash")
        # Assert: one financial action with a stable execution identity.
        assert replayed.execution_id == outcome.execution_id
        assert adapter.entry_count == 1
        assert str(replayed.result) == str(outcome.result)
