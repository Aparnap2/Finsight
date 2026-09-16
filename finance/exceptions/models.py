"""SQLAlchemy persistence models for the Exception Aggregate boundary.

``ExceptionRow`` stores the 12 spec slots (``created_at``/``updated_at``
share one slot family); ``ExceptionAuditRow`` is the append-only trail —
one row per applied transition and per rejection (stale version, illegal
move, bypass attempt). Money never appears on these rows, so no
``Decimal`` handling is needed here.

A local ``DeclarativeBase`` keeps P3.2 storage decoupled from the shared
database catalogue; table names are namespaced under ``exceptions*``.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for row defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Local declarative base for P3.2 exception tables."""


class ExceptionRow(Base):
    """Persisted projection of one :class:`ExceptionAggregate` snapshot."""

    __tablename__ = "exceptions"
    __table_args__ = (
        UniqueConstraint("reconciliation_result_id", name="uq_exceptions_recon_result_once"),
        # Composite covering index for tenant-scoped lookups (P5-03 #2 tenant→case)
        # and RLS `tenant_id = current_setting('app.tenant_id')` scans.
        # Keep single-column `tenant_id` index for wide scans.
        UniqueConstraint("tenant_id", "exception_id", name="uq_exceptions_tenant_exception_once"),
    )

    exception_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reconciliation_result_id: Mapped[str] = mapped_column(String, nullable=False)
    exception_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ExceptionAuditRow(Base):
    """One immutable audit fact per transition attempt (applied or rejected)."""

    __tablename__ = "exception_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exception_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String, nullable=False, default="system")
    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    attempted_state: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
