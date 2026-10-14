"""Idempotent outbox consumer boundary (issue #113).

Claim-first protocol (review finding 2): the durable claim happens
BEFORE the effect executes, and crash recovery distinguishes
"definitely did not happen" from "outcome unknown":

- PENDING (or expired lease, no execution recorded) → atomically
  claim → execute → record execution (CONSUMED). Only the claim
  winner executes.
- CLAIMED with a live lease → another worker is active: redrive
  (return ``busy=True``), never execute twice.
- CLAIMED with an expired lease and no recorded execution → the
  previous worker may or may not have executed: outcome UNKNOWN.
  The consumer does NOT blindly re-execute; it calls the injected
  ``reconcile`` hook (reconcile-against-source, then record), or
  returns ``needs_reconciliation=True`` when no hook is configured.
- CONSUMED → replay the recorded execution id, never re-execute.

SQS delivery or acknowledgement is never proof of financial
execution — only the recorded execution id counts.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from shared.models.database import OutboxRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConsumeResult:
    """Outcome of one consume attempt (durable, replayable)."""

    consumed: bool
    deduplicated: bool
    busy: bool = False
    needs_reconciliation: bool = False
    execution_id: str | None = None


def consume_once(
    engine: Any,
    outbox_id: str,
    execute: Callable[[], str | None],
    reconcile: Callable[[], str | None] | None = None,
    lease_seconds: int = 300,
) -> ConsumeResult:
    """Consume one outbox row under the claim-first protocol."""
    if engine is None:
        raise ValueError("Consumer requires a durable engine, got None.")
    now = datetime.now(UTC).replace(tzinfo=None)
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
        # ORM attributes type as Columns; read plain values for branching.
        status = str(row.status)
        leased_until = row.leased_until
        recorded_exec = row.execution_id
        lease_live = leased_until is not None and leased_until > now
        if status == "CLAIMED" and lease_live and recorded_exec is None:
            return ConsumeResult(consumed=False, deduplicated=False, busy=True)
        if status == "CLAIMED" and not lease_live and recorded_exec is None:
            # Previous claimant may have executed with an unrecorded
            # outcome: never blindly re-execute.
            if reconcile is None:
                logger.warning("unreconciled claim requires operator: %s", outbox_id)
                return ConsumeResult(consumed=False, deduplicated=False, needs_reconciliation=True)
            execution_id = reconcile()
            if execution_id is None:
                # Still unknown: leave the row for the operator, do NOT
                # record a false outcome and do NOT re-execute.
                return ConsumeResult(consumed=False, deduplicated=False, needs_reconciliation=True)
            _record(session, outbox_id, execution_id)
            session.commit()
            return ConsumeResult(consumed=True, deduplicated=True, execution_id=execution_id)
        token = f"consume_{uuid.uuid4().hex[:16]}"
        won = session.execute(
            update(OutboxRow)
            .where(
                OutboxRow.id == outbox_id,
                OutboxRow.status == "PENDING",
                (OutboxRow.leased_until.is_(None)) | (OutboxRow.leased_until < now),
            )
            .values(
                status="CLAIMED",
                claim_token=token,
                leased_until=now + timedelta(seconds=lease_seconds),
                attempts=OutboxRow.attempts + 1,
            )
        ).rowcount
        session.commit()
        if not won:
            return ConsumeResult(consumed=False, deduplicated=False, busy=True)
        execution_id = execute()
        _record(session, outbox_id, execution_id)
        session.commit()
        return ConsumeResult(consumed=True, deduplicated=False, execution_id=execution_id)


def _record(session: Session, outbox_id: str, execution_id: str | None) -> None:
    """Record the execution outcome on a claimed row."""
    session.execute(
        update(OutboxRow)
        .where(OutboxRow.id == outbox_id)
        .values(
            consumed_at=datetime.now(UTC).replace(tzinfo=None),
            status="CONSUMED",
            execution_id=execution_id,
            leased_until=None,
            claim_token=None,
        )
    )
