"""Reconciliation REST endpoints (P2.6).

Thin routes over the existing FastAPI application. Each endpoint reuses the
tenant context established by ``TenantAuthMiddleware`` and the plain
persistence functions in ``finance.reconciliation.persistence``. No generic
CRUD, no new service layer, no new orchestration.

Only the endpoints required for the defined reconciliation workflow are
provided: create session, upload source, validate, reconcile, retrieve run
results, list exceptions, record a decision, and tenant-scoped audit
retrieval.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from finance.reconciliation.persistence import (
    create_import_session,
    get_audit_events,
    get_run,
    list_exceptions,
    persist_ingestion_report,
    record_decision,
    start_reconciliation,
    upload_source_file,
)
from finance.reconciliation.statement_workflow import (
    StatementSources,
    run_statement_reconciliation,
)
from finance.source_ingestion import SourceType, ingest_source
from shared.models.reconciliation import (
    PayoutAllocation,
    ReconciliationMatch,
    SourceFile,
)

router = APIRouter(tags=["reconciliation"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    period_start: date
    period_end: date


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str


class UploadSourceResponse(BaseModel):
    file_id: str
    row_count: int
    duplicate: bool


class ValidateResponse(BaseModel):
    status: str
    accepted_count: int
    rejected_count: int
    skipped_debits: int
    issues: list[dict[str, Any]]


class ReconcileRequest(BaseModel):
    idempotency_key: str = Field(min_length=1)
    tolerance_absolute: str = "0"
    tolerance_percent: str = "0"
    window_seconds: int | None = None


class ReconcileResponse(BaseModel):
    run_id: str
    status: str
    fingerprint: str


class DecisionRequest(BaseModel):
    decision_type: str
    reason: str = Field(min_length=1)
    new_status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_session(request: Request) -> Session:
    from apps.api.middleware import _default_session_factory

    return _default_session_factory()  # type: ignore[no-any-return]


def _actor(request: Request) -> dict[str, str]:
    actor = getattr(request.state, "actor", None)
    if not actor:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return actor  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/reconciliation/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    actor = _actor(request)
    session = _db_session(request)
    try:
        session_id = create_import_session(
            session,
            tenant_id=actor["tenant_id"],
            actor_id=actor["user_id"] or str(uuid4()),
            period_start=body.period_start,
            period_end=body.period_end,
        )
        session.commit()
        return CreateSessionResponse(session_id=session_id, status="CREATED")
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post(
    "/reconciliation/sessions/{session_id}/sources/{source_type}",
    response_model=UploadSourceResponse,
)
async def upload_source(
    session_id: str,
    source_type: str,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> UploadSourceResponse:
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        if source_type.upper() not in ("INVOICE", "STRIPE", "BANK"):
            raise HTTPException(status_code=400, detail="Unknown source type.")
        st = SourceType(source_type.upper())
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file.")
        digest = hashlib.sha256(content).hexdigest()
        existing = (
            session.query(SourceFile)
            .filter(
                SourceFile.tenant_id == tenant_id,
                SourceFile.source_type == source_type.upper(),
                SourceFile.content_hash == digest,
            )
            .first()
        )
        duplicate = existing is not None

        report = ingest_source(
            content,
            source_type=st,
            tenant_id=tenant_id,
            filename=file.filename,
        )

        from finance.reconciliation.persistence import get_import_session as _get_session

        sess = _get_session(session, session_id=session_id, tenant_id=tenant_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found.")

        file_id = upload_source_file(
            session,
            session_id=session_id,
            tenant_id=tenant_id,
            source_type=source_type.upper(),
            filename=file.filename or "upload",
            content_hash=digest,
            file_size_bytes=len(content),
            row_count=report.row_count,
            storage_ref=f"inline:{digest}",
            uploaded_by=actor["user_id"] or str(uuid4()),
        )
        persist_ingestion_report(
            session,
            file_id=file_id,
            session_id=session_id,
            tenant_id=tenant_id,
            source_type=source_type.upper(),
            report=report,
        )
        session.commit()
        return UploadSourceResponse(
            file_id=file_id,
            row_count=report.row_count,
            duplicate=duplicate,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/reconciliation/sessions/{session_id}/validate", response_model=ValidateResponse)
def validate_session(session_id: str, request: Request) -> ValidateResponse:
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        from finance.reconciliation.persistence import get_import_session as _get_session

        sess = _get_session(session, session_id=session_id, tenant_id=tenant_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        from shared.models.reconciliation import ImportRow

        rows = (
            session.query(ImportRow)
            .filter(ImportRow.session_id == session_id, ImportRow.tenant_id == tenant_id)
            .all()
        )
        accepted = sum(1 for r in rows if r.validation_status == "VALID")
        rejected = sum(1 for r in rows if r.validation_status == "INVALID")
        issues = [
            {"line_number": r.line_number, "code": r.reject_reason, "raw": r.raw_data}
            for r in rows
            if r.validation_status == "INVALID"
        ]
        sess.status = "READY" if rejected == 0 else "REJECTED"
        session.commit()
        return ValidateResponse(
            status=sess.status,
            accepted_count=accepted,
            rejected_count=rejected,
            skipped_debits=0,
            issues=issues,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/reconciliation/sessions/{session_id}/reconcile", response_model=ReconcileResponse)
def reconcile_session(
    session_id: str,
    body: ReconcileRequest,
    request: Request,
) -> ReconcileResponse:
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        from finance.reconciliation.persistence import get_import_session as _get_session

        sess = _get_session(session, session_id=session_id, tenant_id=tenant_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found.")

        from shared.models.reconciliation import ImportRow

        rows = (
            session.query(ImportRow)
            .filter(ImportRow.session_id == session_id, ImportRow.tenant_id == tenant_id)
            .all()
        )
        invoices = []
        charges = []
        bank_rows = []
        for r in rows:
            if r.validation_status != "VALID":
                continue
            norm = r.normalized or {}
            if norm.get("record_type") == "PAYMENT":
                from finance.reconciliation.models import PaymentRecord

                rec = PaymentRecord(
                    payment_id=norm["payment_id"],
                    provider=norm["provider"],
                    provider_event_id=norm["provider_event_id"],
                    idempotency_key=norm["idempotency_key"],
                    gross=Decimal(norm["gross"]),
                    fee=Decimal(norm["fee"]),
                    refund=Decimal(norm["refund"]),
                    net=Decimal(norm["net"]),
                    currency=norm["currency"],
                    status=norm["status"],
                    occurred_at=datetime.fromisoformat(norm["occurred_at"]),
                    tenant_id=norm["tenant_id"],
                    source_reference=norm.get("source_reference"),
                )
                if r.source_type == "INVOICE":
                    invoices.append(rec)
                else:
                    charges.append(rec)
            elif norm.get("record_type") == "DEPOSIT":
                bank_rows.append(
                    {
                        "deposit_id": norm["deposit_id"],
                        "amount": norm["amount"],
                        "posted_at": str(norm["posted_at"])[:10],
                        "fee": norm["fee"],
                        "account": norm.get("account_reference", ""),
                        "reference": norm.get("reference", ""),
                        "description": norm.get("description", ""),
                    }
                )

        from finance.reconciliation.bank import BankStatementMapping
        from finance.reconciliation.tolerances import ReconciliationTolerance

        currency = invoices[0].currency if invoices else (charges[0].currency if charges else "USD")
        sources = StatementSources(
            tenant_id=tenant_id,
            currency=currency,
            invoices=invoices,
            charges=charges,
            bank_rows=bank_rows,
            mapping=BankStatementMapping(statement_currency=currency),
            statement_digest="0" * 64,
            tolerance=ReconciliationTolerance(
                absolute=Decimal(body.tolerance_absolute),
                percent=Decimal(body.tolerance_percent),
            ),
            window_seconds=body.window_seconds,
        )
        report = run_statement_reconciliation(sources)

        run_id = start_reconciliation(
            session,
            tenant_id=tenant_id,
            session_id=session_id,
            actor_id=actor["user_id"] or str(uuid4()),
            idempotency_key=body.idempotency_key,
            engine_version="dev",
            input_fingerprint=report.fingerprint,
            input_snapshot_ref=f"session:{session_id}",
            report=report,
            currency=currency,
        )
        session.commit()
        return ReconcileResponse(
            run_id=run_id,
            status="SUCCEEDED",
            fingerprint=report.fingerprint,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/reconciliation/runs/{run_id}")
def get_run_detail(run_id: str, request: Request) -> dict[str, Any]:
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        run = get_run(session, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        matches = (
            session.query(ReconciliationMatch)
            .filter(
                ReconciliationMatch.run_id == run_id,
                ReconciliationMatch.tenant_id == tenant_id,
            )
            .all()
        )
        allocations = (
            session.query(PayoutAllocation)
            .filter(
                PayoutAllocation.run_id == run_id,
                PayoutAllocation.tenant_id == tenant_id,
            )
            .all()
        )
        exceptions = list_exceptions(session, run_id=run_id, tenant_id=tenant_id)
        return {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "status": run.status,
            "engine_version": run.engine_version,
            "input_fingerprint": run.input_fingerprint,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "matches": [
                {
                    "match_id": m.match_id,
                    "invoice_id": m.invoice_id,
                    "charge_id": m.charge_id,
                    "outcome": m.outcome,
                    "expected_amount": str(m.expected_amount),
                    "observed_amount": str(m.observed_amount),
                    "difference": str(m.difference),
                    "variance": str(m.variance),
                    "currency": m.currency,
                    "exception_code": m.exception_code,
                    "materiality": m.materiality,
                }
                for m in matches
            ],
            "allocations": [
                {
                    "allocation_id": a.allocation_id,
                    "deposit_id": a.deposit_id,
                    "outcome": a.outcome,
                    "allocated_total": str(a.allocated_total),
                    "open_balance": str(a.open_balance),
                    "unallocated_deposit": str(a.unallocated_deposit),
                    "exception_code": a.exception_code,
                }
                for a in allocations
            ],
            "exceptions": [
                {
                    "exception_id": e.exception_id,
                    "exception_code": e.exception_code,
                    "severity": e.severity,
                    "status": e.status,
                    "title": e.title,
                    "description": e.description,
                }
                for e in exceptions
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/reconciliation/runs/{run_id}/audit")
def get_run_audit(run_id: str, request: Request) -> dict[str, Any]:
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        events = get_audit_events(session, tenant_id=tenant_id, limit=200)
        return {
            "run_id": run_id,
            "events": [
                {
                    "event_id": e.event_id,
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "action": e.action,
                    "actor_id": e.actor_id,
                    "previous_state": e.previous_state,
                    "new_state": e.new_state,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/reconciliation/exceptions/{exception_id}/decisions")
def decide_exception(
    exception_id: str,
    body: DecisionRequest,
    request: Request,
) -> dict[str, Any]:
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        from shared.models.reconciliation import ReconciliationException

        exc = session.get(ReconciliationException, exception_id)
        if exc is None or exc.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Exception not found.")
        decision_id = record_decision(
            session,
            exception_id=exception_id,
            tenant_id=tenant_id,
            actor_id=actor["user_id"] or str(uuid4()),
            decision_type=body.decision_type,
            reason=body.reason,
            previous_status=exc.status,
            new_status=body.new_status,
        )
        session.commit()
        return {"decision_id": decision_id, "status": body.new_status}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()
