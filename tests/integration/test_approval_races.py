"""Approval race integration tests (T3): real restart plus API pinning.

CRASH runs on a file-backed SQLite database so the restart is a real
engine reboot (dispose, then fresh handles on the same file): APPROVED
plus the record triple survive, ``execution_id`` stays None (no
scheduler state exists), and the winner key replays without a duplicate.
PINNED-FIELDS mounts the real ``approvals`` router in a minimal app:
money/action smuggling is 422 with no mutation, an unknown tenant is
403, and missing auth is 401. No sleep, no LLM, Decimal-only money.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.approvals import get_db_session, get_proposal_lookup, router
from finance.approvals.decision import ApprovalCommand
from finance.approvals.service import ApprovalService
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.proposals.builder import build_proposal
from finance.proposals.proposal import Proposal
from finance.reconciliation.models import ExceptionCode, PaymentRecord

_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
_TENANT = "tenant-acme"
_EVIDENCE = ("ev-1", "ev-2")
_THRESHOLD = Decimal("100.00")


def _engine() -> object:
    """Build a shared in-memory SQLite engine for API tests."""
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


def _body(
    snapshot: ExceptionAggregate, proposal: Proposal, *, key: str = "key-api-1"
) -> dict[str, object]:
    """Valid decision coordinates for the pinned proposal (no money)."""
    return {
        "exception_id": snapshot.exception_id,
        "proposal_id": proposal.proposal_id,
        "proposal_version": proposal.version,
        "proposal_content_hash": proposal.content_hash,
        "approver_id": "approver-1",
        "decision": "APPROVED",
        "idempotency_key": key,
        "expected_state_version": snapshot.state_version,
    }


def _build_app(engine: object, lookup: dict[str, Proposal], *, tenant_id: str | None) -> FastAPI:
    """Mount the approvals router with a fixed actor (None = anonymous)."""
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _actor(request: Request, call_next: Any) -> Any:
        """Attach the test actor, or leave it missing for the 401 path."""
        if tenant_id is not None:
            request.state.actor = {"tenant_id": tenant_id, "user_id": "tester"}
        return await call_next(request)

    def _session_override() -> Iterator[Session]:
        """Yield request sessions bound to the shared test engine."""
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_proposal_lookup] = lambda: lookup
    return app


class TestApprovalCrash:
    """Durability across a real restart on one file-backed database."""

    def test_crash_approved_persists_resumable_no_dup_no_scheduler(self, tmp_path: Path) -> None:
        """APPROVED survives dispose plus fresh handles with no dup record."""
        # Arrange: approve on a file-backed database (restart is real).
        url = f"sqlite:///{tmp_path / 'approval_crash.db'}"
        engine = create_engine(url, connect_args={"check_same_thread": False})
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-crash-restart")
        record = _service(engine).decide(
            _cmd(snapshot, proposal, key="key-crash-restart"),
            repo,
            {proposal.proposal_id: proposal},
        )
        expected_triple = proposal.pin_triple()
        expected_version = snapshot.state_version + 1
        # Act: crash — drop every handle; only the sqlite file survives.
        engine.dispose()
        # Assert: fresh handles on the SAME file read APPROVED intact.
        fresh = create_engine(url, connect_args={"check_same_thread": False})
        try:
            fresh_repo = ExceptionRepository(fresh)  # type: ignore[arg-type]
            fresh_service = _service(fresh)
            current = fresh_repo.get("exc-crash-restart")
            assert current is not None
            assert current.state is ExceptionState.APPROVED
            assert current.state_version == expected_version
            assert current.approval_id == record.approval_id
            assert current.execution_id is None  # no scheduler state persisted
            resumed = fresh_service.get_by_idempotency_key("key-crash-restart")
            assert resumed is not None
            assert resumed.approval_id == record.approval_id
            assert resumed.pin_triple() == expected_triple
            assert len(fresh_service.get_for_exception("exc-crash-restart")) == 1
            replayed = fresh_service.decide(
                _cmd(current, proposal, key="key-crash-restart"),
                fresh_repo,
                {proposal.proposal_id: proposal},
            )
            assert replayed.approval_id == record.approval_id
            assert len(fresh_service.get_for_exception("exc-crash-restart")) == 1
        finally:
            fresh.dispose()


class TestApprovalPinnedFields:
    """API pinning: forbid money/action, deny strangers, require auth."""

    def test_extra_amount_action_rejected_422_no_mutation(self) -> None:
        """Smuggled amount/action fields fail closed with zero mutation."""
        # Arrange: awaiting aggregate plus the owning-tenant router app.
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-pin-422")
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(_build_app(engine, lookup, tenant_id=_TENANT))
        payload = dict(_body(snapshot, proposal, key="key-pin-422"))
        payload["amount"] = "8.00"
        payload["action"] = "CREATE_CORRECTING_ENTRY"
        # Act: attempt to smuggle money/action past policy.
        response = client.post("/approvals/decide", json=payload)
        # Assert: 422 from extra=forbid, aggregate untouched, no record.
        assert response.status_code == 422
        current = repo.get("exc-pin-422")
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.state_version == snapshot.state_version
        assert current.approval_id is None
        assert _service(engine).get_for_exception("exc-pin-422") == []

    def test_unknown_tenant_denied_403_no_mutation(self) -> None:
        """A valid body from a foreign tenant is denied without mutation."""
        # Arrange: awaiting aggregate plus a foreign-tenant router app.
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-pin-403")
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(_build_app(engine, lookup, tenant_id="tenant-unknown"))
        # Act: decide with coordinates that would pass for the owner.
        response = client.post(
            "/approvals/decide", json=_body(snapshot, proposal, key="key-pin-403")
        )
        # Assert: 403 cross-tenant denial, aggregate untouched, no record.
        assert response.status_code == 403
        current = repo.get("exc-pin-403")
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.state_version == snapshot.state_version
        assert current.approval_id is None
        assert _service(engine).get_for_exception("exc-pin-403") == []

    def test_missing_auth_denied_401_no_mutation(self) -> None:
        """A valid body with no actor context is denied without mutation."""
        # Arrange: awaiting aggregate plus an anonymous router app.
        engine = _engine()
        repo = ExceptionRepository(engine)  # type: ignore[arg-type]
        snapshot, proposal = _awaiting(repo, "exc-pin-401")
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(_build_app(engine, lookup, tenant_id=None))
        # Act: decide with no actor attached to the request.
        response = client.post(
            "/approvals/decide", json=_body(snapshot, proposal, key="key-pin-401")
        )
        # Assert: 401 missing-actor denial, aggregate untouched, no record.
        assert response.status_code == 401
        current = repo.get("exc-pin-401")
        assert current is not None
        assert current.state is ExceptionState.AWAITING_APPROVAL
        assert current.state_version == snapshot.state_version
        assert current.approval_id is None
        assert _service(engine).get_for_exception("exc-pin-401") == []
