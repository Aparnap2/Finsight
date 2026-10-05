"""Claim wiring: Executor.run() must enter through IdempotencyStore.claim().

Behavior-preserving refactor of the (payload_hash_for check + record)
pair: claim() binds on FRESH, passes through on REPLAY, and rejects on
CONFLICT. The terminal-row fast-path still precedes the claim, and the
row state machine (terminal replay / intent recovery / fresh execute)
is unchanged — only the entry point moves.
"""

from __future__ import annotations

from typing import Any

from finance.accounting.mock import MockQuickBooksAdapter
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from tests.unit.execution.test_execution_boundary import _Seed
from tests.unit.execution.test_executor import _engine, _make_executor


class _ClaimCountingStore:
    """Proxy delegating to a real store while counting entry calls."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.claim_calls: list[tuple[str, str, str]] = []
        self.record_calls: list[tuple[str, str, str]] = []

    def claim(self, tenant_id: str, key: str, payload_hash: str) -> Any:
        self.claim_calls.append((tenant_id, key, payload_hash))
        return self._inner.claim(tenant_id, key, payload_hash)

    def record(self, tenant_id: str, key: str, payload_hash: str) -> None:
        self.record_calls.append((tenant_id, key, payload_hash))
        return self._inner.record(tenant_id, key, payload_hash)

    def seen(self, tenant_id: str, key: str) -> bool:
        return self._inner.seen(tenant_id, key)

    def payload_hash_for(self, tenant_id: str, key: str) -> str | None:
        return self._inner.payload_hash_for(tenant_id, key)


def _executor_with_proxy(adapter: Any, engine: Any) -> tuple[Any, _ClaimCountingStore]:
    from tests.unit.execution.test_executor import _make_store

    executor = _make_executor(adapter, engine)
    proxy = _ClaimCountingStore(_make_store(engine))
    executor._store = proxy
    return executor, proxy


class TestClaimWiring:
    def test_run_invokes_claim_once_with_tenant_key_hash(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor, proxy = _executor_with_proxy(adapter, engine)

        result = executor.run(seed.approved, seed.proposal, seed.approval, "key-claim-1")

        assert str(result.result) == "SUCCEEDED"
        assert proxy.claim_calls == [
            (seed.approved.tenant_id, "key-claim-1", seed.proposal.content_hash)
        ]
        assert proxy.record_calls == []

    def test_terminal_replay_returns_before_claim(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor, proxy = _executor_with_proxy(adapter, engine)

        first = executor.run(seed.approved, seed.proposal, seed.approval, "key-claim-2")
        assert str(first.result) == "SUCCEEDED"
        proxy.claim_calls.clear()

        second = executor.run(seed.approved, seed.proposal, seed.approval, "key-claim-2")
        assert second.execution_id == first.execution_id
        assert str(second.result) == "SUCCEEDED"
        assert proxy.claim_calls == []

    def test_conflict_rejects_through_claim_with_no_write(self) -> None:
        engine = _engine()
        adapter = MockQuickBooksAdapter()
        seed = _Seed(engine)
        executor, proxy = _executor_with_proxy(adapter, engine)

        proxy._inner.record(seed.approved.tenant_id, "key-claim-3", "different-hash")
        result = executor.run(seed.approved, seed.proposal, seed.approval, "key-claim-3")

        assert str(result.result) == "REJECTED"
        assert [c for c in proxy.claim_calls if c[1] == "key-claim-3"] != []
        creates = [c for c in adapter.calls if c.op == "create_correcting_entry"]
        assert creates == []
        row = ExceptionRepository(engine).get(seed.approved.exception_id)
        assert row is not None and row.state is not ExceptionState.CLOSED
