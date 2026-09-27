"""Postgres-backed durable run store behind the frozen P8-03 seam.

Persists the frozen P8-03 durable projection (``agents/p8_runtime/durability.py``)
as opaque canonical JSON: runs, ordered attempts, audit entries, quarantine flags.
This module imports only SQLAlchemy plus the standard library — never
``agents/`` or ``apps/`` — so the layered-architecture rules hold.

Semantic authority stays with the frozen durability functions: callers build
payloads from ``durability.snapshot()``, seal with ``durability.seal_fields``,
verify with ``durability.verify_seal``, and recover through
``durability.recover_run``/``resubmit``/``replay_durable``. This store is a
dumb durable byte-box: it upserts run snapshots, INSERTs audit rows (never
UPDATEs or DELETEs them — append-only), and flags quarantine. No provider
calls, no LLM, no authority minting.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Engine, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Local declarative base keeping P8 durability storage decoupled."""


class RunStateRow(Base):
    """One durable run snapshot keyed by the frozen ``RunIdentity``."""

    __tablename__ = "p8_run_states"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    input_fingerprint: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    terminal_state: Mapped[str] = mapped_column(String, nullable=False, default="")
    budget_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    integrity_seal: Mapped[str] = mapped_column(String, nullable=False)
    quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RunAuditRow(Base):
    """One append-only recovery/provenance event for a run identity."""

    __tablename__ = "p8_run_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    input_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PostgresDurableRunStore:
    """Durable byte-box for frozen P8-03 snapshots over one database.

    Each method opens short sessions so fresh handles observe committed
    state (crash-resume). Audit rows are INSERT-only: this class exposes
    no update or delete path for them.
    """

    def __init__(self, engine: Engine) -> None:
        """Bind the store to an engine and ensure its tables exist."""
        self._engine = engine
        Base.metadata.create_all(engine)

    def save_snapshot(
        self,
        *,
        run_id: str,
        input_fingerprint: str,
        scope: str,
        attempts: list[dict[str, Any]],
        terminal_state: str,
        budget_usage: dict[str, Any],
        integrity_seal: str,
    ) -> None:
        """Upsert one durable snapshot; same identity converges, never forks."""
        stmt = insert(RunStateRow).values(
            run_id=run_id,
            input_fingerprint=input_fingerprint,
            scope=scope,
            attempts=attempts,
            terminal_state=terminal_state,
            budget_usage=budget_usage,
            integrity_seal=integrity_seal,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id", "input_fingerprint"],
            set_={
                "scope": stmt.excluded.scope,
                "attempts": stmt.excluded.attempts,
                "terminal_state": stmt.excluded.terminal_state,
                "budget_usage": stmt.excluded.budget_usage,
                "integrity_seal": stmt.excluded.integrity_seal,
            },
        )
        with Session(self._engine) as session:
            session.execute(stmt)
            session.commit()
        logger.info("p8 durable snapshot saved run=%s.", run_id)

    def load_snapshot(self, run_id: str, input_fingerprint: str) -> dict[str, Any] | None:
        """Return the persisted snapshot dict, or None when unrecorded."""
        with Session(self._engine) as session:
            row = session.get(RunStateRow, (run_id, input_fingerprint))
            if row is None:
                return None
            return {
                "run_id": row.run_id,
                "input_fingerprint": row.input_fingerprint,
                "scope": row.scope,
                "attempts": list(row.attempts),
                "terminal_state": row.terminal_state,
                "budget_usage": dict(row.budget_usage),
                "integrity_seal": row.integrity_seal,
                "quarantined": row.quarantined,
            }

    def append_audit(self, run_id: str, input_fingerprint: str, event: str) -> None:
        """Append one audit entry; recorded entries are never mutated."""
        with Session(self._engine) as session:
            session.add(
                RunAuditRow(
                    run_id=run_id,
                    input_fingerprint=input_fingerprint,
                    event=event,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

    def audit_entries(self, run_id: str, input_fingerprint: str) -> list[str]:
        """Return audit events oldest-first for one identity."""
        with Session(self._engine) as session:
            rows = (
                session.execute(
                    select(RunAuditRow.event)
                    .where(
                        RunAuditRow.run_id == run_id,
                        RunAuditRow.input_fingerprint == input_fingerprint,
                    )
                    .order_by(RunAuditRow.id.asc())
                )
                .scalars()
                .all()
            )
            return list(rows)

    def set_quarantined(self, run_id: str, input_fingerprint: str) -> None:
        """Flag a run quarantined; persists pending human review."""
        with Session(self._engine) as session:
            row = session.get(RunStateRow, (run_id, input_fingerprint))
            if row is None:
                return
            row.quarantined = True
            session.commit()
        logger.info("p8 run quarantined run=%s.", run_id)

    def is_quarantined(self, run_id: str, input_fingerprint: str) -> bool:
        """Report whether a run is quarantined (non-executable)."""
        snapshot = self.load_snapshot(run_id, input_fingerprint)
        return bool(snapshot and snapshot["quarantined"])

    def run_row_count(self, run_id: str, input_fingerprint: str) -> int:
        """Count state rows for one identity (idempotency: always 0 or 1)."""
        with Session(self._engine) as session:
            row = session.get(RunStateRow, (run_id, input_fingerprint))
            return 1 if row is not None else 0
