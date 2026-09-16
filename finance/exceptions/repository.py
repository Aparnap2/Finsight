"""Atomic compare-and-swap repository for the Exception Aggregate.

Every transition is enforced in persistence with a single predicated
``UPDATE`` (``WHERE exception_id + state_version + state``); zero affected
rows means ``CONCURRENCY_CONFLICT`` — no mutation — plus a mandatory audit
row. A read-then-check-then-write sequence without the atomic guard would
violate the frozen spec, so the guard lives in SQL, not just in Python.

An audit row is appended for every attempt: applied transitions, stale
writes, and illegal moves alike carry actor, attempted transition, and
expected-vs-actual versions.

Only SQLAlchemy plus P1-adjacent domain types are used. This module
imports nothing from ``apps/`` or ``agents/``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.errors import ConcurrencyConflictError, IllegalTransitionError
from finance.exceptions.models import Base, ExceptionAuditRow, ExceptionRow
from finance.exceptions.states import ExceptionState

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for audit rows."""
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Re-attach UTC to naive datetimes coming back from the database."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value


def _row_to_aggregate(row: ExceptionRow) -> ExceptionAggregate:
    """Rehydrate an aggregate snapshot from its persisted row."""
    return ExceptionAggregate(
        exception_id=row.exception_id,
        tenant_id=row.tenant_id,
        reconciliation_result_id=row.reconciliation_result_id,
        exception_type=row.exception_type,
        severity=row.severity,  # type: ignore[arg-type]
        state=row.state,  # type: ignore[arg-type]
        state_version=row.state_version,
        evidence_ids=tuple(row.evidence_ids or []),
        proposal_id=row.proposal_id,
        approval_id=row.approval_id,
        execution_id=row.execution_id,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


class ExceptionRepository:
    """CAS-guarded store over ``exceptions`` plus the append-only audit log.

    The repository owns an engine; each method opens a short session so
    two repository handles over one engine race exactly like two writers
    in production.
    """

    def __init__(self, engine: Engine) -> None:
        """Bind the repository to an engine and ensure tables exist."""
        self._engine = engine
        Base.metadata.create_all(engine)

    def create(self, aggregate: ExceptionAggregate, *, actor: str = "system") -> None:
        """Persist a fresh aggregate exactly once (create-once).

        Raises:
            IllegalTransitionError: If the id (or reconciliation result) exists.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            session.add(
                ExceptionRow(
                    exception_id=aggregate.exception_id,
                    tenant_id=aggregate.tenant_id,
                    reconciliation_result_id=aggregate.reconciliation_result_id,
                    exception_type=aggregate.exception_type.value,
                    severity=aggregate.severity.value,
                    state=aggregate.state.value,
                    state_version=aggregate.state_version,
                    evidence_ids=list(aggregate.evidence_ids),
                    proposal_id=aggregate.proposal_id,
                    approval_id=aggregate.approval_id,
                    execution_id=aggregate.execution_id,
                    created_at=aggregate.created_at,
                    updated_at=aggregate.updated_at,
                )
            )
            session.add(
                ExceptionAuditRow(
                    exception_id=aggregate.exception_id,
                    tenant_id=aggregate.tenant_id,
                    actor=actor,
                    from_state=None,
                    attempted_state=aggregate.state.value,
                    expected_version=aggregate.state_version,
                    actual_version=aggregate.state_version,
                    outcome="CREATED",
                    reason="aggregate created once",
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                logger.warning("duplicate exception create id=%s", aggregate.exception_id)
                raise IllegalTransitionError(
                    aggregate.exception_id,
                    "-",
                    aggregate.state.value,
                    reason="duplicate create: aggregate already exists",
                ) from exc

    def get(self, exception_id: str) -> ExceptionAggregate | None:
        """Read the current snapshot, exposing ``state_version`` for retry.

        Tenant-blind; for tenant-scoped reads use :meth:`get_for_tenant`.
        """
        with Session(self._engine) as session:
            row = session.get(ExceptionRow, exception_id)
            return _row_to_aggregate(row) if row is not None else None

    def get_for_tenant(self, tenant_id: str, exception_id: str) -> ExceptionAggregate | None:
        """Tenant-scoped read — fails closed if tenant does not own the case.

        Returns ``None`` with uniform ``None`` for both missing and
        wrong-tenant (no existential leak, no timing oracle beyond query).
        """
        tid = tenant_id.strip()
        eid = exception_id.strip()
        if not tid or not eid:
            return None
        with Session(self._engine) as session:
            row = (
                session.query(ExceptionRow)
                .filter(ExceptionRow.exception_id == eid, ExceptionRow.tenant_id == tid)
                .one_or_none()
            )
            return _row_to_aggregate(row) if row is not None else None

    def apply(
        self,
        snapshot: ExceptionAggregate,
        target: ExceptionState | str,
        *,
        actor: str = "system",
        evidence_ids: tuple[str, ...] | list[str] | None = None,
        proposal_id: str | None = None,
    ) -> ExceptionAggregate:
        """CAS-apply one transition from a caller-held snapshot.

        The snapshot's ``(state, state_version)`` becomes the SQL
        predicate; the single ``UPDATE`` either advances exactly one row
        or affects zero rows (conflict). Python-side legality is checked
        first for clear illegal-move errors, but the version guard is
        always enforced atomically in SQL.

        Args:
            snapshot: Caller-held pre-transition view (carries expected
                version + state).
            target: Requested next state.
            actor: Caller identity for the audit row.
            evidence_ids: Replacement evidence set (append-only sealed).
            proposal_id: Proposal slot value when entering ``PROPOSED``.

        Returns:
            The post-transition aggregate re-read from the winning row.

        Raises:
            IllegalTransitionError: If the move is banned, unlisted, beyond
                P3.2 scope, or violates slot/seal rules. Audited.
            ConcurrencyConflictError: If the predicated ``UPDATE`` affects
                zero rows (stale version or state). Audited, unmutated.
        """
        target_state = target if isinstance(target, ExceptionState) else ExceptionState(target)
        try:
            plan = snapshot.transition_to(
                target_state,
                snapshot.state_version,
                actor=actor,
                evidence_ids=evidence_ids,
                proposal_id=proposal_id,
            )
        except (IllegalTransitionError, ConcurrencyConflictError) as exc:
            self._audit_rejection(snapshot, target_state.value, actor, str(exc))
            raise
        with Session(self._engine) as session:
            stmt = (
                update(ExceptionRow)
                .where(
                    ExceptionRow.exception_id == snapshot.exception_id,
                    ExceptionRow.tenant_id == snapshot.tenant_id,
                    ExceptionRow.state_version == snapshot.state_version,
                    ExceptionRow.state == snapshot.state.value,
                )
                .values(
                    state=plan.state.value,
                    state_version=ExceptionRow.state_version + 1,
                    evidence_ids=list(plan.evidence_ids),
                    proposal_id=plan.proposal_id,
                    approval_id=plan.approval_id,
                    execution_id=plan.execution_id,
                    updated_at=plan.updated_at,
                )
            )
            result = session.execute(stmt)
            if result.rowcount == 1:
                session.add(
                    ExceptionAuditRow(
                        exception_id=snapshot.exception_id,
                        tenant_id=snapshot.tenant_id,
                        actor=actor,
                        from_state=snapshot.state.value,
                        attempted_state=plan.state.value,
                        expected_version=snapshot.state_version,
                        actual_version=plan.state_version,
                        outcome="APPLIED",
                        reason=f"{snapshot.state.value} -> {plan.state.value}",
                        created_at=_utcnow(),
                    )
                )
                session.commit()
                logger.info(
                    "exception CAS applied id=%s %s -> %s v=%s",
                    snapshot.exception_id,
                    snapshot.state.value,
                    plan.state.value,
                    plan.state_version,
                )
            else:
                session.rollback()
                current = self.get(snapshot.exception_id)
                actual_version = current.state_version if current else -1
                self._audit_rejection(
                    snapshot,
                    target_state.value,
                    actor,
                    f"CONCURRENCY_CONFLICT expected={snapshot.state_version} "
                    f"actual={actual_version}",
                    actual_version=actual_version,
                )
                raise ConcurrencyConflictError(
                    snapshot.exception_id,
                    snapshot.state_version,
                    actual_version,
                    detail="atomic CAS UPDATE affected 0 rows",
                )
        refreshed = self.get(snapshot.exception_id)
        if refreshed is None:  # pragma: no cover - defensive, row just won CAS
            raise ConcurrencyConflictError(
                snapshot.exception_id,
                snapshot.state_version,
                -1,
                detail="row vanished after winning CAS",
            )
        return refreshed

    def audit_trail(self, exception_id: str) -> list[ExceptionAuditRow]:
        """Return the ordered audit rows for one aggregate (oldest first)."""
        with Session(self._engine) as session:
            rows = (
                session.query(ExceptionAuditRow)
                .filter(ExceptionAuditRow.exception_id == exception_id)
                .order_by(ExceptionAuditRow.id.asc())
                .all()
            )
            return list(rows)

    def _audit_rejection(
        self,
        snapshot: ExceptionAggregate,
        attempted_state: str,
        actor: str,
        reason: str,
        *,
        actual_version: int | None = None,
    ) -> None:
        """Append a rejection audit row without mutating the aggregate row."""
        with Session(self._engine) as session:
            session.add(
                ExceptionAuditRow(
                    exception_id=snapshot.exception_id,
                    tenant_id=snapshot.tenant_id,
                    actor=actor,
                    from_state=snapshot.state.value,
                    attempted_state=attempted_state,
                    expected_version=snapshot.state_version,
                    actual_version=(
                        actual_version if actual_version is not None else snapshot.state_version
                    ),
                    outcome="REJECTED",
                    reason=reason,
                    created_at=_utcnow(),
                )
            )
            session.commit()


def new_exception_id() -> str:
    """Mint a random aggregate identity (hex UUID)."""
    return uuid.uuid4().hex
