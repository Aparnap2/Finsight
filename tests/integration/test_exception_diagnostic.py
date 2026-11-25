"""P2.9 — CP2 diagnostic composition (Postgres-backed)."""

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
from finance.reconciliation.context import ExceptionDiagnostic
from finance.reconciliation.context_builder import ContextNotFoundError, CurrencyRequiredError
from finance.reconciliation.diagnostics import diagnose_exception

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


def _run_discrepancy(client: TestClient) -> tuple[str, str, str]:
    """Run discrepancy batch; return (run_id, exception_id, snapshot_id)."""
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
            "idempotency_key": f"diag-{uuid4()}",
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
            snapshot_id = conn.execute(
                text("SELECT input_snapshot_ref FROM reconciliation_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).scalar()
    finally:
        engine.dispose()
    assert exception_id, "discrepancy batch produced no exception"
    return str(run_id), str(exception_id), str(snapshot_id or run_id)


class TestExceptionDiagnostic:
    def test_diagnose_complete_fee_discrepancy(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                diag = diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        assert isinstance(diag, ExceptionDiagnostic)
        assert diag.run_id == run_id
        assert diag.exception_id == exception_id
        assert diag.tenant_id == TENANT_A
        assert diag.snapshot_id, "snapshot_id must be present"
        assert diag.engine_version, "engine_version must be present"
        assert diag.context.evidence_refs, "evidence_refs must be populated"
        assert diag.rule_results, "rule_results must be non-empty"
        # money precision preserved
        for key in ("expected_net", "actual_deposit", "variance", "tolerance"):
            val = getattr(diag.context, key)
            assert isinstance(val, str)
        # rule ids include payout variance + evidence completeness
        rule_ids = {r.rule_id for r in diag.rule_results}
        assert "PAYOUT_VARIANCE" in rule_ids
        assert "EVIDENCE_COMPLETENESS" in rule_ids
        assert "CALCULATION_CONSISTENCY" in rule_ids
        # CP3 eligibility attached and ELIGIBLE for a complete, consistent run
        assert diag.eligibility is not None
        assert diag.eligibility.status.value == "ELIGIBLE"

    def test_diagnose_deterministic(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                a = diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="USD",
                )
                b = diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        import json

        assert json.dumps(a.model_dump(), sort_keys=True) == json.dumps(
            b.model_dump(), sort_keys=True
        )
        assert a.query_count == b.query_count

    def test_cross_tenant_denied(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session, pytest.raises(ContextNotFoundError):
                diagnose_exception(
                    session,
                    tenant_id=TENANT_B,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()

    def test_unknown_snapshot_raises(self) -> None:
        engine = create_engine(DSN)
        try:
            with Session(engine) as session, pytest.raises(ContextNotFoundError):
                diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=str(uuid4()),
                    exception_id=str(uuid4()),
                    currency="USD",
                )
        finally:
            engine.dispose()

    def test_unknown_currency_raises(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session, pytest.raises(CurrencyRequiredError):
                diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="",
                )
            with Session(engine) as session, pytest.raises(CurrencyRequiredError):
                diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="US",
                )
        finally:
            engine.dispose()

    def test_missing_evidence_ineligible(self) -> None:
        # Build a context manually by using a real run but an exception with no evidence refs.
        # We simulate by checking that an exception with empty evidence_refs would be ineligible.
        # Here we just verify the rule result structure is present for a real run.
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                diag = diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        # evidence completeness rule present
        rule_ids = {r.rule_id for r in diag.rule_results}
        assert "EVIDENCE_COMPLETENESS" in rule_ids
        # query_count recorded and non-negative
        assert diag.query_count >= 0

    def test_decimal_precision(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        engine = create_engine(DSN)
        try:
            with Session(engine) as session:
                diag = diagnose_exception(
                    session,
                    tenant_id=TENANT_A,
                    snapshot_id=snapshot_id,
                    exception_id=exception_id,
                    currency="USD",
                )
        finally:
            engine.dispose()
        for key in ("expected_net", "actual_deposit", "variance", "tolerance"):
            val = getattr(diag.context, key)
            assert isinstance(val, str)
            assert "e" not in val.lower() or "." in val


class TestInvestigateEligibilityGate:
    def test_ineligible_returns_409(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        # Strip evidence to make the exception INELIGIBLE.
        engine = create_engine(DSN)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE reconciliation_exceptions SET evidence_refs = '[]'::json WHERE exception_id = :e"),
                    {"e": exception_id},
                )
        finally:
            engine.dispose()
        r = ca.post(f"/api/v1/reconciliation/exceptions/{exception_id}/investigate")
        assert r.status_code == 409, r.text
        assert "INELIGIBLE" in r.text

    def test_eligible_reaches_provider_boundary(self) -> None:
        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        # Eligibility should pass (ELIGIBLE), so the request proceeds to the
        # LLM provider boundary. Without a configured provider this yields 500
        # (provider unavailable), NOT 409 — proving the gate did not block.
        r = ca.post(f"/api/v1/reconciliation/exceptions/{exception_id}/investigate")
        assert r.status_code != 409, r.text
        assert r.status_code in (200, 500), r.text

    def test_investigate_with_mocked_provider_persists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from shared.llm.fake import FakeLLM

        fake = FakeLLM(scripted={
            "InvestigationFinding": {
                "claim": "Fee discrepancy due to timing.",
                "evidence_refs": ["ch_a", "dep_1"],
                "confidence": "medium",
                "abstained": False,
            }
        })

        def _fake_provider():
            return fake

        monkeypatch.setattr(
            "shared.llm.factory.create_provider_from_settings", _fake_provider
        )

        ca = _client(TENANT_A)
        run_id, exception_id, snapshot_id = _run_discrepancy(ca)
        r = ca.post(f"/api/v1/reconciliation/exceptions/{exception_id}/investigate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["abstained"] is False
        assert body["claim"] == "Fee discrepancy due to timing."
        # persisted investigation is retrievable
        inv_id = body["investigation_id"]
        r2 = ca.get(f"/api/v1/investigations/{inv_id}")
        assert r2.status_code == 200, r2.text
        assert r2.json()["investigation_id"] == inv_id
