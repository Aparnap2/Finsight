"""Integrated financial E2E: SQS transport + POST execute_controlled (Slice 4).

RED until GREEN (``apps.workers.sqs_execute`` does not exist).

Asserts PostgreSQL rows, idempotency records, audit entries, and
verification outcomes — never just HTTP statuses or queue depths.
Requires real PostgreSQL AND the SQS emulator; skipped otherwise.

Transport rule under test: the worker forwards the original
idempotency keys and hashes unchanged and invents no business state.
"""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from apps.api import execution_routes as ex
from apps.api.execution_routes import (
    get_db_session,
    get_executor_factory,
    get_proposal_lookup,
    get_verify_bundle,
    router,
)
from apps.workers.sqs_execute import poll_once
from finance.accounting.mock import MockQuickBooksAdapter
from finance.exceptions.repository import ExceptionRepository
from finance.execution.executor import Executor
from tests.unit.execution.test_executor import _awaiting

SQS_ENDPOINT = "http://localhost:4566"
PG_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"

TENANT_A = "tenant-e2e-a"
TENANT_B = "tenant-e2e-b"
_SIT = "FS-E2E-001"


def _stack_available() -> bool:
    """Return True when PostgreSQL and the SQS emulator both answer."""
    try:
        socket.create_connection(("localhost", 4566), timeout=2).close()
        engine = create_engine(PG_DSN)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001 - any failure skips
        return False


needs_stack = pytest.mark.skipif(not _stack_available(), reason="needs PostgreSQL + SQS emulator")


def _sqs() -> Any:
    """Boto3 SQS client bound to the emulator (lazy: ministack group only)."""
    boto3 = pytest.importorskip("boto3", reason="ministack group not installed")
    return boto3.client(
        "sqs",
        endpoint_url=SQS_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


class _Stack:
    """Seeded PG + app + queues for one E2E scenario."""

    def __init__(self, sqs: Any, tenant: str = TENANT_A) -> None:
        from finance.exceptions.models import Base as ExceptionsBase

        self.run_id = uuid4().hex[:8]
        self.engine = create_engine(PG_DSN)
        ExceptionsBase.metadata.create_all(self.engine)
        self.repo = ExceptionRepository(self.engine)
        self.exc_id = f"exc-e2e-{tenant}-{self.run_id}"
        self.approved, self.proposal = _awaiting(self.repo, self.exc_id, tenant_id=tenant)
        # Second tenant seeded for the cross-tenant pointer scenario.
        self.exc_id_b = f"exc-e2e-{TENANT_B}-{self.run_id}"
        _awaiting(self.repo, self.exc_id_b, tenant_id=TENANT_B)
        self.adapter = MockQuickBooksAdapter()
        self.executor = Executor(self.adapter, self.engine)
        self.lookup = {self.proposal.proposal_id: self.proposal}
        self.client = TestClient(self._build_app(tenant))
        self.work_url = sqs.create_queue(
            QueueName=f"finsight-e2e-work-{self.run_id}",
            Attributes={
                "VisibilityTimeout": "2",
                "RedrivePolicy": (
                    '{"deadLetterTargetArn":'
                    f'"arn:aws:sqs:us-east-1:000000000000:finsight-e2e-work-dlq-{self.run_id}",'
                    '"maxReceiveCount":"2"}'
                ),
            },
        )["QueueUrl"]
        sqs.create_queue(QueueName=f"finsight-e2e-work-dlq-{self.run_id}")
        self.dlq_url = (
            "http://sqs.us-east-1.localhost.localstack.cloud:4566"
            f"/000000000000/finsight-e2e-work-dlq-{self.run_id}"
        )
        self.quarantine_url = sqs.create_queue(QueueName=f"finsight-e2e-quarantine-{self.run_id}")[
            "QueueUrl"
        ]
        self.queue_names = (
            f"finsight-e2e-work-{self.run_id}",
            f"finsight-e2e-work-dlq-{self.run_id}",
            f"finsight-e2e-quarantine-{self.run_id}",
        )

    def _build_app(self, tenant: str) -> FastAPI:
        """Execution router with fixed actor, seeded lookup, spy executor."""
        app = FastAPI()
        app.include_router(router)

        @app.middleware("http")
        async def _actor(request: Request, call_next: Any) -> Any:
            request.state.actor = {"tenant_id": tenant, "user_id": "tester"}
            return await call_next(request)

        def _session_override() -> Iterator[Session]:
            with Session(self.engine) as session:
                yield session

        bundle = ex._default_readers()
        app.dependency_overrides[get_db_session] = _session_override
        app.dependency_overrides[get_proposal_lookup] = lambda: self.lookup
        app.dependency_overrides[get_executor_factory] = lambda: lambda _eng: self.executor
        app.dependency_overrides[get_verify_bundle] = lambda: bundle
        return app

    def post(self, body: dict[str, Any], tenant: str) -> tuple[int, dict[str, Any]]:
        """POST the execution route as the worker would (actor = claim)."""
        response = self.client.post(
            "/execute",
            json=body,
            headers={"X-Tenant-ID": tenant, "X-User-ID": "sqs-worker"},
        )
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    def message(self, tenant: str, key: str, **over: Any) -> dict[str, Any]:
        """ExecuteRequest-shaped SQS body (coordinates only, no money)."""
        run_key = f"{key}-{self.run_id}"
        body = {
            "tenant_id": tenant,
            "exception_id": self.exc_id,
            "proposal_id": self.proposal.proposal_id,
            "proposal_version": self.proposal.version,
            "proposal_content_hash": self.proposal.content_hash,
            "approver_id": "approver-1",
            "decision": "APPROVED",
            "idempotency_key": f"{run_key}-approval",
            "execution_idempotency_key": run_key,
            "expected_state_version": self.approved.state_version,
            "situation_id": _SIT,
            "company_id": "meridian",
        }
        body.update(over)
        return body

    def enqueue(self, sqs: Any, body: dict[str, Any]) -> None:
        """Put one work message on the queue."""
        sqs.send_message(QueueUrl=self.work_url, MessageBody=json.dumps(body))

    def financial_actions(self) -> int:
        """Count authoritative accounting mutations on the adapter."""
        return sum(
            1 for c in getattr(self.adapter, "calls", []) if c.op == "create_correcting_entry"
        )


@pytest.fixture()
def stack() -> Iterator[_Stack]:
    """Fresh seeded stack per test; queues cleaned afterwards."""
    sqs = _sqs()
    pending = _Stack(sqs)
    yield pending
    pending.engine.dispose()
    for name in pending.queue_names:
        try:
            url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
            sqs.delete_queue(QueueUrl=url)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


def _make_post(stack: _Stack) -> Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]]:
    """Adapt the harness to the worker's post callable."""
    return lambda body, tenant: stack.post(body, tenant)


@needs_stack
class TestSqsExecuteE2E:
    def test_happy_path_closes_verified(self, stack: _Stack) -> None:
        sqs = _sqs()
        stack.enqueue(sqs, stack.message(TENANT_A, "e2e-key-1"))
        result = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        assert result.kind == "DELETED"
        assert result.verified is True
        assert stack.financial_actions() == 1

    def test_duplicate_delivery_single_action(self, stack: _Stack) -> None:
        sqs = _sqs()
        body = stack.message(TENANT_A, "e2e-key-2")
        stack.enqueue(sqs, body)
        stack.enqueue(sqs, body)
        first = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        second = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        assert first.execution_id == second.execution_id
        assert second.deduplicated is True
        assert stack.financial_actions() == 1

    def test_crash_after_commit_recovers_same_execution(self, stack: _Stack) -> None:
        from apps.workers.sqs_execute import process_message

        sqs = _sqs()
        stack.enqueue(sqs, stack.message(TENANT_A, "e2e-key-3"))
        received = sqs.receive_message(QueueUrl=stack.work_url)["Messages"][0]
        first = process_message(_make_post(stack), json.loads(received["Body"]))
        assert first.action == "delete"  # worker would delete here; it crashes instead
        time.sleep(3)  # visibility expiry redelivers the unacknowledged message
        second = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        assert second.execution_id == first.execution_id
        assert stack.financial_actions() == 1

    def test_cross_tenant_pointer_quarantined_without_mutation(self, stack: _Stack) -> None:
        sqs = _sqs()
        forged = stack.message(TENANT_A, "e2e-key-4")
        forged["exception_id"] = stack.exc_id_b  # B's exception, A's claim
        stack.enqueue(sqs, forged)
        result = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        assert result.kind == "QUARANTINED"
        assert result.code == "CROSS_TENANT"
        assert stack.financial_actions() == 0

    def test_malformed_message_quarantined(self, stack: _Stack) -> None:
        sqs = _sqs()
        sqs.send_message(QueueUrl=stack.work_url, MessageBody='{"nope": true}')
        result = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        assert result.kind == "QUARANTINED"
        assert result.code == "MALFORMED"

    def test_audit_trail_persisted(self, stack: _Stack) -> None:
        sqs = _sqs()
        stack.enqueue(sqs, stack.message(TENANT_A, "e2e-key-6"))
        result = poll_once(sqs, stack.work_url, stack.quarantine_url, _make_post(stack))
        assert result.kind == "DELETED"
        with Session(stack.engine) as session:
            states = [
                r[0]
                for r in session.execute(
                    text(
                        "SELECT attempted_state FROM exception_audits "
                        "WHERE exception_id = :exc ORDER BY id"
                    ),
                    {"exc": stack.exc_id},
                ).all()
            ]
        assert "CLOSED" in states
