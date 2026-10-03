"""Commit 5 — failure-injection matrix across the execution state machine.

For each seam between APPROVED → EXECUTING → intent row → adapter write →
external_reference → POST_VERIFYING → verification → CLOSED, assert the
system never reports false success and that recovery performs no second
authoritative mutation. Strict tenant xfail in the boundary suite is out of
scope for this slice.
"""

from __future__ import annotations

from typing import Any

import pytest

from finance.accounting.errors import TransientError
from finance.accounting.mock import MockQuickBooksAdapter
from finance.exceptions.models import Base, ExceptionAuditRow
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from tests.unit.execution.test_execution_boundary import _run_one, _Seed
from tests.unit.execution.test_executor import (
    _engine,
    _make_executor,
    _records,
)


class TestIntentCommitBoundary:
    def test_intent_commit_failure_leaves_no_partial_state_and_retry_succeeds(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor = _make_executor(adapter, engine)

        ExceptionAuditRow.__table__.drop(engine)  # type: ignore[arg-type]
        r1 = executor.run(seed.approved, seed.proposal, seed.approval, "key-fi-1")
        # COMMIT of row+audit+intent is atomic → nothing persisted
        assert str(r1.result) == "REJECTED"
        repo = ExceptionRepository(engine)
        current = repo.get(seed.approved.exception_id)
        assert current is not None
        assert current.state is ExceptionState.APPROVED
        assert current.execution_id is None

        # retry works once the audit table is restored
        Base.metadata.create_all(engine)
        r2 = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-fi-1"
        )
        assert str(r2.result) == "SUCCEEDED"
        final = repo.get(seed.approved.exception_id)
        assert final is not None and final.state is ExceptionState.CLOSED
        creates = [c for c in adapter.calls if c.op == "create_correcting_entry"]
        assert len(creates) == 1


class TestAdapterFailureSeams:
    def test_adapter_transient_failure_books_nothing_terminal_failed_escalated(self) -> None:
        engine = _engine()
        seed = _Seed(engine)

        class _TransientAdapter(MockQuickBooksAdapter):
            def create_correcting_entry(self, command: Any, idempotency_key: str) -> Any:
                raise TransientError("timeout")

        adp = _TransientAdapter()
        r1 = _run_one(engine, adp, seed, "key-fi-2")
        assert str(r1.result) == "FAILED"
        assert str(r1.post_verify) == "MISMATCH"
        repo = ExceptionRepository(engine)
        final = repo.get(seed.approved.exception_id)
        assert final is not None
        assert final.state is ExceptionState.ESCALATED
        # bounded retries, same key, no booked entry
        creates = [c for c in adp.calls if c.op == "create_correcting_entry"]
        assert len(creates) <= 3
        assert all(c.outcome.value != "SUCCESS" for c in creates)

        # retry replays the terminal outcome without a new write
        r2 = _run_one(engine, adp, seed, "key-fi-2")
        assert str(r2.result) == "FAILED"
        assert r2.execution_id == r1.execution_id

    def test_update_row_transport_failure_surfaces_as_persistence_error(self) -> None:
        # Direct seam probe: the Executor's row-write must convert SQL
        # transport errors into the typed PersistenceError.
        engine = _engine()
        executor = _make_executor(MockQuickBooksAdapter(), engine)
        from finance.execution.models import ExecutionRow as _Row
        from shared.safety.errors import PersistenceError

        _Row.__table__.drop(engine)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError):
            executor._update_row("tenant-acme", "key-fi-row", external_reference="x")

    def test_local_persist_failure_after_adapter_write_recovers_without_second_write(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor = _make_executor(adapter, engine)

        from shared.safety.errors import PersistenceError

        def _persist_failed(*a: Any, **k: Any) -> Any:
            raise PersistenceError("simulated local persist failure of external_reference")

        executor._update_row = _persist_failed  # type: ignore[assignment]
        raised = None
        r1 = None
        try:
            r1 = executor.run(seed.approved, seed.proposal, seed.approval, "key-fi-3")
        except BaseException as exc:  # noqa: BLE001
            raised = exc

        # RED: was raw OperationalError during _update_row; now typed REJECTED
        assert raised is None, f"raw {type(raised).__name__}"
        assert str(r1.result) == "REJECTED"

        # The adapter write is committed but unrecognized locally: exception
        # must still be recoverable, NOT falsely CLOSED and NOT re-written.
        live = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert live is not None
        assert live.state is ExceptionState.EXECUTING
        creates = [c for c in adapter.calls if c.op == "create_correcting_entry"]
        assert len(creates) == 1

        retry_exec = _make_executor(adapter, engine)
        r2 = retry_exec.run(seed.approved, seed.proposal, seed.approval, "key-fi-3")
        opens = [c for c in adapter.calls if c.op == "create_correcting_entry"]
        assert len(opens) == 1, "recovery must not write twice"
        assert live is not None
        final = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert final is not None and final.state is ExceptionState.CLOSED
        assert str(r2.result) == "SUCCEEDED"

    def test_crash_after_ref_before_verify_recovers_without_second_write(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor = _make_executor(adapter, engine)

        # Worker dies mentally once at the POST_VERIFYING CAS
        original = executor._cas
        called: dict[str, int] = {"n": 0}

        def _cas_crash_once(*args: Any, **kwargs: Any) -> Any:
            called["n"] += 1
            if called["n"] == 1:
                raise RuntimeError("process interrupted")
            return original(*args, **kwargs)

        executor._cas = _cas_crash_once  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="process interrupted"):
            executor.run(seed.approved, seed.proposal, seed.approval, "key-fi-4")

        creates = [c for c in adapter.calls if c.op == "create_correcting_entry"]
        assert len(creates) == 1

        # Retry from persisted state — the local intent must already be intact
        # and recovery must NOT re-execute the write.
        live = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert live is not None
        assert live.state in (ExceptionState.EXECUTING, ExceptionState.POST_VERIFYING)

        r2 = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-fi-4"
        )
        creates2 = [c for c in adapter.calls if c.op == "create_correcting_entry"]
        assert len(creates2) == 1
        final = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert final is not None and final.state is ExceptionState.CLOSED
        assert str(r2.result) == "SUCCEEDED"

    def test_verification_mismatch_is_terminal_escalated_not_persistence_or_success(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)

        processor, ledger = _records()
        # Marry the two MISMATCHED legs: processor-side expects, ledger confirms.
        executor = _make_executor(adapter, engine, ledger_leg=ledger, processor_leg=processor)
        r1 = executor.run(seed.approved, seed.proposal, seed.approval, "key-fi-5")
        assert str(r1.result) == "FAILED"
        assert str(r1.post_verify) == "MISMATCH"
        final = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert final is not None
        assert final.state is ExceptionState.ESCALATED
        assert final.state is not ExceptionState.CLOSED
