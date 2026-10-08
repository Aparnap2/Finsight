"""P10-05 GREEN: post-expiry retry behavior at the execution boundary.

Expiry may remove replay history but must never make a settled action
executable again. Per persisted execution state, a late retry after
binding expiry must deterministically:

- terminal row → replay the prior outcome (never fresh, no mutation);
- intent row → resume recovery (no second adapter write);
- no row → execute fresh exactly once (nothing ever happened).

Different payloads never create a second mutation either. Adapter
``create_correcting_entry`` counts prove the single-mutation invariant.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from finance.accounting.mock import MockQuickBooksAdapter
from shared.privacy.retention import disposition_for, purge_expired
from tests.unit.execution.test_execution_boundary import _Seed
from tests.unit.execution.test_executor import _engine, _make_executor

OLD = datetime(2020, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _creates(adapter: Any) -> int:
    """Count authoritative adapter writes."""
    return sum(1 for c in adapter.calls if c.op == "create_correcting_entry")


def _expire_binding(engine: Any, tenant_id: str, key: str) -> None:
    """Backdate a binding past TTL and purge it (expiry fixture)."""
    from shared.safety.idempotency import IdempotencyRow

    with Session(engine) as session:
        session.query(IdempotencyRow).filter(
            IdempotencyRow.tenant_id == tenant_id,
            IdempotencyRow.idempotency_key == key,
        ).update({"created_at": OLD, "updated_at": OLD})
        session.commit()
    with Session(engine) as session:
        deleted = purge_expired(session, disposition_for("idempotency_keys"), NOW)
    assert deleted == 1


class TestExpiredTerminalReplays:
    def test_same_payload_replays_without_mutation(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        first = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-1"
        )
        assert str(first.result) == "SUCCEEDED"
        assert _creates(adapter) == 1

        _expire_binding(engine, seed.approved.tenant_id, "key-exp-1")
        second = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-1"
        )
        assert second.execution_id == first.execution_id
        assert str(second.result) == "SUCCEEDED"
        assert _creates(adapter) == 1

    def test_different_payload_causes_no_new_mutation(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        first = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-2"
        )
        assert str(first.result) == "SUCCEEDED"

        _expire_binding(engine, seed.approved.tenant_id, "key-exp-2")
        other = replace(seed.proposal, content_hash="d" * 64)
        retry = _make_executor(adapter, engine).run(
            seed.approved, other, seed.approval, "key-exp-2"
        )
        assert retry is not None
        assert _creates(adapter) == 1

    def test_concurrent_post_expiry_retries_share_outcome(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        first = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-3"
        )
        assert str(first.result) == "SUCCEEDED"

        _expire_binding(engine, seed.approved.tenant_id, "key-exp-3")
        results: list[Any] = []
        barrier = threading.Barrier(2)

        def work() -> None:
            barrier.wait(timeout=5)
            results.append(
                _make_executor(adapter, engine).run(
                    seed.approved, seed.proposal, seed.approval, "key-exp-3"
                )
            )

        threads = [threading.Thread(target=work) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert len(results) == 2
        assert {r.execution_id for r in results} == {first.execution_id}
        assert _creates(adapter) == 1


class TestExpiredIntentRecovers:
    def test_crash_intent_then_expiry_resumes_without_second_write(self) -> None:
        from finance.exceptions.repository import ExceptionRepository
        from finance.exceptions.states import ExceptionState
        from shared.safety.errors import PersistenceError

        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor = _make_executor(adapter, engine)

        def _fail_once(*args: Any, **kwargs: Any) -> Any:
            raise PersistenceError("simulated local persist failure")

        executor._update_row = _fail_once
        crashed = executor.run(seed.approved, seed.proposal, seed.approval, "key-exp-4")
        assert str(crashed.result) == "REJECTED"
        assert _creates(adapter) == 1

        _expire_binding(engine, seed.approved.tenant_id, "key-exp-4")
        recovered = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-4"
        )
        assert str(recovered.result) == "SUCCEEDED"
        assert _creates(adapter) == 1
        final = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert final is not None and final.state is ExceptionState.CLOSED


class TestExpiredAbsentBinding:
    def test_never_bound_key_executes_fresh_exactly_once(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        result = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-5"
        )
        assert str(result.result) == "SUCCEEDED"
        assert _creates(adapter) == 1
        again = _make_executor(adapter, engine).run(
            seed.approved, seed.proposal, seed.approval, "key-exp-5"
        )
        assert again.execution_id == result.execution_id
        assert _creates(adapter) == 1
