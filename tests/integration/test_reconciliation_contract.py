"""Contract endpoints for the reconciliation workflow (docs/specs/API_CONTRACT.md).

Covers the eight endpoints that were absent from the implementation:

* ``GET  /api/v1/import-sessions/{session_id}``
* ``GET  /api/v1/runs/{run_id}/matches``
* ``GET  /api/v1/runs/{run_id}/allocations``
* ``GET  /api/v1/runs/{run_id}/exceptions``
* ``GET  /api/v1/exceptions/{exception_id}``
* ``POST /api/v1/exceptions/{exception_id}/decisions``
* ``POST /api/v1/runs/{run_id}/exports``
* ``GET  /api/v1/exports/{export_id}``

Each case asserts persisted state and contract shape, not merely a status code.
Requires Postgres (``FINSIGHT_TEST_DSN``); skipped otherwise.
"""

from __future__ import annotations

import io
import os
from decimal import Decimal
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


def _discrepancy_run(client: TestClient) -> str:
    """Create a run whose fee drift raises exactly one I-FEE-DRIFT exception."""
    tag = uuid4().hex[:8]
    r = client.post(
        "/api/v1/reconciliation/sessions",
        json={"period_start": "2026-06-01", "period_end": "2026-06-30"},
    )
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    _upload(
        client,
        session_id,
        "INVOICE",
        "invoice_id,amount,currency,issued_at\n"
        f"INV-{tag}-A,250.00,USD,2026-01-02\n"
        f"INV-{tag}-B,500.00,USD,2026-01-02\n",
    )
    _upload(
        client,
        session_id,
        "STRIPE",
        "charge_id,amount,currency,created_at,fee\n"
        f"ch_{tag}_a,250.00,USD,2026-01-02T09:15:00Z,0.00\n"
        f"ch_{tag}_b,500.00,USD,2026-01-02T09:20:00Z,15.00\n",
    )
    _upload(
        client,
        session_id,
        "BANK",
        f"deposit_id,amount,posted_at\ndep_{tag},735.00,2026-01-04\n",
    )
    assert client.post(f"/api/v1/reconciliation/sessions/{session_id}/validate").status_code == 200
    r = client.post(
        f"/api/v1/reconciliation/sessions/{session_id}/reconcile",
        json={"idempotency_key": f"contract-{uuid4()}"},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["run_id"])


def _only_exception_id(client: TestClient, run_id: str) -> str:
    r = client.get(f"/api/v1/runs/{run_id}/exceptions")
    assert r.status_code == 200, r.text
    exceptions = r.json()["exceptions"]
    assert len(exceptions) == 1, exceptions
    return str(exceptions[0]["exception_id"])


class TestSessionDetail:
    def test_detail_reports_files_and_validation_counts(self) -> None:
        ca = _client(TENANT_A)
        tag = uuid4().hex[:8]
        r = ca.post(
            "/api/v1/reconciliation/sessions",
            json={"period_start": "2026-07-01", "period_end": "2026-07-31"},
        )
        session_id = r.json()["session_id"]
        _upload(
            ca,
            session_id,
            "INVOICE",
            f"invoice_id,amount,currency,issued_at\nINV-{tag},100.00,USD,2026-01-02\n",
        )

        r = ca.get(f"/api/v1/import-sessions/{session_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == session_id
        assert body["status"] == "CREATED"
        assert len(body["files"]) == 1
        f = body["files"][0]
        assert f["source_type"] == "INVOICE"
        assert f["valid_rows"] == 1
        assert f["invalid_rows"] == 0

    def test_unknown_session_is_404(self) -> None:
        r = _client(TENANT_A).get(f"/api/v1/import-sessions/{uuid4()}")
        assert r.status_code == 404


class TestRunResultEndpoints:
    def test_matches_return_contract_fields(self) -> None:
        ca = _client(TENANT_A)
        run_id = _discrepancy_run(ca)

        r = ca.get(f"/api/v1/runs/{run_id}/matches")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] == run_id
        assert body["total_count"] == 2
        assert body["has_more"] is False
        outcomes = sorted(m["outcome"] for m in body["matches"])
        assert outcomes == ["EXCEPTION", "MATCHED"]
        broken = next(m for m in body["matches"] if m["outcome"] == "EXCEPTION")
        assert broken["exception_code"] == "I-FEE-DRIFT"
        for key in (
            "match_id",
            "invoice_id",
            "charge_id",
            "expected_amount",
            "observed_amount",
            "difference",
            "variance",
            "tolerance_applied",
            "currency",
            "materiality",
            "fingerprint",
        ):
            assert key in broken, key

    def test_allocations_include_legs_and_money(self) -> None:
        ca = _client(TENANT_A)
        run_id = _discrepancy_run(ca)

        r = ca.get(f"/api/v1/runs/{run_id}/allocations")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_count"] == 1
        allocation = body["allocations"][0]
        assert Decimal(allocation["allocated_total"]) == Decimal("735.00")
        assert Decimal(allocation["eligible_net_total"]) == Decimal("735.00")
        assert Decimal(allocation["fee_total"]) == Decimal("15.00")
        assert allocation["outcome"] == "MATCHED"
        assert len(allocation["legs"]) == 2
        nets = sorted(Decimal(leg["net"]) for leg in allocation["legs"])
        assert nets == [Decimal("250.00"), Decimal("485.00")]

    def test_exceptions_endpoint_matches_detail(self) -> None:
        ca = _client(TENANT_A)
        run_id = _discrepancy_run(ca)

        r = ca.get(f"/api/v1/runs/{run_id}/exceptions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_count"] == 1
        exception = body["exceptions"][0]
        assert exception["exception_code"] == "I-FEE-DRIFT"
        assert exception["status"] == "OPEN"
        assert exception["evidence_refs"]

        detail = ca.get(f"/api/v1/exceptions/{exception['exception_id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["exception_id"] == exception["exception_id"]

    @pytest.mark.parametrize("suffix", ["matches", "allocations", "exceptions"])
    def test_cross_tenant_run_is_404(self, suffix: str) -> None:
        run_id = _discrepancy_run(_client(TENANT_A))
        r = _client(TENANT_B).get(f"/api/v1/runs/{run_id}/{suffix}")
        assert r.status_code == 404

    def test_unknown_run_is_404(self) -> None:
        r = _client(TENANT_A).get(f"/api/v1/runs/{uuid4()}/matches")
        assert r.status_code == 404


class TestDecisions:
    def test_assign_then_approve_resolves_exception(self) -> None:
        ca = _client(TENANT_A)
        exception_id = _only_exception_id(ca, _discrepancy_run(ca))

        assign = ca.post(
            f"/api/v1/exceptions/{exception_id}/decisions",
            json={"decision_type": "ASSIGN", "reason": "route to reviewer"},
        )
        assert assign.status_code == 201, assign.text
        assert assign.json()["previous_status"] == "OPEN"
        assert assign.json()["new_status"] == "UNDER_REVIEW"

        approve = ca.post(
            f"/api/v1/exceptions/{exception_id}/decisions",
            json={
                "decision_type": "APPROVE",
                "reason": "fee drift confirmed with processor statement",
                "evidence_refs": ["ch_b"],
            },
        )
        assert approve.status_code == 201, approve.text
        assert approve.json()["new_status"] == "RESOLVED"

        detail = ca.get(f"/api/v1/exceptions/{exception_id}").json()
        assert detail["status"] == "RESOLVED"
        assert [d["decision_type"] for d in detail["decisions"]] == ["ASSIGN", "APPROVE"]

        # The state machine rejects a no-op repeat; the endpoint reports 409.
        repeat = ca.post(
            f"/api/v1/exceptions/{exception_id}/decisions",
            json={"decision_type": "APPROVE", "reason": "again"},
        )
        assert repeat.status_code == 409, repeat.text

    def test_approve_from_open_is_a_400(self) -> None:
        ca = _client(TENANT_A)
        exception_id = _only_exception_id(ca, _discrepancy_run(ca))
        r = ca.post(
            f"/api/v1/exceptions/{exception_id}/decisions",
            json={"decision_type": "APPROVE", "reason": "skip review"},
        )
        assert r.status_code == 400, r.text
        assert ca.get(f"/api/v1/exceptions/{exception_id}").json()["status"] == "OPEN"

    def test_cross_tenant_decision_is_404(self) -> None:
        exception_id = _only_exception_id(_client(TENANT_A), _discrepancy_run(_client(TENANT_A)))
        r = _client(TENANT_B).post(
            f"/api/v1/exceptions/{exception_id}/decisions",
            json={"decision_type": "ASSIGN", "reason": "not yours"},
        )
        assert r.status_code == 404


class TestExports:
    def test_create_and_retrieve_export(self) -> None:
        ca = _client(TENANT_A)
        run_id = _discrepancy_run(ca)

        r = ca.post(f"/api/v1/runs/{run_id}/exports", json={"format": "CSV"})
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["run_id"] == run_id
        assert created["status"] == "PENDING"
        assert created["format"] == "CSV"

        got = ca.get(f"/api/v1/exports/{created['export_id']}")
        assert got.status_code == 200, got.text
        assert got.json()["export_id"] == created["export_id"]
        assert got.json()["status"] == "PENDING"

    def test_unknown_format_is_400(self) -> None:
        ca = _client(TENANT_A)
        run_id = _discrepancy_run(ca)
        r = ca.post(f"/api/v1/runs/{run_id}/exports", json={"format": "XLSX"})
        assert r.status_code == 400

    def test_cross_tenant_export_is_404(self) -> None:
        ca = _client(TENANT_A)
        run_id = _discrepancy_run(ca)
        export_id = ca.post(f"/api/v1/runs/{run_id}/exports", json={"format": "JSON"}).json()[
            "export_id"
        ]
        assert _client(TENANT_B).get(f"/api/v1/exports/{export_id}").status_code == 404


class TestRunScopedAudit:
    def test_audit_excludes_events_from_other_runs(self) -> None:
        ca = _client(TENANT_A)
        run_one = _discrepancy_run(ca)
        exception_one = _only_exception_id(ca, run_one)
        assert (
            ca.post(
                f"/api/v1/exceptions/{exception_one}/decisions",
                json={"decision_type": "ASSIGN", "reason": "review"},
            ).status_code
            == 201
        )

        run_two = _discrepancy_run(ca)

        events_one = ca.get(f"/api/v1/reconciliation/runs/{run_one}/audit").json()["events"]
        assert any(e["entity_id"] == exception_one for e in events_one)

        events_two = ca.get(f"/api/v1/reconciliation/runs/{run_two}/audit").json()["events"]
        # Run two's own exception has no decisions, so no event may reference
        # run one's exception.
        assert all(e["entity_id"] != exception_one for e in events_two)
        assert all(e["entity_id"] != run_one for e in events_two)

    def test_unknown_run_audit_is_404(self) -> None:
        r = _client(TENANT_A).get(f"/api/v1/reconciliation/runs/{uuid4()}/audit")
        assert r.status_code == 404
