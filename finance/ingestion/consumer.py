"""Idempotent outbox consumer boundary (issue #113).

Unified lifecycle with the publisher: PENDING → CLAIMED[publisher] →
PUBLISHED → CONSUMING[consumer] → CONSUMED (+ TERMINAL dead-end).

Claim-first protocol (review finding 2): the durable consumer claim
happens BEFORE the effect executes, and crash recovery distinguishes
"definitely did not happen" from "outcome unknown":

- PUBLISHED (lease free) → atomically claim → execute → fenced
  record. Only the claim winner executes.
- CONSUMING with a live lease → another worker is active: redrive
  (``busy=True``), never execute twice.
- CONSUMING with an expired lease and no recorded execution → the
  previous worker may or may not have executed: outcome UNKNOWN.
  Never blindly re-execute; call the injected ``reconcile`` hook, or
  return ``needs_reconciliation=True`` when unconfigured.
- CONSUMED → replay the recorded execution id, never re-execute.

Completion and reconciliation writes are fenced on the consumer claim
token (review finding): a superseded worker cannot overwrite a newer
outcome. SQS delivery or acknowledgement is never proof of financial
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
        # ORM attributes type as Columns; read plain values for branching.
        status = str(row.status)
        leased_until = row.leased_until
        recorded_exec = row.execution_id
        if row.consumed_at is not None:
            return ConsumeResult(
                consumed=True,
                deduplicated=True,
                execution_id=str(recorded_exec) if recorded_exec is not None else None,
            )
        lease_live = leased_until is not None and leased_until > now
        if status == "CONSUMING" and lease_live and recorded_exec is None:
            return ConsumeResult(consumed=False, deduplicated=False, busy=True)
        if status == "CONSUMING" and not lease_live and recorded_exec is None:
            # Previous claimant may have executed with an unrecorded
            # outcome: never blindly re-execute. First acquire an
            # EXCLUSIVE reconciliation claim (fenced on the observed
            # token, so exactly one worker runs the hook); only the
            # winner invokes reconcile(), and completion is fenced on
            # the winner's token.
            if reconcile is None:
                logger.warning("unreconciled claim requires operator: %s", outbox_id)
                return ConsumeResult(consumed=False, deduplicated=False, needs_reconciliation=True)
            observed_token = _token_of(session, outbox_id)
            retoken = f"rec_{uuid.uuid4().hex[:16]}"
            acquired = session.execute(
                update(OutboxRow)
                .where(
                    OutboxRow.id == outbox_id,
                    OutboxRow.status == "CONSUMING",
                    OutboxRow.claim_token == observed_token,
                    OutboxRow.leased_until < now,
                    OutboxRow.execution_id.is_(None),
                )
                .values(
                    claim_token=retoken,
                    leased_until=now + timedelta(seconds=lease_seconds),
                )
            ).rowcount
            session.commit()
            if not acquired:
                return ConsumeResult(consumed=False, deduplicated=False, busy=True)
            execution_id = reconcile()
            if execution_id is None:
                # Still unknown: leave the row for the operator, do NOT
                # record a false outcome and do NOT re-execute.
                return ConsumeResult(consumed=False, deduplicated=False, needs_reconciliation=True)
            if _record(session, outbox_id, retoken, execution_id):
                session.commit()
                return ConsumeResult(consumed=True, deduplicated=True, execution_id=execution_id)
            return ConsumeResult(consumed=False, deduplicated=False, busy=True)
        token = f"con_{uuid.uuid4().hex[:16]}"
        won = session.execute(
            update(OutboxRow)
            .where(
                OutboxRow.id == outbox_id,
                OutboxRow.status == "PUBLISHED",
                (OutboxRow.leased_until.is_(None)) | (OutboxRow.leased_until < now),
            )
            .values(
                status="CONSUMING",
                claimed_by="consumer",
                claim_token=token,
                leased_until=now + timedelta(seconds=lease_seconds),
            )
        ).rowcount
        session.commit()
        if not won:
            return ConsumeResult(consumed=False, deduplicated=False, busy=True)
        execution_id = execute()
        if _record(session, outbox_id, token, execution_id):
            session.commit()
            return ConsumeResult(consumed=True, deduplicated=False, execution_id=execution_id)
        # Lost the claim mid-execution (superseded): the recorded outcome
        # belongs to the newer owner; do not present ours as authoritative.
        session.rollback()
        return ConsumeResult(consumed=False, deduplicated=False, busy=True)


def _token_of(session: Session, outbox_id: str) -> str | None:
    """Read the current consumer claim token for fencing."""
    row = session.get(OutboxRow, outbox_id)
    if row is None:
        return None
    token = row.claim_token
    return str(token) if token is not None else None


def _record(session: Session, outbox_id: str, token: str | None, execution_id: str | None) -> bool:
    """Record the execution outcome, fenced on the consumer claim token.

    Returns True when this worker still owns the claim; False when a
    newer claim superseded it (caller must not present its outcome).
    """
    if token is None:
        return False
    won = session.execute(
        update(OutboxRow)
        .where(
            OutboxRow.id == outbox_id,
            OutboxRow.status == "CONSUMING",
            OutboxRow.claim_token == token,
        )
        .values(
            consumed_at=datetime.now(UTC).replace(tzinfo=None),
            status="CONSUMED",
            execution_id=execution_id,
            leased_until=None,
            claim_token=None,
            claimed_by=None,
        )
    ).rowcount  # type: ignore[attr-defined]  # CursorResult at runtime
    return bool(won)
