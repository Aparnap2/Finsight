"""Phase 5 API tests: POST /execute and POST /verify via the controlled path.

Mounts ONLY the new ``execution_routes`` router in a minimal app with a
fixed actor (mirroring the frozen approval-races ``_build_app`` pattern):
valid inputs reuse the frozen P6 slice fixture builders (imported, never
edited). No live server, no real DB — shared in-memory SQLite engine plus
``MockQuickBooksAdapter`` doubles. Every success test proves via spies
that ``authorize_execution`` ran before the executor entry (bypass
impossible); a static test proves no other endpoint path reaches
``Executor.run``.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import tests.integration.test_p6_executable_slice as p6s
from apps.api import execution_routes as ex
from apps.api.execution_routes import (
    get_amount_threshold,
    get_db_session,
    get_executor_factory,
    get_proposal_lookup,
    get_verify_bundle,
    router,
)
from finance.accounting.mock import MockQuickBooksAdapter
from finance.approvals.service import ApprovalService
from finance.exceptions.repository import ExceptionRepository
from finance.execution.executor import Executor
from finance.verification.orchestrator import R2Observation

_TENANT = p6s._TENANT
_SIT = "FS-TEST-001"


def _body(snapshot: Any, proposal: Any, *, key: str, exec_key: str) -> dict[str, Any]:
    """Decision coordinates plus execution binding (no money/action)."""
    return {
        "exception_id": snapshot.exception_id,
        "proposal_id": proposal.proposal_id,
        "proposal_version": proposal.version,
        "proposal_content_hash": proposal.content_hash,
        "approver_id": "approver-1",
        "decision": "APPROVED",
        "idempotency_key": key,
        "execution_idempotency_key": exec_key,
        "expected_state_version": snapshot.state_version,
        "situation_id": _SIT,
        "company_id": "meridian",
    }


def _seed() -> tuple[Any, Any, Any, MockQuickBooksAdapter, Executor]:
    """Fresh engine, one awaiting aggregate, and a spy executor on it."""
    engine = p6s._engine()
    repo = ExceptionRepository(engine)  # type: ignore[arg-type]
    snapshot, proposal = p6s._seed_awaiting(repo)
    adapter = MockQuickBooksAdapter()
    executor = Executor(adapter, engine)  # type: ignore[arg-type]
    return engine, snapshot, proposal, adapter, executor


def _build_app(
    engine: Any,
    lookup: dict[str, Any],
    executor: Executor,
    *,
    tenant_id: str | None,
    threshold: Decimal | None = None,
    bundle: dict[str, Any] | None = None,
) -> FastAPI:
    """Mount the execution router with a fixed actor (None = anonymous)."""
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _actor(request: Request, call_next: Any) -> Any:
        if tenant_id is not None:
            request.state.actor = {"tenant_id": tenant_id, "user_id": "tester"}
        return await call_next(request)

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_proposal_lookup] = lambda: lookup
    app.dependency_overrides[get_executor_factory] = lambda: lambda _eng: executor
    if threshold is not None:
        app.dependency_overrides[get_amount_threshold] = lambda: threshold
    if bundle is not None:
        app.dependency_overrides[get_verify_bundle] = lambda: bundle
    return app


def _order_spies(
    monkeypatch: Any, executor: Executor, order: list[str]
) -> MockQuickBooksAdapter | None:
    """Wrap authorize + executor.run to record bypass-proof call order."""
    real_authorize = ex.authorize_execution

    def _auth_spy(**kwargs: Any) -> str:
        order.append("authorization.verify")
        return real_authorize(**kwargs)

    monkeypatch.setattr(ex, "authorize_execution", _auth_spy)
    real_run = executor.run

    def _exec_spy(*args: Any, **kwargs: Any) -> Any:
        order.append("executor.entry")
        return real_run(*args, **kwargs)

    executor.run = _exec_spy  # type: ignore[method-assign]
    return None


class TestExecuteHappy:
    """Happy path: full controlled path to VERIFIED, order asserted."""

    def test_execute_runs_controlled_path_to_verified(self, monkeypatch: Any) -> None:
        """Arrange fixture; Act POST /execute; Assert order + VERIFIED."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        order: list[str] = []
        _order_spies(monkeypatch, executor, order)
        client = TestClient(_build_app(engine, lookup, executor, tenant_id=_TENANT))
        response = client.post(
            "/execute", json=_body(snapshot, proposal, key="api-exec-1", exec_key="x-1")
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["status"] == "VERIFIED"
        assert payload["stages"] == list(ex.STAGES)
        assert payload["verification"]["verdict"] == "VERIFIED"
        assert order == ["authorization.verify", "executor.entry"]
        assert adapter.entry_count == 1


class TestExecuteRefusals:
    """Typed refusals: executor spy silent on every break."""

    def test_policy_rejected_input_refuses_before_execution(self) -> None:
        """Arrange 15k proposal under a 1.00 ceiling; Assert 422, no write."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(
            _build_app(engine, lookup, executor, tenant_id=_TENANT, threshold=Decimal("1.00"))
        )
        response = client.post(
            "/execute", json=_body(snapshot, proposal, key="api-pol-1", exec_key="xp-1")
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "POLICY_DENIED"
        assert adapter.entry_count == 0

    def test_missing_authorization_context_refuses(self) -> None:
        """Arrange anonymous request; Assert 401 before execution."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(_build_app(engine, lookup, executor, tenant_id=None))
        response = client.post(
            "/execute", json=_body(snapshot, proposal, key="api-401-1", exec_key="x401")
        )
        assert response.status_code == 401
        assert adapter.entry_count == 0

    def test_wrong_tenant_refuses_without_effect(self) -> None:
        """Arrange foreign tenant; Assert 403, aggregate untouched."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(_build_app(engine, lookup, executor, tenant_id="tenant-unknown"))
        response = client.post(
            "/execute", json=_body(snapshot, proposal, key="api-403-1", exec_key="x403")
        )
        assert response.status_code == 403
        assert response.json()["code"] == "CROSS_TENANT"
        assert adapter.entry_count == 0
        current = ExceptionRepository(engine).get(snapshot.exception_id)  # type: ignore[arg-type]
        assert current is not None
        assert current.state_version == snapshot.state_version
        assert (
            ApprovalService(engine, amount_threshold=p6s._THRESHOLD).get_for_exception(  # type: ignore[arg-type]
                snapshot.exception_id
            )
            == []
        )

    def test_duplicate_idempotency_key_single_effect(self, monkeypatch: Any) -> None:
        """Arrange same keys replayed; Assert one approval row, one booking."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        order: list[str] = []
        _order_spies(monkeypatch, executor, order)
        client = TestClient(_build_app(engine, lookup, executor, tenant_id=_TENANT))
        payload = _body(snapshot, proposal, key="api-dup-1", exec_key="xdup-1")
        first = client.post("/execute", json=payload)
        assert first.status_code == 201, first.text
        second = client.post("/execute", json=payload)
        assert second.status_code == 200, second.text
        assert second.json()["deduplicated"] is True
        assert second.json()["execution_id"] == first.json()["execution_id"]
        assert adapter.entry_count == 1
        service = ApprovalService(engine, amount_threshold=p6s._THRESHOLD)  # type: ignore[arg-type]
        assert len(service.get_for_exception(snapshot.exception_id)) == 1
        assert order == [
            "authorization.verify",
            "executor.entry",
            "authorization.verify",
            "executor.entry",
        ]


class TestVerifyEndpoint:
    """Standalone verification: VERIFIED report or typed failure, no exec."""

    def _verify_body(self, proposal: Any, *, batch: str = "BATCH-v1") -> dict[str, Any]:
        return {
            "execution_id": "exec-verify-1",
            "authorization_id": "authz-verify-1",
            "situation_id": _SIT,
            "company_id": "meridian",
            "proposal_hash": proposal.content_hash,
            "proposal_version": proposal.version,
            "batch_id": batch,
            "control_total": str(proposal.amount),
            "accepted_total": str(proposal.amount),
        }

    def test_verify_happy_path_returns_verified(self) -> None:
        """Arrange honest readers; Assert 200 VERIFIED report."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(_build_app(engine, lookup, executor, tenant_id=_TENANT))
        response = client.post("/verify", json=self._verify_body(proposal))
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["verdict"] == "VERIFIED"
        assert payload["execution_id"] == "exec-verify-1"
        assert adapter.entry_count == 0  # verify never executes

    def test_verification_failure_returns_typed_failure(self) -> None:
        """Arrange count-skewed reader; Assert 422 VERIFY_COUNT_SKEW."""
        engine, snapshot, proposal, adapter, executor = _seed()
        lookup = {proposal.proposal_id: proposal}
        skewed = proposal.amount - Decimal("1000.00")
        bundle = ex._default_readers()

        def read_legacy(handoff: Any) -> R2Observation:
            return R2Observation(
                accepted_total=skewed,
                prior_total=Decimal("0.00"),
                legacy_after=skewed,
                observed_at=ex._utcnow(),
            )

        bundle = {**bundle, "read_legacy": read_legacy}
        client = TestClient(_build_app(engine, lookup, executor, tenant_id=_TENANT, bundle=bundle))
        response = client.post("/verify", json=self._verify_body(proposal))
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "VERIFY_COUNT_SKEW"
        assert adapter.entry_count == 0


class TestNoBypass:
    """Prove no endpoint path reaches the executor without authorization."""

    def test_single_executor_entry_guarded_by_authorization(self) -> None:
        """Assert one executor call site, textually after authorize."""
        source = inspect.getsource(ex.execute_controlled)
        assert source.count("executor.run(") == 1
        assert source.count("authorize_execution(") == 1
        assert source.index("authorize_execution(") < source.index("executor.run(")
        module_source = inspect.getsource(ex)
        assert module_source.count(".run(fresh, proposal, record,") == 1

    def test_health_still_200(self) -> None:
        """GET /health on the real app still reports healthy."""
        from apps.api.main import app

        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
