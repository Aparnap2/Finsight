"""Leased outbox publisher: PostgreSQL claims to SQS (issue #113).

Bounded publishing with PostgreSQL-backed leases. Claims use
``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent publishers fence
correctly; a claim sets ``leased_until`` and bumps ``attempts``.
Expired leases become claimable again (recovery). Publication may
succeed while recording success fails — the consumer's idempotency
absorbs the resulting duplicate, never a second outbox row.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from shared.models.database import OutboxRow

logger = logging.getLogger(__name__)


class Publisher:
    """Claim due outbox rows and publish them through an injected sender."""

    def __init__(
        self,
        engine: Any,
        sender: Callable[[OutboxRow], None],
        lease_seconds: int = 300,
    ) -> None:
        """Bind to ``engine`` with a ``sender`` (SQS in prod, stub in tests)."""
        self._engine = engine
        self._sender = sender
        self._lease_seconds = lease_seconds

    def claim_due(self, limit: int = 10) -> list[OutboxRow]:
        """Atomically claim up to ``limit`` due rows (PENDING, lease free)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        with Session(self._engine) as session:
            ids = (
                session.execute(
                    select(OutboxRow.id)
                    .where(
                        OutboxRow.status == "PENDING",
                        (OutboxRow.leased_until.is_(None))
                        | (OutboxRow.leased_until < now),
                    )
                    .order_by(OutboxRow.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            if not ids:
                return []
            leased_until = now + timedelta(seconds=self._lease_seconds)
            session.execute(
                update(OutboxRow)
                .where(OutboxRow.id.in_(ids))
                .values(leased_until=leased_until, attempts=OutboxRow.attempts + 1)
            )
            session.commit()
            rows = (
                session.execute(select(OutboxRow).where(OutboxRow.id.in_(ids)))
                .scalars()
                .all()
            )
            for row in rows:
                session.expunge(row)
            return list(rows)

    def publish(self, row: OutboxRow) -> None:
        """Send one claimed row; mark PUBLISHED only after sender returns."""
        self._sender(row)
        with Session(self._engine) as session:
            session.execute(
                update(OutboxRow)
                .where(OutboxRow.id == row.id)
                .values(
                    status="PUBLISHED",
                    published_at=datetime.now(UTC).replace(tzinfo=None),
                    leased_until=None,
                    last_error=None,
                )
            )
            session.commit()

    def fail(self, row: OutboxRow, error: str) -> None:
        """Record a publish failure; the row stays PENDING for redelivery."""
        with Session(self._engine) as session:
            session.execute(
                update(OutboxRow)
                .where(OutboxRow.id == row.id)
                .values(last_error=error[:500], leased_until=None)
            )
            session.commit()
