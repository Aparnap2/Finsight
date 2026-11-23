"""Thin persistence functions for the reconciliation domain.

This module is deliberately not a repository framework. It is a set of plain
functions that persist the deterministic output of the reconciliation engine
into the tables defined in ``docs/specs/DATABASE_SCHEMA.md``. Each function
accepts a SQLAlchemy ``Session`` (with the tenant context already established
by ``TenantAuthMiddleware``) and uses ``persist_guarded`` so SQL transport
failures surface as ``PersistenceError``.

Transaction control stays with the caller. ``start_reconciliation`` adds every
row for one run to the session and flushes; the caller commits or rolls back.
This keeps the single-transaction invariant explicit and lets tests inject a
failure at any stage and roll back.

No new abstractions, no orchestration, no queues.

Only SQLAlchemy plus the Python standard library are used.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finance.reconciliation.exception_lifecycle import validate_transition
from finance.reconciliation.statement_workflow import (
    ReconciliationReport,
)
from shared.models.reconciliation import (
    AllocationLeg as AllocationLegRow,
)
from shared.models.reconciliation import (
    AuditEvent,
    ExceptionDecision,
    ExportArtifact,
    ImportRow,
    ImportSession,
    Investigation,
    PayoutAllocation,
    ReconciliationException,
    ReconciliationMatch,
    ReconciliationRun,
    SourceFile,
    Tenant,
)
from shared.safety.errors import persist_guarded

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Import sessions
# --------------------------------------------------------------------------- #


@persist_guarded
def create_import_session(
    session: Session,
    *,
    tenant_id: str,
    actor_id: str,
    period_start: date,
    period_end: date,
) -> str:
    """Create an import session and return its id. Does not commit."""
    row = ImportSession(
        tenant_id=tenant_id,
        actor_id=actor_id,
        period_start=period_start,
        period_end=period_end,
        status="CREATED",
    )
    session.add(row)
    session.flush()
    return row.session_id


@persist_guarded
def get_import_session(
    session: Session, *, session_id: str, tenant_id: str
) -> ImportSession | None:
    """Return the session row for this tenant, or None."""
    row = session.get(ImportSession, session_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


# --------------------------------------------------------------------------- #
# Source files
# --------------------------------------------------------------------------- #


@persist_guarded
def upload_source_file(
    session: Session,
    *,
    session_id: str,
    tenant_id: str,
    source_type: str,
    filename: str,
    content_hash: str,
    file_size_bytes: int,
    row_count: int,
    storage_ref: str,
    uploaded_by: str,
) -> str:
    """Insert source-file metadata. Returns the file id.

    Idempotent on ``(tenant_id, source_type, content_hash)``: if a matching row
    already exists it is returned instead of inserting a duplicate.
    """
    existing = (
        session.query(SourceFile)
        .filter(
            SourceFile.tenant_id == tenant_id,
            SourceFile.source_type == source_type,
            SourceFile.content_hash == content_hash,
        )
        .first()
    )
    if existing is not None:
        return existing.file_id
    row = SourceFile(
        session_id=session_id,
        tenant_id=tenant_id,
        source_type=source_type,
        filename=filename,
        content_hash=content_hash,
        file_size_bytes=file_size_bytes,
        row_count=row_count,
        storage_ref=storage_ref,
        uploaded_by=uploaded_by,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = (
            session.query(SourceFile)
            .filter(
                SourceFile.tenant_id == tenant_id,
                SourceFile.source_type == source_type,
                SourceFile.content_hash == content_hash,
            )
            .first()
        )
        if existing is None:
            raise
        return existing.file_id
    return row.file_id


# --------------------------------------------------------------------------- #
# Canonical row persistence
# --------------------------------------------------------------------------- #


@persist_guarded
def persist_ingestion_report(
    session: Session,
    *,
    file_id: str,
    session_id: str,
    tenant_id: str,
    source_type: str,
    report: Any,
) -> int:
    """Persist the accepted and rejected rows from an IngestionReport.

    Returns the number of rows written. Does not commit.
    """
    count = 0
    for record in getattr(report, "records", ()):
        normalized = _record_to_dict(record)
        row = ImportRow(
            file_id=file_id,
            session_id=session_id,
            tenant_id=tenant_id,
            source_type=source_type,
            line_number=record.line_number,
            raw_data=dict(record.raw),
            normalized=normalized,
            validation_status="VALID",
        )
        session.add(row)
        count += 1
    for issue in getattr(report, "issues", ()):
        row = ImportRow(
            file_id=file_id,
            session_id=session_id,
            tenant_id=tenant_id,
            source_type=source_type,
            line_number=issue.line_number,
            raw_data=dict(issue.raw),
            normalized=None,
            validation_status="INVALID",
            reject_reason=issue.code.value,
        )
        session.add(row)
        count += 1
    session.flush()
    return count


def _record_to_dict(record: Any) -> dict[str, Any]:
    """Render a canonical record as the JSONB ``normalized`` payload."""
    underlying = getattr(record, "record", None)
    if underlying is None:
        return {}
    if hasattr(underlying, "payment_id"):
        return {
            "record_type": "PAYMENT",
            "payment_id": underlying.payment_id,
            "provider": underlying.provider,
            "provider_event_id": underlying.provider_event_id,
            "idempotency_key": underlying.idempotency_key,
            "gross": str(underlying.gross),
            "fee": str(underlying.fee),
            "refund": str(underlying.refund),
            "net": str(underlying.net),
            "currency": underlying.currency,
            "status": underlying.status.value,
            "occurred_at": underlying.occurred_at.isoformat(),
            "source_reference": underlying.source_reference,
            "tenant_id": underlying.tenant_id,
        }
    return {
        "record_type": "DEPOSIT",
        "deposit_id": underlying.deposit_id,
        "tenant_id": underlying.tenant_id,
        "amount": str(underlying.amount),
        "fee": str(underlying.fee),
        "currency": underlying.currency,
        "posted_at": underlying.posted_at.isoformat(),
        "statement_digest": underlying.statement_digest,
        "line_number": underlying.line_number,
        "account_reference": underlying.account_reference,
        "reference": underlying.reference,
        "description": underlying.description,
    }


# --------------------------------------------------------------------------- #
# Reconciliation runs
# --------------------------------------------------------------------------- #


def _severity_for(code: str | None) -> str:
    """Map an exception code to a severity. Deterministic, documented."""
    if code in ("I-DUPLICATE", "I-PAYOUT"):
        return "HIGH"
    if code in ("I-PARTIAL",):
        return "MEDIUM"
    return "MEDIUM"


def _title_for(code: str | None) -> str:
    """Human-readable title for an exception code."""
    titles = {
        "I-REFUND-LAG": "Partial refund accounting lag",
        "I-FEE-DRIFT": "Fee mismatch",
        "I-DUPLICATE": "Duplicate ledger entry",
        "I-PARTIAL": "Partial settlement",
        "I-PAYOUT": "Payout mismatch",
    }
    return titles.get(code or "", "Reconciliation exception")


@persist_guarded
def start_reconciliation(
    session: Session,
    *,
    tenant_id: str,
    session_id: str,
    actor_id: str,
    idempotency_key: str,
    engine_version: str,
    input_fingerprint: str,
    input_snapshot_ref: str,
    report: ReconciliationReport,
    currency: str,
) -> str:
    """Persist a complete reconciliation run atomically. Returns the run id.

    The caller must have already executed the deterministic engine and hold
    the ``ReconciliationReport``. This function adds every row (run, matches,
    allocations, legs, exceptions) to the session and flushes; the caller
    commits or rolls back the whole transaction.

    Idempotent on ``(tenant_id, idempotency_key)``: a repeat with the same key
    returns the existing run id. A repeat with a differing input fingerprint
    raises ``ValueError`` (idempotency conflict).
    """
    existing = (
        session.query(ReconciliationRun)
        .filter(
            ReconciliationRun.tenant_id == tenant_id,
            ReconciliationRun.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise ValueError(
                f"Idempotency conflict: key {idempotency_key!r} was already used "
                f"with a different input fingerprint."
            )
        return existing.run_id

    run = ReconciliationRun(
        session_id=session_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        status="PROCESSING",
        engine_version=engine_version,
        input_fingerprint=input_fingerprint,
        input_snapshot_ref=input_snapshot_ref,
    )
    session.add(run)
    session.flush()

    # Matches (invoice -> charge edges)
    for link in getattr(report, "links", ()):
        result = link.result
        match = ReconciliationMatch(
            run_id=run.run_id,
            tenant_id=tenant_id,
            invoice_id=link.invoice_id,
            charge_id=link.charge_id,
            outcome=result.outcome.value,
            expected_amount=result.expected,
            observed_amount=result.observed,
            difference=result.difference,
            variance=result.variance,
            tolerance_applied=result.tolerance_applied,
            currency=currency,
            exception_code=result.exception_code or None,
            materiality=result.materiality.value,
            fingerprint=result.fingerprint,
        )
        session.add(match)

    # Payout allocations (deposit -> charges)
    for deposit in getattr(report, "deposits", ()):
        allocation = deposit.allocation
        payout = PayoutAllocation(
            run_id=run.run_id,
            tenant_id=tenant_id,
            deposit_id=allocation.deposit.deposit_id if allocation.deposit else deposit.deposit_id,
            outcome=allocation.outcome.value,
            allocated_total=allocation.allocated_total,
            eligible_net_total=allocation.eligible_net_total,
            open_balance=allocation.open_balance,
            unallocated_deposit=allocation.unallocated_deposit,
            fee_total=allocation.fee_total,
            refund_total=allocation.refund_total,
            exception_code=allocation.exception_code.value if allocation.exception_code else None,
            fingerprint=allocation.fingerprint,
        )
        session.add(payout)
        session.flush()
        for leg in allocation.legs:
            leg_row = AllocationLegRow(
                allocation_id=payout.allocation_id,
                tenant_id=tenant_id,
                payment_id=leg.payment_id,
                gross=leg.gross,
                fee=leg.fee,
                refund=leg.refund,
                net=leg.net,
                allocated=leg.allocated,
                fingerprint=leg.fingerprint,
            )
            session.add(leg_row)

    # Exceptions: from invoice->charge links
    for link in getattr(report, "links", ()):
        result = link.result
        if result.outcome.value != "EXCEPTION":
            continue
        code = result.exception_code or "I-PARTIAL"
        exc = ReconciliationException(
            run_id=run.run_id,
            tenant_id=tenant_id,
            exception_code=code,
            severity=_severity_for(code),
            status="OPEN",
            title=_title_for(code),
            description=(
                f"Invoice {link.invoice_id} vs charge {link.charge_id}: {result.outcome.value}"
            ),
            evidence_refs=[link.invoice_id, link.charge_id],
        )
        session.add(exc)

    # Exceptions: from payout allocations
    for deposit in getattr(report, "deposits", ()):
        allocation = deposit.allocation
        if allocation.outcome.value not in ("EXCEPTION", "PENDING_EVIDENCE", "REQUIRES_HUMAN"):
            continue
        code = allocation.exception_code.value if allocation.exception_code else "I-PAYOUT"
        if code not in ("I-REFUND-LAG", "I-FEE-DRIFT", "I-DUPLICATE", "I-PARTIAL", "I-PAYOUT"):
            code = "I-PAYOUT"
        exc = ReconciliationException(
            run_id=run.run_id,
            tenant_id=tenant_id,
            exception_code=code,
            severity=_severity_for(code),
            status="OPEN",
            title=_title_for(code),
            description=f"Deposit {deposit.deposit_id}: {allocation.outcome.value}",
            evidence_refs=[deposit.deposit_id],
        )
        session.add(exc)

    run.status = "SUCCEEDED"
    run.completed_at = datetime.now(UTC)
    session.flush()
    return run.run_id


@persist_guarded
def get_run(session: Session, *, run_id: str, tenant_id: str) -> ReconciliationRun | None:
    """Return the run row for this tenant, or None."""
    row = session.get(ReconciliationRun, run_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


@persist_guarded
def list_exceptions(
    session: Session, *, run_id: str, tenant_id: str
) -> list[ReconciliationException]:
    """Return all exceptions for a run within the tenant."""
    return (
        session.query(ReconciliationException)
        .filter(
            ReconciliationException.run_id == run_id,
            ReconciliationException.tenant_id == tenant_id,
        )
        .all()
    )


@persist_guarded
def record_decision(
    session: Session,
    *,
    exception_id: str,
    tenant_id: str,
    actor_id: str,
    decision_type: str,
    reason: str,
    previous_status: str,
    new_status: str,
    evidence_refs: list[str] | None = None,
) -> str:
    """Append a decision, update exception status, and write an audit event.

    Does not commit. The caller commits the transaction.
    """
    exc = session.get(ReconciliationException, exception_id)
    if exc is None or exc.tenant_id != tenant_id:
        raise ValueError(f"Exception {exception_id} not found for tenant {tenant_id}.")
    validate_transition(exc.status, new_status, decision_type)
    decision = ExceptionDecision(
        exception_id=exception_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        decision_type=decision_type,
        reason=reason,
        previous_status=previous_status,
        new_status=new_status,
        evidence_refs=evidence_refs,
    )
    session.add(decision)
    exc.status = new_status
    exc.updated_at = datetime.now(UTC)
    audit = AuditEvent(
        tenant_id=tenant_id,
        entity_type="exception",
        entity_id=exception_id,
        action=f"decision:{decision_type}",
        actor_id=actor_id,
        previous_state=previous_status,
        new_state=new_status,
        metadata={"reason": reason},
    )
    session.add(audit)
    session.flush()
    return decision.decision_id


@persist_guarded
def record_audit_event(
    session: Session,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str | None = None,
    previous_state: str | None = None,
    new_state: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> str:
    """Append an audit event. Does not commit."""
    event = AuditEvent(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        previous_state=previous_state,
        new_state=new_state,
        metadata_=metadata,
        correlation_id=correlation_id,
    )
    session.add(event)
    session.flush()
    return event.event_id


@persist_guarded
def get_audit_events(
    session: Session,
    *,
    tenant_id: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
) -> list[AuditEvent]:
    """Return audit events for this tenant, newest first."""
    query = session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant_id)
    if entity_type is not None:
        query = query.filter(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditEvent.entity_id == entity_id)
    return query.order_by(AuditEvent.created_at.desc()).limit(limit).all()


@persist_guarded
def get_run_exceptions(
    session: Session, *, run_id: str, tenant_id: str
) -> list[ReconciliationException]:
    """Alias for list_exceptions, for API-layer naming consistency."""
    return list_exceptions(session, run_id=run_id, tenant_id=tenant_id)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

# Re-export for callers that need the ORM classes.
__all__ = [
    "AuditEvent",
    "ReconciliationRun",
    "ReconciliationMatch",
    "PayoutAllocation",
    "AllocationLegRow",
    "ReconciliationException",
    "ExceptionDecision",
    "Investigation",
    "ExportArtifact",
    "ImportSession",
    "SourceFile",
    "ImportRow",
    "Tenant",
    "create_import_session",
    "get_import_session",
    "upload_source_file",
    "persist_ingestion_report",
    "start_reconciliation",
    "get_run",
    "list_exceptions",
    "get_run_exceptions",
    "record_decision",
    "record_audit_event",
    "get_audit_events",
]
