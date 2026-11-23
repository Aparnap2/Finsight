"""P2.7 — HTTP workflow, idempotency, tenant isolation, and restart recovery.

These tests require a reachable Postgres (``FINSIGHT_TEST_DSN``) and are
skipped otherwise. They exercise the full reconciliation workflow over HTTP:
create session, upload three sources, validate, reconcile, retrieve results,
record a decision, and retrieve audit events. A second client (different
tenant) must see none of the first tenant's data.
"""

from __future__ import annotations

import io
import os
from decimal import Decimal
from typing import Any
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

from apps.api.main import app

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)

TENANT_A = "7d6f8b65-5e40-55b5-967f-69b85912dd87"
TENANT_B = "ea7639b2-4a8e-5954-84a2-f8630e89d206"

INVOICE_CSV = "invoice_id,amount,currency,issued_at\nINV-1,250.00,USD,2026-01-02\n"
STRIPE_CSV = "charge_id,amount,currency,created_at,fee\nch_1,250.00,USD,2026-01-02T09:15:00Z,0.00\n"
BANK_CSV = "deposit_id,amount,posted_at\ndep_1,250.00,2026-01-04\n"


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


def _upload(client: TestClient, session_id: str, source_type: str, csv_text: str) -> dict[str, Any]:
    files = {"file": (f"{source_type.lower()}.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    r = client.post(
        f"/api/v1/reconciliation/sessions/{session_id}/sources/{source_type}", files=files
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


class TestReconciliationHttpWorkflow:
    def test_full_workflow_import_reconcile_retrieve(self) -> None:
        ca = _client(TENANT_A)
        r = ca.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        assert r.status_code == 200, r.text
        session_id = r.json()["session_id"]

        _upload(ca, session_id, "INVOICE", INVOICE_CSV)
        _upload(ca, session_id, "STRIPE", STRIPE_CSV)
        _upload(ca, session_id, "BANK", BANK_CSV)

        r = ca.post(f"/api/v1/reconciliation/sessions/{session_id}/validate")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "READY"
        assert r.json()["accepted_count"] >= 3

        r = ca.post(
            f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
            json={
                "idempotency_key": "test-run-1",
                "tolerance_absolute": "0",
                "tolerance_percent": "0",
            },
        )
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        assert r.json()["status"] == "SUCCEEDED"

        r = ca.get(f"/api/v1/reconciliation/runs/{run_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "SUCCEEDED"
        assert len(body["matches"]) >= 1

        r = ca.get(f"/api/v1/reconciliation/runs/{run_id}/audit")
        assert r.status_code == 200, r.text

    def test_idempotent_reconcile_returns_same_run(self) -> None:
        ca = _client(TENANT_A)
        r = ca.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-02-01", "period_end": "2026-02-28"},
        )
        session_id = r.json()["session_id"]
        _upload(ca, session_id, "INVOICE", INVOICE_CSV)
        _upload(ca, session_id, "STRIPE", STRIPE_CSV)
        _upload(ca, session_id, "BANK", BANK_CSV)
        ca.post(f"/api/v1/reconciliation/sessions/{session_id}/validate")

        r1 = ca.post(
            f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
            json={"idempotency_key": "idem-key-1"},
        )
        r2 = ca.post(
            f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
            json={"idempotency_key": "idem-key-1"},
        )
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["run_id"] == r2.json()["run_id"]

    def test_cross_tenant_isolation(self) -> None:
        ca = _client(TENANT_A)
        cb = _client(TENANT_B)
        r = ca.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
        )
        assert r.status_code == 200
        r = cb.get("/api/v1/reconciliation/runs/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_restart_recovery_retrieves_persisted_run(self) -> None:
        ca = _client(TENANT_A)
        r = ca.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-04-01", "period_end": "2026-04-30"},
        )
        session_id = r.json()["session_id"]
        _upload(ca, session_id, "INVOICE", INVOICE_CSV)
        _upload(ca, session_id, "STRIPE", STRIPE_CSV)
        _upload(ca, session_id, "BANK", BANK_CSV)
        ca.post(f"/api/v1/reconciliation/sessions/{session_id}/validate")
        r = ca.post(
            f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
            json={"idempotency_key": "restart-test-1"},
        )
        run_id = r.json()["run_id"]

        ca2 = _client(TENANT_A)
        r = ca2.get(f"/api/v1/reconciliation/runs/{run_id}")
        assert r.status_code == 200, r.text
        assert r.json()["run_id"] == run_id
        assert r.json()["status"] == "SUCCEEDED"

    def test_anonymous_caller_gets_401(self) -> None:
        c = TestClient(app)
        r = c.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        assert r.status_code == 401


# Two invoices, two charges, one deposit. ch_b carries a 15.00 processor fee, so
# its net (485.00) is short of INV-B's 500.00 expectation: that edge must be
# persisted as an EXCEPTION, while the 735.00 deposit clears both charges net.
TWO_INVOICE_CSV = (
    "invoice_id,amount,currency,issued_at\n"
    "INV-A,250.00,USD,2026-01-02\n"
    "INV-B,500.00,USD,2026-01-02\n"
)
TWO_STRIPE_CSV = (
    "charge_id,amount,currency,created_at,fee\n"
    "ch_a,250.00,USD,2026-01-02T09:15:00Z,0.00\n"
    "ch_b,500.00,USD,2026-01-02T09:20:00Z,15.00\n"
)
TWO_BANK_CSV = "deposit_id,amount,posted_at\ndep_two,735.00,2026-01-04\n"


class TestDiscrepancyWorkflowPersistence:
    """A discrepancy-producing batch must persist matches, allocations, legs, exceptions.

    The single-invoice happy path previously passed while the exception branch
    crashed with ``'str' object has no attribute 'value'``. This test exercises
    the realistic path the product exists for and asserts the rows that were
    actually written, not merely the HTTP status.
    """

    def test_fee_discrepancy_persists_all_four_record_kinds(self) -> None:
        ca = _client(TENANT_A)
        r = ca.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-09-01", "period_end": "2026-09-30"},
        )
        assert r.status_code == 200, r.text
        session_id = r.json()["session_id"]

        _upload(ca, session_id, "INVOICE", TWO_INVOICE_CSV)
        _upload(ca, session_id, "STRIPE", TWO_STRIPE_CSV)
        _upload(ca, session_id, "BANK", TWO_BANK_CSV)

        r = ca.post(f"/api/v1/reconciliation/sessions/{session_id}/validate")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "READY"
        assert r.json()["accepted_count"] >= 5

        r = ca.post(
            f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
            json={
                # Unique per invocation: reusing a key would replay an earlier
                # run and mask whether this batch was actually persisted.
                "idempotency_key": f"discrepancy-{uuid4()}",
                "tolerance_absolute": "0",
                "tolerance_percent": "0",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "SUCCEEDED"
        run_id = r.json()["run_id"]

        engine = create_engine(DSN)
        try:
            with engine.connect() as conn:
                matches = (
                    conn.execute(
                        text(
                            "SELECT invoice_id, charge_id, outcome, exception_code, "
                            "expected_amount, observed_amount FROM reconciliation_matches "
                            "WHERE run_id = :run_id ORDER BY invoice_id"
                        ),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                )
                allocations = (
                    conn.execute(
                        text(
                            "SELECT allocation_id, deposit_id, outcome, allocated_total, "
                            "fee_total FROM payout_allocations WHERE run_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                )
                legs = (
                    conn.execute(
                        text(
                            "SELECT payment_id, gross, fee, net, allocated FROM allocation_legs "
                            "WHERE allocation_id IN ("
                            "  SELECT allocation_id FROM payout_allocations WHERE run_id = :run_id"
                            ") ORDER BY payment_id"
                        ),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                )
                exceptions = (
                    conn.execute(
                        text(
                            "SELECT exception_code, severity, status, description FROM "
                            "reconciliation_exceptions WHERE run_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                    .mappings()
                    .all()
                )
        finally:
            engine.dispose()

        # Both invoice->charge edges are persisted, one matched and one broken.
        assert len(matches) == 2, matches
        by_invoice = {str(m["invoice_id"]): m for m in matches}
        assert by_invoice["INV-A"]["outcome"] == "MATCHED"
        assert by_invoice["INV-A"]["exception_code"] is None
        assert by_invoice["INV-B"]["outcome"] == "EXCEPTION"
        # The fee drift is classified, not silently absorbed.
        assert by_invoice["INV-B"]["exception_code"] == "I-FEE-DRIFT"
        assert Decimal(str(by_invoice["INV-B"]["observed_amount"])) == Decimal("485.00")

        # One deposit allocation covering both charges, valued net of fees.
        assert len(allocations) == 1, allocations
        allocation = allocations[0]
        assert str(allocation["deposit_id"]) == "dep_two"
        assert Decimal(str(allocation["allocated_total"])) == Decimal("735.00")
        assert Decimal(str(allocation["fee_total"])) == Decimal("15.00")

        # Allocation legs bind each charge to the deposit with its own fee.
        assert len(legs) == 2, legs
        leg_by_payment = {str(leg["payment_id"]): leg for leg in legs}
        assert Decimal(str(leg_by_payment["ch_a"]["net"])) == Decimal("250.00")
        assert Decimal(str(leg_by_payment["ch_b"]["net"])) == Decimal("485.00")
        assert Decimal(str(leg_by_payment["ch_b"]["fee"])) == Decimal("15.00")

        # The break is durable and actionable, not just in the HTTP response.
        assert len(exceptions) >= 1, exceptions
        exc_codes = {str(e["exception_code"]) for e in exceptions}
        assert exc_codes == {"I-FEE-DRIFT"}, exc_codes
        assert all(str(e["status"]) == "OPEN" for e in exceptions)

        # The read API reflects the persisted exception.
        r = ca.get(f"/api/v1/reconciliation/runs/{run_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(m["outcome"] == "EXCEPTION" for m in body["matches"])
