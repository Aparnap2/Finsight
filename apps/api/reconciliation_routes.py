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

from finance.exceptions.errors import IllegalTransitionError
from finance.reconciliation.exception_lifecycle import allowed_targets
from finance.reconciliation.models import ExceptionStatus
from finance.reconciliation.persistence import (
    create_import_session,
    get_audit_events,
    get_import_session,
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
    AllocationLeg,
    ExceptionDecision,
    ExportArtifact,
    ImportRow,
    PayoutAllocation,
    ReconciliationException,
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
    evidence_refs: list[str] | None = None
    # Optional: when omitted the target status is derived from decision_type
    # through the exception state machine (see ``_target_status``).
    new_status: str | None = None


class CreateExportRequest(BaseModel):
    format: str = Field(default="CSV")


# Result status implied by a decision type; ASSIGN depends on the current state.
_DECISION_TARGET: dict[str, str] = {
    "APPROVE": ExceptionStatus.RESOLVED.value,
    "REJECT": ExceptionStatus.REOPENED.value,
    "REOPEN": ExceptionStatus.INVESTIGATING.value,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_session(request: Request) -> Session:
    from sqlalchemy import event, text

    from apps.api.middleware import _default_session_factory

    session = _default_session_factory()
    # Wire the tenant into RLS on THIS session's connection. The middleware
    # validates headers and stashes the actor, but it must not open a separate
    # DB session to set the GUC: that setting is transaction-scoped and would
    # be rolled back before the route's own session ever sees it, leaving
    # production (non-superuser) requests without a tenant context.
    actor = getattr(request.state, "actor", None)
    tenant_id = actor.get("tenant_id") if isinstance(actor, dict) else None
    if tenant_id:
        # ``set_config(..., is_local => true)`` is transaction-scoped, so a
        # single eager call is lost the moment a route commits and then reads
        # again (e.g. ``session.get`` after ``commit``, or an expired attribute
        # refresh). Re-apply it at the start of every transaction on this
        # session. Being transaction-local, it can never leak onto the next
        # request that checks the same pooled connection out.
        @event.listens_for(session, "after_begin")
        def _apply_tenant_guc(_session: Session, _transaction: Any, connection: Any) -> None:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )

    return session  # type: ignore[no-any-return]


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
    statement_currency: str = "USD",
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
            statement_currency=statement_currency if st == SourceType.BANK else None,
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
    """Return audit events belonging to one run and its child records.

    Scoped by entity id, not just tenant: a previous version returned every
    audit event for the tenant and ignored ``run_id`` entirely.
    """
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        _require_run(session, run_id, tenant_id)
        matches = (
            session.query(ReconciliationMatch.match_id)
            .filter(
                ReconciliationMatch.run_id == run_id,
                ReconciliationMatch.tenant_id == tenant_id,
            )
            .all()
        )
        allocations = (
            session.query(PayoutAllocation.allocation_id)
            .filter(
                PayoutAllocation.run_id == run_id,
                PayoutAllocation.tenant_id == tenant_id,
            )
            .all()
        )
        exceptions = list_exceptions(session, run_id=run_id, tenant_id=tenant_id)
        entity_ids = [run_id]
        entity_ids.extend(str(v) for (v,) in matches)
        entity_ids.extend(str(v) for (v,) in allocations)
        entity_ids.extend(e.exception_id for e in exceptions)
        events = get_audit_events(session, tenant_id=tenant_id, entity_ids=entity_ids, limit=200)
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
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/reconciliation/exceptions/{exception_id}/investigate")
def investigate_exception(
    exception_id: str,
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

        from finance.reconciliation.investigation import (
            BoundedInvestigation,
            InvestigationContext,
        )
        from shared.llm.factory import create_provider_from_settings

        provider = create_provider_from_settings()
        investigator = BoundedInvestigation(provider)
        context = InvestigationContext(
            exception_id=exc.exception_id,
            exception_code=exc.exception_code,
            title=exc.title,
            description=exc.description,
            evidence_refs=list(exc.evidence_refs or []),
        )
        finding = investigator.investigate(context)

        from shared.models.reconciliation import Investigation as InvRow

        inv = InvRow(
            exception_id=exception_id,
            tenant_id=tenant_id,
            status="COMPLETED" if not finding.abstained else "FAILED",
            result_text=finding.claim,
            evidence_refs=finding.evidence_refs,
            created_by=actor["user_id"] or str(uuid4()),
        )
        session.add(inv)
        session.commit()
        return {
            "investigation_id": inv.investigation_id,
            "claim": finding.claim,
            "evidence_refs": finding.evidence_refs,
            "confidence": finding.confidence,
            "abstained": finding.abstained,
            "abstention_reason": finding.abstention_reason,
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/exceptions/{exception_id}/decisions", status_code=201)
def decide_exception(
    exception_id: str,
    body: DecisionRequest,
    request: Request,
) -> dict[str, Any]:
    """Record a human decision on an exception (contract §2.3).

    The target status is derived from ``decision_type`` through the exception
    state machine unless the caller supplies one. An illegal move returns 400; a
    repeat of a decision that would be a no-op (for example a second APPROVE on
    an already-RESOLVED exception) returns 409.
    """
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        exc = _require_exception(session, exception_id, tenant_id)
        requested_type = body.decision_type.upper()
        new_status = body.new_status or _target_status(exc.status, requested_type)
        previous_status = exc.status
        try:
            decision_id = record_decision(
                session,
                exception_id=exception_id,
                tenant_id=tenant_id,
                actor_id=actor["user_id"] or str(uuid4()),
                decision_type=requested_type,
                reason=body.reason,
                previous_status=previous_status,
                new_status=new_status,
                evidence_refs=body.evidence_refs,
            )
        except IllegalTransitionError as exc_error:
            session.rollback()
            if "no-op" in str(exc_error):
                raise HTTPException(status_code=409, detail="Duplicate decision.") from exc_error
            raise HTTPException(status_code=400, detail=str(exc_error)) from exc_error
        session.commit()
        decision = session.get(ExceptionDecision, decision_id)
        return {
            "decision_id": decision_id,
            "exception_id": exception_id,
            "decision_type": requested_type,
            "previous_status": previous_status,
            "new_status": new_status,
            "decided_at": _iso(decision.decided_at) if decision is not None else None,
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Contract endpoints (docs/specs/API_CONTRACT.md §2.1-2.4)
#
# These expose the same persisted rows as the routes above but at the paths and
# response shapes the frozen contract specifies. No new business logic: every
# handler reads or writes through finance.reconciliation.persistence.
# ---------------------------------------------------------------------------


def _require_run(session: Session, run_id: str, tenant_id: str) -> Any:
    """Return the tenant-scoped run or raise 404."""
    run = get_run(session, run_id=run_id, tenant_id=tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


def _require_exception(session: Session, exception_id: str, tenant_id: str) -> Any:
    """Return the tenant-scoped exception or raise 404."""
    exc = session.get(ReconciliationException, exception_id)
    if exc is None or exc.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Exception not found.")
    return exc


def _iso(value: Any) -> str | None:
    """Serialize an optional datetime to ISO-8601."""
    return value.isoformat() if value is not None else None


def _target_status(current: str, decision_type: str) -> str:
    """Resolve the status a decision moves an exception to.

    ``ASSIGN`` is state-dependent, so it picks the first allowed target from the
    exception state machine. An unknown decision type is a 400, matching the
    contract's ``400 (invalid transition)``.
    """
    decision = decision_type.upper()
    if decision == "ASSIGN":
        targets = allowed_targets(current)
        for candidate in (ExceptionStatus.UNDER_REVIEW, ExceptionStatus.INVESTIGATING):
            if candidate in targets:
                return candidate.value
        raise HTTPException(
            status_code=400,
            detail=f"No legal ASSIGN target from status {current!r}.",
        )
    target = _DECISION_TARGET.get(decision)
    if target is None:
        raise HTTPException(status_code=400, detail=f"Unknown decision_type {decision_type!r}.")
    return target


@router.get("/import-sessions/{session_id}")
def get_session_detail(session_id: str, request: Request) -> dict[str, Any]:
    """Full import-session detail with per-file validation status."""
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        sess = get_import_session(session, session_id=session_id, tenant_id=tenant_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        files = (
            session.query(SourceFile)
            .filter(SourceFile.session_id == session_id, SourceFile.tenant_id == tenant_id)
            .all()
        )
        counts: dict[str, list[int]] = {
            f.file_id: [0, 0] for f in files
        }  # file_id -> [valid, invalid]
        rows = (
            session.query(ImportRow)
            .filter(ImportRow.session_id == session_id, ImportRow.tenant_id == tenant_id)
            .all()
        )
        for row in rows:
            bucket = counts.setdefault(row.file_id, [0, 0])
            bucket[0 if row.validation_status == "VALID" else 1] += 1
        return {
            "session_id": sess.session_id,
            "tenant_id": sess.tenant_id,
            "status": sess.status,
            "period_start": _iso(sess.period_start),
            "period_end": _iso(sess.period_end),
            "created_at": _iso(sess.created_at),
            "files": [
                {
                    "file_id": f.file_id,
                    "source_type": f.source_type,
                    "filename": f.filename,
                    "row_count": f.row_count,
                    "content_hash": f.content_hash,
                    "valid_rows": counts.get(f.file_id, [0, 0])[0],
                    "invalid_rows": counts.get(f.file_id, [0, 0])[1],
                    "uploaded_at": _iso(f.uploaded_at),
                }
                for f in files
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/runs/{run_id}/matches")
def list_run_matches(
    run_id: str, request: Request, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """List invoice-to-charge matches for a run (contract §2.2)."""
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        _require_run(session, run_id, tenant_id)
        query = session.query(ReconciliationMatch).filter(
            ReconciliationMatch.run_id == run_id,
            ReconciliationMatch.tenant_id == tenant_id,
        )
        total = query.count()
        matches = query.order_by(ReconciliationMatch.match_id).offset(offset).limit(limit).all()
        return {
            "run_id": run_id,
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
                    "tolerance_applied": str(m.tolerance_applied),
                    "currency": m.currency,
                    "exception_code": m.exception_code,
                    "materiality": m.materiality,
                    "fingerprint": m.fingerprint,
                }
                for m in matches
            ],
            "total_count": total,
            "has_more": offset + len(matches) < total,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/runs/{run_id}/allocations")
def list_run_allocations(
    run_id: str, request: Request, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """List deposit allocations for a run, with their legs (contract §2.2)."""
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        _require_run(session, run_id, tenant_id)
        query = session.query(PayoutAllocation).filter(
            PayoutAllocation.run_id == run_id,
            PayoutAllocation.tenant_id == tenant_id,
        )
        total = query.count()
        allocations = (
            query.order_by(PayoutAllocation.allocation_id).offset(offset).limit(limit).all()
        )
        allocation_ids = [a.allocation_id for a in allocations]
        legs = (
            session.query(AllocationLeg)
            .filter(
                AllocationLeg.allocation_id.in_(allocation_ids),
                AllocationLeg.tenant_id == tenant_id,
            )
            .order_by(AllocationLeg.payment_id)
            .all()
            if allocation_ids
            else []
        )
        legs_by_allocation: dict[str, list[dict[str, Any]]] = {}
        for leg in legs:
            legs_by_allocation.setdefault(leg.allocation_id, []).append(
                {
                    "payment_id": leg.payment_id,
                    "gross": str(leg.gross),
                    "fee": str(leg.fee),
                    "refund": str(leg.refund),
                    "net": str(leg.net),
                    "allocated": str(leg.allocated),
                    "fingerprint": leg.fingerprint,
                }
            )
        return {
            "run_id": run_id,
            "allocations": [
                {
                    "allocation_id": a.allocation_id,
                    "deposit_id": a.deposit_id,
                    "outcome": a.outcome,
                    "allocated_total": str(a.allocated_total),
                    "eligible_net_total": str(a.eligible_net_total),
                    "open_balance": str(a.open_balance),
                    "unallocated_deposit": str(a.unallocated_deposit),
                    "fee_total": str(a.fee_total),
                    "refund_total": str(a.refund_total),
                    "exception_code": a.exception_code,
                    "fingerprint": a.fingerprint,
                    "legs": legs_by_allocation.get(a.allocation_id, []),
                }
                for a in allocations
            ],
            "total_count": total,
            "has_more": offset + len(allocations) < total,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/runs/{run_id}/exceptions")
def list_run_exceptions(
    run_id: str, request: Request, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """List exceptions raised by a run (contract §2.2)."""
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        _require_run(session, run_id, tenant_id)
        all_exceptions = list_exceptions(session, run_id=run_id, tenant_id=tenant_id)
        page = all_exceptions[offset : offset + limit]
        return {
            "run_id": run_id,
            "exceptions": [_exception_payload(e) for e in page],
            "total_count": len(all_exceptions),
            "has_more": offset + len(page) < len(all_exceptions),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


def _exception_payload(exc: ReconciliationException) -> dict[str, Any]:
    """Serialize an exception in the contract's §2.2 shape."""
    return {
        "exception_id": exc.exception_id,
        "exception_code": exc.exception_code,
        "severity": exc.severity,
        "status": exc.status,
        "title": exc.title,
        "description": exc.description,
        "evidence_refs": list(exc.evidence_refs or []),
        "created_at": _iso(exc.created_at),
    }


@router.get("/exceptions/{exception_id}")
def get_exception_detail(exception_id: str, request: Request) -> dict[str, Any]:
    """Full exception detail with evidence and its decision history."""
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        exc = _require_exception(session, exception_id, tenant_id)
        decisions = (
            session.query(ExceptionDecision)
            .filter(
                ExceptionDecision.exception_id == exception_id,
                ExceptionDecision.tenant_id == tenant_id,
            )
            .order_by(ExceptionDecision.decided_at)
            .all()
        )
        payload = _exception_payload(exc)
        payload.update(
            {
                "run_id": exc.run_id,
                "tenant_id": exc.tenant_id,
                "assigned_to": exc.assigned_to,
                "updated_at": _iso(exc.updated_at),
                "decisions": [
                    {
                        "decision_id": d.decision_id,
                        "decision_type": d.decision_type,
                        "reason": d.reason,
                        "evidence_refs": list(d.evidence_refs or []),
                        "previous_status": d.previous_status,
                        "new_status": d.new_status,
                        "actor_id": d.actor_id,
                        "decided_at": _iso(d.decided_at),
                    }
                    for d in decisions
                ],
            }
        )
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/runs/{run_id}/exports", status_code=201)
def create_run_export(run_id: str, body: CreateExportRequest, request: Request) -> dict[str, Any]:
    """Create an export artifact record for a run (contract §2.4).

    Only the artifact row is created; producing the bytes is a separate worker
    and is not implemented. Status therefore starts ``PENDING`` and stays there
    until a generator advances it, which is why the endpoint is reported as
    CONDITIONAL rather than a working export pipeline.
    """
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        _require_run(session, run_id, tenant_id)
        export_format = body.format.upper()
        if export_format not in ("CSV", "JSON", "MARKDOWN"):
            raise HTTPException(status_code=400, detail="format must be CSV, JSON or MARKDOWN.")
        artifact = ExportArtifact(
            run_id=run_id,
            tenant_id=tenant_id,
            status="PENDING",
            format=export_format,
            created_by=actor["user_id"] or str(uuid4()),
        )
        session.add(artifact)
        session.commit()
        return {
            "export_id": artifact.export_id,
            "run_id": run_id,
            "status": artifact.status,
            "format": artifact.format,
            "created_at": _iso(artifact.created_at),
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/exports/{export_id}")
def get_export(export_id: str, request: Request) -> dict[str, Any]:
    """Retrieve an export artifact record (contract §2.4)."""
    actor = _actor(request)
    tenant_id = actor["tenant_id"]
    session = _db_session(request)
    try:
        artifact = session.get(ExportArtifact, export_id)
        if artifact is None or artifact.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Export not found.")
        return {
            "export_id": artifact.export_id,
            "run_id": artifact.run_id,
            "status": artifact.status,
            "format": artifact.format,
            "storage_ref": artifact.storage_ref,
            "file_size_bytes": artifact.file_size_bytes,
            "created_at": _iso(artifact.created_at),
            "completed_at": _iso(artifact.completed_at),
            "error_code": artifact.error_code,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()
