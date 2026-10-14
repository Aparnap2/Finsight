"""Leased outbox publisher: PostgreSQL claims to SQS (issue #113).

Bounded publishing with PostgreSQL-backed leases and claim fencing:

- ``claim_due`` moves PENDING-or-expired rows to CLAIMED with a fresh
  per-claim token, lease, and ``attempts + 1`` (SKIP LOCKED fencing).
  Rows at ``max_attempts`` transition to TERMINAL instead — bounded
  retries, no rapid loops.
- ``publish``/``fail`` are conditional on the claim token: a worker
  whose lease expired cannot mutate the reclaiming worker's claim
  (stale publish returns False; the row stays with its new owner).
- ``fail`` stores sanitized failure metadata (PII-redacted, 500 chars)
  and releases the lease for redelivery within the attempt budget.
- Publication may succeed while recording success fails — the
  consumer's idempotency absorbs the duplicate, never a second row.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from shared.models.database import OutboxRow
from shared.tracing.redaction import redact_pii

logger = logging.getLogger(__name__)

#: Terminal state: attempts exhausted, awaiting operator — never auto-retried.
STATUS_TERMINAL = "TERMINAL"


class Publisher:
    """Claim due outbox rows and publish them through an injected sender."""

    def __init__(
        self,
        engine: Any,
        sender: Callable[[OutboxRow], None],
        lease_seconds: int = 300,
        max_attempts: int = 5,
    ) -> None:
        """Bind to ``engine`` with a ``sender`` (SQS in prod, stub in tests)."""
        if engine is None:
            raise ValueError("Publisher requires a durable engine, got None.")
        self._engine = engine
        self._sender = sender
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    def claim_due(self, limit: int = 10) -> list[OutboxRow]:
        """Atomically claim due rows; retire exhausted ones to TERMINAL."""
        now = datetime.now(UTC).replace(tzinfo=None)
        with Session(self._engine) as session:
            session.execute(
                update(OutboxRow)
                .where(
                    OutboxRow.status.in_(["PENDING", "CLAIMED"]),
                    OutboxRow.attempts >= self._max_attempts,
                    (OutboxRow.leased_until.is_(None)) | (OutboxRow.leased_until < now),
                )
                .values(status=STATUS_TERMINAL, leased_until=None, claim_token=None)
            )
            ids = (
                session.execute(
                    select(OutboxRow.id)
                    .where(
                        OutboxRow.status.in_(["PENDING", "CLAIMED"]),
                        OutboxRow.attempts < self._max_attempts,
                        (OutboxRow.leased_until.is_(None)) | (OutboxRow.leased_until < now),
                    )
                    .order_by(OutboxRow.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            if not ids:
                session.commit()
                return []
            token = f"claim_{uuid.uuid4().hex[:16]}"
            leased_until = now + timedelta(seconds=self._lease_seconds)
            session.execute(
                update(OutboxRow)
                .where(OutboxRow.id.in_(ids))
                .values(
                    status="CLAIMED",
                    claim_token=token,
                    leased_until=leased_until,
                    attempts=OutboxRow.attempts + 1,
                )
            )
            session.commit()
            rows = session.execute(select(OutboxRow).where(OutboxRow.id.in_(ids))).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def publish(self, row: OutboxRow) -> bool:
        """Send one claimed row; mark PUBLISHED only after sender returns.

        Fenced on the claim token: returns False (row untouched) when
        this worker no longer owns the claim.
        """
        self._sender(row)
        with Session(self._engine) as session:
            won = session.execute(
                update(OutboxRow)
                .where(
                    OutboxRow.id == row.id,
                    OutboxRow.status == "CLAIMED",
                    OutboxRow.claim_token == str(row.claim_token),
                )
                .values(
                    status="PUBLISHED",
                    published_at=datetime.now(UTC).replace(tzinfo=None),
                    leased_until=None,
                    claim_token=None,
                    last_error=None,
                )
            ).rowcount  # type: ignore[attr-defined]  # SQLAlchemy returns CursorResult at runtime
            session.commit()
            if not won:
                logger.warning("stale publish refused (claim superseded)")
            return bool(won)

    def fail(self, row: OutboxRow, error: str) -> bool:
        """Record a sanitized failure; release the lease for redelivery.

        Fenced on the claim token like publish. Returns False when this
        worker no longer owns the claim.
        """
        with Session(self._engine) as session:
            won = session.execute(
                update(OutboxRow)
                .where(
                    OutboxRow.id == row.id,
                    OutboxRow.status == "CLAIMED",
                    OutboxRow.claim_token == str(row.claim_token),
                )
                .values(
                    status="PENDING",
                    last_error=redact_pii(error)[:500],
                    leased_until=None,
                    claim_token=None,
                )
            ).rowcount  # type: ignore[attr-defined]  # SQLAlchemy returns CursorResult at runtime
            session.commit()
            return bool(won)
