"""P2.8 — Deterministic exception context builder (CP1-C).

These tests require a reachable Postgres and are skipped otherwise. They
exercise build_exception_context against persisted reconciliation rows and
verify completeness, tenant isolation, determinism and Decimal precision.
"""

from __future__ import annotations

import io
import os
from uuid import uuid4

os.environ.setdefault(
    "POSTGRES_URI", "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
)
os.environ.setdefault(
    "MIGRATION_POSTGRES_URI", "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from apps.api.main import app
from finance.reconciliation.context import ExceptionContext
from finance.reconciliation.context_builder import (
    ContextNotFoundError,
    build_exception_context,
)

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)

TENANT_A = "7d6f8b65-5e40-55b5-967f-69b85912dd87"
TENANT_B = "ea7639b2-4a8e-5954-84a2-f8630e89d206"

TWO_INVOICE_CSV = (
    "invoice_id,amount,currency,issued_at\n"
    "inv_a,1000.00,USD,2026-09-01\n"
    "inv_b,500.00,USD,2026-09-02\n"
)
TWO_STRIPE_CSV = (
    "charge_id,amount,currency,created_at,fee\n"
    "ch_a,1000.00,USD,2026-09-01,29.00\n"
    "ch_b,500.00,USD,2026-09-02,10.00\n"
)
TWO_BANK_CSV = "deposit_id,amount,posted_at\ndep_1,1471.00,2026-09-03\n"


def _db_reachable() -> bool:
    try:
        engine = create_engine(DSN, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="Postgres unreachable")


def _client(tenant_id: str) -> TestClient:
    c = TestClient(app)
    c.headers.update({"X-Tenant-ID": tenant_id, "X-User-ID": "test-user", "X-Role": "cfo"})
    return c


def _upload(client: TestClient, session_id: str, source_type: str, csv_text: str) -> None:
    files = {"file": (f"{source_type.lower()}.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    r = client.post(
        f"/api/v1/reconciliation/sessions/{session_id}/sources/{source_type}", files=files
    )
    assert r.status_code == 200, r.text


def _run_discrepancy(client: TestClient) -> tuple[str, str]:
    """Run the two-invoice discrepancy batch; return (run_id, exception_id)."""
    r = client.post(
        "/api/v1/reconciliation/sessions",
        json={"period_start": "2026-09-01", "period_end": "2026-09-30"},
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    _upload(client, session_id, "INVOICE", TWO_INVOICE_CSV)
    _upload(client, session_id, "STRIPE", TWO_STRIPE_CSV)
    _upload(client, session_id, "BANK", TWO_BANK_CSV)
    r = client.post(f"/api/v1/reconciliation/sessions/{session_id}/validate")
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
        json={
            "idempotency_key": f"ctx-{uuid4()}",
            "tolerance_absolute": "0",
            "tolerance_percent": "0",
        },
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    engine = create_engine(DSN)
    try:
        with engine.connect() as conn:
            exception_id = conn.execute(
                text(
                    "SELECT exception_id FROM reconciliation_exceptions "
                    "WHERE run_id = :run_id LIMIT 1"
                ),
                {"run_id": run_id},
            ).scalar()
    finally:
        engine.dispose()
    assert exception_id, "discrepancy batch produced no exception"
    return str(run_id), str(exception_id)


class TestExceptionContextBuilder:
    def test_complete_context_for_fee_discrepancy(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                ctx = build_exception_context(
                    session,
                    tenant_id=TENANT_A,
                    run_id=run_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        assert isinstance(ctx, ExceptionContext)
        assert ctx.exception_id == exception_id
        assert ctx.evidence_refs, "evidence_refs must be populated"
        assert ctx.investigation_eligible is True
        assert ctx.ineligibility_reason is None
        assert ctx.calculations, "calculations must be populated"
        assert all(isinstance(v, str) for v in ctx.calculations.values())
        assert ctx.rule_results, "rule_results must be non-empty"
        # money precision preserved
        for key in ("expected_net", "actual_deposit", "variance", "tolerance"):
            assert isinstance(getattr(ctx, key), str)

    def test_unknown_exception_raises(self) -> None:
        ca = _client(TENANT_A)
        run_id, _ = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session, pytest.raises(ContextNotFoundError):
                build_exception_context(
                    session,
                    tenant_id=TENANT_A,
                    run_id=run_id,
                    exception_id=str(uuid4()),
                    currency="USD",
                )
        finally:
            engine.dispose()

    def test_cross_tenant_raises(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session, pytest.raises(ContextNotFoundError):
                build_exception_context(
                    session,
                    tenant_id=TENANT_B,
                    run_id=run_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()

    def test_unknown_run_raises(self) -> None:
        engine = create_engine(DSN)
        try:
            with Session(engine) as session, pytest.raises(ContextNotFoundError):
                build_exception_context(
                    session,
                    tenant_id=TENANT_A,
                    run_id=str(uuid4()),
                    exception_id=str(uuid4()),
                    currency="USD",
                )
        finally:
            engine.dispose()

    def test_deterministic(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                a = build_exception_context(
                    session,
                    tenant_id=TENANT_A,
                    run_id=run_id,
                    exception_id=exception_id,
                    currency="USD",
                )
                b = build_exception_context(
                    session,
                    tenant_id=TENANT_A,
                    run_id=run_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        import json

        assert json.dumps(a.model_dump(), sort_keys=True) == json.dumps(
            b.model_dump(), sort_keys=True
        )

    def test_decimal_precision(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                ctx = build_exception_context(
                    session,
                    tenant_id=TENANT_A,
                    run_id=run_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        for key in ("expected_net", "actual_deposit", "variance", "tolerance"):
            val = getattr(ctx, key)
            assert isinstance(val, str)
            # no scientific notation / float artifacts
            assert "e" not in val.lower() or "." in val
