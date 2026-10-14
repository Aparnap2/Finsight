"""Idempotent outbox consumer boundary (issue #113).

The consumer runs the downstream effect through an injected
``execute`` callable and records the execution id on the outbox row.
Redelivery replays the recorded outcome instead of re-executing:
the same outbox id maps to the same execution id, and the effect
callable runs at most once per outbox row. SQS delivery or
acknowledgement is never treated as proof of financial execution —
only the recorded execution id counts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from shared.models.database import OutboxRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsumeResult:
    """Outcome of one consume attempt (durable, replayable)."""

    consumed: bool
    deduplicated: bool
    execution_id: str | None


def consume_once(engine: Any, outbox_id: str, execute: Callable[[], str | None]) -> ConsumeResult:
    """Consume one outbox row exactly once per row id.

    ``execute`` performs the downstream effect and returns the
    execution id (or None when it produced none). On redelivery the
    recorded execution id is returned with ``deduplicated=True`` and
    ``execute`` is NOT called again.
    """
    with Session(engine) as session:
        row = session.get(OutboxRow, outbox_id)
        if row is None:
            raise ValueError(f"Unknown outbox row: {outbox_id}")
        if row.consumed_at is not None:
            recorded = row.execution_id
            return ConsumeResult(
                consumed=True,
                deduplicated=True,
                execution_id=str(recorded) if recorded is not None else None,
            )
        execution_id = execute()
        # Atomic consume: only the winner flips NULL -> timestamp. A
        # racing redelivery sees consumed_at set and replays instead.
        won = session.execute(
            update(OutboxRow)
            .where(OutboxRow.id == outbox_id, OutboxRow.consumed_at.is_(None))
            .values(
                consumed_at=datetime.now(UTC).replace(tzinfo=None),
                status="CONSUMED",
                execution_id=execution_id,
            )
        ).rowcount
        session.commit()
        if not won:
            replayed = session.get(OutboxRow, outbox_id)
            assert replayed is not None
            recorded = replayed.execution_id
            return ConsumeResult(
                consumed=True,
                deduplicated=True,
                execution_id=str(recorded) if recorded is not None else None,
            )
        return ConsumeResult(consumed=True, deduplicated=False, execution_id=execution_id)
