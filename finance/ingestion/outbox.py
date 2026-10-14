"""Transactional inbox + outbox persistence (issue #113).

The application/use-case boundary owns the transaction: the webhook
inbox row and its outbox dispatch row commit together or roll back
together. Dispatch references the stable ``webhook_event_id`` — never
fabricated domain state (review P1: the financial exception may not
exist yet at ingress).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.models.database import OutboxRow, WebhookEvent
from shared.webhook_repository import insert_or_get_duplicate

logger = logging.getLogger(__name__)


def persist_inbox_and_outbox(
    session: Session,
    *,
    tenant_id: str,
    provider: str,
    envelope: dict[str, Any],
    raw: bytes,
    status: str = "RECEIVED",
) -> tuple[WebhookEvent, OutboxRow, bool]:
    """Persist inbox + outbox atomically; return ``(event, outbox, created)``.

    Commits on success (the function owns the transaction). On replay
    the existing rows are returned with ``created=False`` and no second
    outbox row is created. ``raw`` feeds the payload hash only; the
    inbox stores the parsed envelope per existing behavior.
    """
    payload_hash = hashlib.sha256(raw).hexdigest()
    event, created = insert_or_get_duplicate(
        session,
        tenant_id=tenant_id,
        provider=provider,
        event_id=str(envelope["id"]),
        event_type=str(envelope["type"]),
        raw=dict(envelope),
        fingerprint=payload_hash,
        status=status,
        _commit=False,
    )
    if created:
        outbox = OutboxRow(
            id=f"wh_ob_{uuid.uuid4().hex[:16]}",
            tenant_id=event.tenant_id,
            webhook_event_id=event.id,
            provider=event.provider,
            event_id=event.event_id,
            status="PENDING",
            payload_hash=payload_hash,
            attempts=0,
        )
        session.add(outbox)
    else:
        existing = session.execute(
            select(OutboxRow).where(OutboxRow.webhook_event_id == event.id)
        ).scalar_one_or_none()
        if existing is None:  # pragma: no cover - defensive; unique guards it
            outbox = OutboxRow(
                id=f"wh_ob_{uuid.uuid4().hex[:16]}",
                tenant_id=event.tenant_id,
                webhook_event_id=event.id,
                provider=event.provider,
                event_id=event.event_id,
                status="PENDING",
                payload_hash=payload_hash,
                attempts=0,
            )
            session.add(outbox)
        else:
            outbox = existing
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        event = session.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == provider,
                WebhookEvent.event_id == str(envelope["id"]),
            )
        ).scalar_one()
        outbox = session.execute(
            select(OutboxRow).where(OutboxRow.webhook_event_id == event.id)
        ).scalar_one()
        return event, outbox, False
    except Exception:
        session.rollback()
        raise
    session.refresh(event)
    session.refresh(outbox)
    return event, outbox, created
