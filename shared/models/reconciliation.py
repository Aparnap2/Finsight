"""SQLAlchemy ORM models for the reconciliation domain.

One local ``DeclarativeBase`` keeps reconciliation storage decoupled from
the shared FP&A catalogue (which is a Slice 8 deletion target) and from the
exception/execution aggregates. Every model maps to a concrete entity in
``docs/specs/DOMAIN_MODEL.md`` §2 and a table in
``docs/specs/DATABASE_SCHEMA.md`` §3.

Tenant isolation is enforced at two levels: application-level ``tenant_id``
filters and PostgreSQL Row-Level Security on every tenant-scoped table. The
middleware sets ``app.tenant_id`` per request (see
``apps/api/middleware.py``).

Money columns use ``Numeric(19, 4)`` to carry the 4-decimal minor-unit values
the reconciliation engine emits; ``Decimal`` arithmetic is preserved end to
end. JSON columns use the portable ``JSON`` type (rendered as ``JSONB`` in the
Postgres migration).

Only SQLAlchemy plus the Python standard library are used.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for row defaults."""
    return datetime.now(UTC)


def _new_uuid() -> str:
    """Return a new UUID4 string for primary keys."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Local declarative base for reconciliation tables."""


class Tenant(Base):
    """A tenant (root of all data ownership)."""

    __tablename__ = "reconciliation_tenants"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="ck_tenants_status"),
    )


class ImportSession(Base):
    """Groups the three source imports for one reconciliation period."""

    __tablename__ = "import_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    period_start: Mapped[Any] = mapped_column(Date, nullable=False)
    period_end: Mapped[Any] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED', 'UPLOADING', 'VALIDATING', 'READY', 'REJECTED')",
            name="ck_import_sessions_status",
        ),
        CheckConstraint("period_end >= period_start", name="ck_import_sessions_period"),
        Index("idx_import_sessions_tenant", "tenant_id"),
        Index("idx_import_sessions_status", "status"),
    )


class SourceFile(Base):
    """One uploaded source file belonging to an import session."""

    __tablename__ = "source_files"

    file_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("import_sessions.session_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('INVOICE', 'STRIPE', 'BANK')", name="ck_source_files_type"
        ),
        CheckConstraint("file_size_bytes > 0", name="ck_source_files_size"),
        CheckConstraint("row_count >= 0", name="ck_source_files_rows"),
        UniqueConstraint("session_id", "source_type", name="uq_source_files_session_type"),
        UniqueConstraint(
            "tenant_id", "source_type", "content_hash", name="uq_source_files_tenant_type_hash"
        ),
        Index("idx_source_files_tenant", "tenant_id"),
        Index("idx_source_files_session", "session_id"),
    )


class ImportRow(Base):
    """One normalized source record from an uploaded file."""

    __tablename__ = "import_rows"

    row_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_files.file_id"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("import_sessions.session_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(10), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint("validation_status IN ('VALID', 'INVALID')", name="ck_import_rows_status"),
        CheckConstraint("line_number >= 1", name="ck_import_rows_line"),
        Index("idx_import_rows_file", "file_id"),
        Index("idx_import_rows_session", "session_id"),
        Index("idx_import_rows_tenant", "tenant_id"),
        Index("idx_import_rows_validation", "validation_status"),
    )


class ReconciliationRun(Base):
    """A durable execution of the reconciliation engine on one import session."""

    __tablename__ = "reconciliation_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("import_sessions.session_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'VALIDATING', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_reconciliation_runs_status",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_reconciliation_runs_tenant_key"),
        Index("idx_reconciliation_runs_tenant", "tenant_id"),
        Index("idx_reconciliation_runs_session", "session_id"),
        Index("idx_reconciliation_runs_status", "status"),
        Index("idx_reconciliation_runs_created", "created_at"),
    )


class ReconciliationMatch(Base):
    """Deterministic match between an invoice and a charge."""

    __tablename__ = "reconciliation_matches"

    match_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_runs.run_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    invoice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    charge_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    observed_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    variance: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    tolerance_applied: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exception_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    materiality: Mapped[str] = mapped_column(String(12), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('MATCHED', 'TOLERANCE_MATCHED', 'EXCEPTION', 'PENDING_EVIDENCE')",
            name="ck_reconciliation_matches_outcome",
        ),
        CheckConstraint("expected_amount >= 0", name="ck_reconciliation_matches_expected"),
        CheckConstraint("observed_amount >= 0", name="ck_reconciliation_matches_observed"),
        CheckConstraint("variance >= 0", name="ck_reconciliation_matches_variance"),
        CheckConstraint("tolerance_applied >= 0", name="ck_reconciliation_matches_tolerance"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_reconciliation_matches_currency"),
        CheckConstraint(
            "materiality IN ('MATERIAL', 'IMMATERIAL')",
            name="ck_reconciliation_matches_materiality",
        ),
        CheckConstraint(
            "(outcome != 'EXCEPTION' OR exception_code IS NOT NULL) AND "
            "(outcome = 'EXCEPTION' OR exception_code IS NULL)",
            name="ck_reconciliation_matches_exception_code",
        ),
        Index("idx_reconciliation_matches_run", "run_id"),
        Index("idx_reconciliation_matches_tenant", "tenant_id"),
        Index("idx_reconciliation_matches_invoice", "invoice_id"),
        Index("idx_reconciliation_matches_charge", "charge_id"),
    )


class PayoutAllocation(Base):
    """Allocation of a bank deposit to one or more charges."""

    __tablename__ = "payout_allocations"

    allocation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_runs.run_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    deposit_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    allocated_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    eligible_net_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    open_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    unallocated_deposit: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    fee_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    refund_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    exception_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('MATCHED', 'TOLERANCE_MATCHED', 'EXCEPTION', "
            "'PENDING_EVIDENCE', 'REQUIRES_HUMAN')",
            name="ck_payout_allocations_outcome",
        ),
        CheckConstraint("allocated_total >= 0", name="ck_payout_allocations_allocated"),
        CheckConstraint("eligible_net_total >= 0", name="ck_payout_allocations_eligible"),
        CheckConstraint("open_balance >= 0", name="ck_payout_allocations_open"),
        CheckConstraint("unallocated_deposit >= 0", name="ck_payout_allocations_unallocated"),
        CheckConstraint("fee_total >= 0", name="ck_payout_allocations_fee"),
        CheckConstraint("refund_total >= 0", name="ck_payout_allocations_refund"),
        CheckConstraint(
            "(outcome != 'EXCEPTION' OR exception_code IS NOT NULL) AND "
            "(outcome = 'EXCEPTION' OR exception_code IS NULL)",
            name="ck_payout_allocations_exception_code",
        ),
        Index("idx_payout_allocations_run", "run_id"),
        Index("idx_payout_allocations_tenant", "tenant_id"),
        Index("idx_payout_allocations_deposit", "deposit_id"),
    )


class AllocationLeg(Base):
    """One leg of a payout allocation."""

    __tablename__ = "allocation_legs"

    leg_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    allocation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payout_allocations.allocation_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gross: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    refund: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    net: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    allocated: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("gross >= 0", name="ck_allocation_legs_gross"),
        CheckConstraint("fee >= 0", name="ck_allocation_legs_fee"),
        CheckConstraint("refund >= 0", name="ck_allocation_legs_refund"),
        CheckConstraint("allocated > 0", name="ck_allocation_legs_allocated"),
        CheckConstraint("net = gross - fee - refund", name="ck_allocation_legs_net"),
        CheckConstraint("allocated <= net", name="ck_allocation_legs_allocated_le_net"),
        Index("idx_allocation_legs_allocation", "allocation_id"),
        Index("idx_allocation_legs_tenant", "tenant_id"),
        Index("idx_allocation_legs_payment", "payment_id"),
    )


class ReconciliationException(Base):
    """An unresolved discrepancy requiring human attention."""

    __tablename__ = "reconciliation_exceptions"

    exception_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_runs.run_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    exception_code: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')",
            name="ck_reconciliation_exceptions_severity",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'INVESTIGATING', 'UNDER_REVIEW', 'RESOLVED', 'REOPENED')",
            name="ck_reconciliation_exceptions_status",
        ),
        Index("idx_reconciliation_exceptions_run", "run_id"),
        Index("idx_reconciliation_exceptions_tenant", "tenant_id"),
        Index("idx_reconciliation_exceptions_status", "status"),
        Index("idx_reconciliation_exceptions_severity", "severity"),
    )


class ExceptionDecision(Base):
    """Append-only record of a human decision on an exception."""

    __tablename__ = "exception_decisions"

    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    exception_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_exceptions.exception_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "decision_type IN ('APPROVE', 'REJECT', 'REOPEN', 'ASSIGN')",
            name="ck_exception_decisions_type",
        ),
        Index("idx_exception_decisions_exception", "exception_id"),
        Index("idx_exception_decisions_tenant", "tenant_id"),
        Index("idx_exception_decisions_decided", "decided_at"),
    )


class Investigation(Base):
    """AI investigation of an exception."""

    __tablename__ = "investigations"

    investigation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    exception_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_exceptions.exception_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_investigations_status",
        ),
        Index("idx_investigations_exception", "exception_id"),
        Index("idx_investigations_tenant", "tenant_id"),
        Index("idx_investigations_status", "status"),
    )


class AuditEvent(Base):
    """Append-only audit event for consequential state changes."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("idx_audit_events_tenant", "tenant_id"),
        Index("idx_audit_events_entity", "entity_type", "entity_id"),
        Index("idx_audit_events_created", "created_at"),
        Index("idx_audit_events_correlation", "correlation_id"),
    )


class ExportArtifact(Base):
    """A generated export artifact for a reconciliation run."""

    __tablename__ = "export_artifacts"

    export_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_runs.run_id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_tenants.tenant_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'GENERATING', 'COMPLETED', 'FAILED')",
            name="ck_export_artifacts_status",
        ),
        CheckConstraint("format IN ('CSV', 'JSON', 'MARKDOWN')", name="ck_export_artifacts_format"),
        Index("idx_export_artifacts_run", "run_id"),
        Index("idx_export_artifacts_tenant", "tenant_id"),
        Index("idx_export_artifacts_status", "status"),
    )
