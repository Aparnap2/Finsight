"""Boundary contract: N deliveries of one logical execution must yield
exactly 1 authoritative mutation, 1 terminal outcome, N-1 replay/conflicts,
even under concurrency, process-crash, and DB failure.

RED gap coverage for Commit 4:
- concurrent duplicate returns typed outcome (not raw ConcurrencyConflictError)
- PersistenceError maps to a typed ExecutionResult (not raw raise)
- same key across tenants must not replay another tenant's result (documented)
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from sqlalchemy import create_engine

from finance.accounting.errors import AccountingError
from finance.accounting.mock import MockQuickBooksAdapter
from finance.exceptions.models import ExceptionRow
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from tests.unit.execution.test_executor import (
    _approve,
    _engine,
    _make_executor,
)


class _Seed:
    def __init__(self, engine: Any, exc_id: str = "exc-boundary") -> None:
        self.repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        self.approved, self.proposal, self.approval = _approve(
            engine, self.repo, exc_id, approval_key=f"{exc_id}-approval"
        )
        self.engine = engine


def _run_one(engine: Any, adapter: Any, seed: _Seed, key: str) -> Any:
    return _make_executor(adapter, engine).run(seed.approved, seed.proposal, seed.approval, key)


class TestSequentialReplay:
    def test_exact_replay_executes_once_and_returns_same_result(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)

        r1 = _run_one(engine, adapter, seed, "key-seq-1")
        assert str(r1.result) == "SUCCEEDED"
        r2 = _run_one(engine, adapter, seed, "key-seq-1")
        r3 = _run_one(engine, adapter, seed, "key-seq-1")

        assert r2.execution_id == r1.execution_id
        assert str(r2.result) == "SUCCEEDED"
        assert r3.execution_id == r1.execution_id
        # exactly one authoritative mutation (create entry), regardless of polls
        creates = [c for c in getattr(adapter, "calls", []) if c.op == "create_correcting_entry"]
        assert len(creates) == 1

    def test_replay_after_distinct_failure_is_terminal(self) -> None:
        engine = _engine()
        seed = _Seed(engine)

        class _FailingAdapter(MockQuickBooksAdapter):
            def create_correcting_entry(self, command: Any, idempotency_key: str) -> Any:
                raise AccountingError("transient")

        adp = _FailingAdapter()
        k = "key-fail-1"
        r1 = _run_one(engine, adp, seed, k)
        assert str(r1.result) == "FAILED"
        creates_after = sum(
            1 for c in getattr(adp, "calls", []) if c.op == "create_correcting_entry"
        )
        r2 = _run_one(engine, adp, seed, k)
        assert str(r2.result) == "FAILED"
        assert r2.execution_id == r1.execution_id
        assert (
            sum(1 for c in getattr(adp, "calls", []) if c.op == "create_correcting_entry")
            == creates_after
        ), "failed run must not write again on replay"


class TestConcurrencyBoundary:
    def test_concurrent_duplicate_returns_typed_outcome(self, tmp_path) -> None:
        db = tmp_path / "persist_boundary_c.db"
        engine = create_engine(
            f"sqlite:///{db}",
            connect_args={"timeout": 15, "check_same_thread": False},
        )
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        results: list[Any] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def work() -> None:
            try:
                barrier.wait(timeout=5)
                results.append(_run_one(engine, adapter, seed, "key-conc-1"))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # RED: loser should NOT receive a raw exception; both must be typed results
        assert errors == []
        assert len(results) == 2
        creates = [c for c in getattr(adapter, "calls", []) if c.op == "create_correcting_entry"]
        assert len(creates) == 1, (
            f"expected exactly one authoritative adapter write, got {len(creates)}: {creates}"
        )
        assert results[0].execution_id == results[1].execution_id
        # exactly one terminal authoritative outcome for the same exe
        final = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert final.state is ExceptionState.CLOSED

    def test_persistence_error_maps_to_typed_result(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)

        ExceptionRow.__table__.drop(engine)  # type: ignore[arg-type]
        result: Any = None
        raised: BaseException | None = None
        try:
            result = _run_one(engine, adapter, seed, "key-perserr")
        except BaseException as exc:  # noqa: BLE001
            raised = exc
        # RED: must return a typed ExecutionResult, not raise raw PersistenceError
        assert raised is None, f"raw {type(raised).__name__} reached caller"
        assert result is not None
        assert str(result.result) in {"FAILED", "REJECTED"}

    def test_conflicting_payload_same_key_no_write(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)

        from tests.unit.execution.test_executor import _make_store

        # Store binds key to a DIFFERENT payload hash than the proposal carries.
        store = _make_store(engine)
        store.record("key-conflict-1", "different-payload-hash")

        bad = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-conflict-1"
        )
        assert str(bad.result) == "REJECTED"
        # no authoritative mutation, no execution row, no CLOSED exception
        creates = [c for c in getattr(adapter, "calls", []) if c.op == "create_correcting_entry"]
        assert creates == []
        row = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert row.state is not ExceptionState.CLOSED


class TestTenantCrossKeyCollision:
    @pytest.mark.xfail(
        reason=(
            "execution ledger is tenant-blind: ExecutionRow PK is idempotency_key, "
            "so same key from another tenant can collide and replay tenant A's result. "
            "Tracking for Commit 6 tenant isolation work."
        ),
        strict=True,
    )
    def test_same_key_cross_tenant_never_returns_other_tenant_result(self) -> None:
        engine = _engine()
        seed_a = _Seed(engine, exc_id="exc-ten-a")
        adapter_a = MockQuickBooksAdapter()
        r_a = _run_one(engine, adapter_a, seed_a, "shared-key")
        assert str(r_a.result) == "SUCCEEDED"

        seed_b = _Seed(engine, exc_id="exc-ten-b")
        adapter_b = MockQuickBooksAdapter()
        r_b = _run_one(engine, adapter_b, seed_b, "shared-key")
        # RED-once (xfail doing its job): must not be tenant A's result
        assert r_b.execution_id != r_a.execution_id
