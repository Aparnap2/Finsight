"""P10-04 RED: error + observation-read surfaces must not echo secrets/PII.

- Unknown-field 422 bodies must not echo the submitted secret value.
- Domain `str(exc)` error bodies must not echo PII-bearing reasons.
- Observation audit/timeline reads must not serve raw PII from legacy
  rows (defense in depth alongside write-time sanitization).

No live server: TestClient + shared in-memory SQLite (+ tmp file DB
where noted). No network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

SECRET = "sk-test-synthetic-secret-value"
EMAIL = "rahul@example.com"


def _body() -> dict[str, object]:
    """Validation-passing decision coordinates (no seeding needed)."""
    return {
        "exception_id": "exc-echo-1",
        "proposal_id": "prop-echo-1",
        "proposal_version": 1,
        "proposal_content_hash": "a" * 16,
        "approver_id": "approver-1",
        "decision": "APPROVED",
        "idempotency_key": "key-echo-1",
        "expected_state_version": 1,
    }


def _build_app(engine: Any, tenant_id: str | None) -> FastAPI:
    """Mount approvals + observations routers with a fixed actor."""
    from collections.abc import Iterator

    from apps.api.approvals import get_db_session
    from apps.api.approvals import router as approvals_router
    from apps.api.observations import get_observation_session
    from apps.api.observations import router as observations_router

    app = FastAPI()
    app.include_router(approvals_router)
    app.include_router(observations_router)

    async def _actor(request: Request, call_next: Any) -> Any:
        if tenant_id is not None:
            request.state.actor = {"tenant_id": tenant_id, "user_id": "tester"}
        return await call_next(request)

    app.middleware("http")(_actor)

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_observation_session] = _session_override
    return app


class TestValidationEcho:
    def test_unknown_secret_field_not_echoed_in_422(self) -> None:
        from tests.unit.execution.test_executor import _engine

        client = TestClient(_build_app(_engine(), "tenant-acme"))
        body = _body()
        body["api_key"] = SECRET
        response = client.post("/approvals/decide", json=body)
        assert response.status_code == 422
        assert SECRET not in response.text


class TestDomainErrorEcho:
    def test_pii_reason_not_echoed_in_422(self, monkeypatch: Any) -> None:
        from finance.approvals.service import ApprovalService
        from finance.exceptions.errors import IllegalTransitionError
        from tests.unit.execution.test_executor import _engine

        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise IllegalTransitionError(
                "exc-echo-1", "APPROVED", "EXECUTING", reason=f"contact {EMAIL}"
            )

        monkeypatch.setattr(ApprovalService, "decide", _raise)
        client = TestClient(_build_app(_engine(), "tenant-acme"))
        response = client.post("/approvals/decide", json=_body())
        assert response.status_code == 422
        assert EMAIL not in response.text


class TestObservationReadLegacy:
    def test_raw_legacy_audit_row_not_served(self) -> None:

        from finance.exceptions.models import ExceptionAuditRow
        from tests.unit.execution.test_executor import _engine

        engine = _engine()
        with Session(engine) as session:
            session.add(
                ExceptionAuditRow(
                    exception_id="exc-echo-1",
                    tenant_id="tenant-acme",
                    from_state=None,
                    attempted_state="PROPOSED",
                    outcome="APPLIED",
                    reason=f"per {EMAIL}, key {SECRET}",
                    actor="tester",
                    expected_version=1,
                    actual_version=1,
                    created_at=datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC),
                )
            )
            session.commit()
        client = TestClient(_build_app(engine, "tenant-acme"))
        from finance.execution.executor import execution_id_for
        from finance.execution.models import ExecutionRow

        with Session(engine) as session:
            session.add(
                ExecutionRow(
                    tenant_id="tenant-acme",
                    idempotency_key="key-echo-1",
                    execution_id=execution_id_for("tenant-acme", "key-echo-1"),
                    exception_id="exc-echo-1",
                    proposal_id="prop-echo-1",
                    payload_hash="h",
                    result="SUCCEEDED",
                    external_reference="ext-1",
                    post_verify="MATCHED",
                )
            )
            session.commit()
        execution_id = execution_id_for("tenant-acme", "key-echo-1")
        for path in (
            f"/api/v1/observations/executions/{execution_id}/audit",
            f"/api/v1/observations/executions/{execution_id}/timeline",
        ):
            body = client.get(path)
            assert body.status_code == 200
            assert EMAIL not in body.text
            assert SECRET not in body.text
