"""Persistence boundary for raw provider webhook envelopes.

Insert-or-get-duplicate only: this module performs no business logic, no
normalization, and no classification. Callers persist the raw envelope first
(INSERT+COMMIT before processing) and branch on the ``created`` flag to treat
replays as safe no-ops.
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.models.database import WebhookEvent

logger = logging.getLogger(__name__)


def _require_money(field_name: str, value: object) -> Decimal | None:
    """Validate an optional money field as Decimal-only (float/bool rejected)."""
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise ValueError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value.strip())
    raise ValueError(
        f"Field '{field_name}' must be Decimal, int, str, or None, "
        f"got {type(value).__name__}."
    )


def insert_or_get_duplicate(
    session: Session,
    *,
    tenant_id: str,
    provider: str,
    event_id: str,
    event_type: str,
    raw: dict[str, Any],
    fingerprint: str | None = None,
    amount: Decimal | int | str | None = None,
    currency: str | None = None,
    status: str = "RECEIVED",
) -> tuple[WebhookEvent, bool]:
    """Insert a webhook envelope, or return the existing row on replay.

    Args:
        session: Active SQLAlchemy session (commit happens here).
        tenant_id: Explicit tenant scope, or the ``UNROUTABLE`` sentinel.
        provider: Provider name (e.g. ``"stripe"``).
        event_id: Provider-side event identifier.
        event_type: Provider-side event type.
        raw: Verbatim provider payload (stored immutable).
        fingerprint: Optional P1 stable hash of the normalized payload.
        amount: Optional money snapshot (Decimal-only).
        currency: Optional ISO 4217 code.
        status: Initial lifecycle status (default ``"RECEIVED"``).

    Returns:
        ``(event, created)`` — ``created`` is False when the envelope was
        already stored (duplicate delivery).

    Raises:
        ValueError: If identifiers are empty or money is float/bool.
    """
    for field_name, value in (
        ("tenant_id", tenant_id),
        ("provider", provider),
        ("event_id", event_id),
        ("event_type", event_type),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    if not isinstance(raw, dict):
        raise ValueError(f"Field 'raw' must be a dict, got {type(raw).__name__}.")

    existing = session.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider, WebhookEvent.event_id == event_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "Duplicate webhook ignored provider=%s event_id=%s",
            provider,
            event_id,
        )
        return existing, False

    event = WebhookEvent(
        id=f"wh_{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id.strip(),
        provider=provider.strip(),
        event_id=event_id.strip(),
        event_type=event_type.strip(),
        status=status,
        fingerprint=fingerprint,
        amount=_require_money("amount", amount),
        currency=currency,
        raw=dict(raw),
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = session.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == provider, WebhookEvent.event_id == event_id
            )
        ).scalar_one_or_none()
        if raced is None:
            raise
        logger.info(
            "Duplicate webhook raced insert provider=%s event_id=%s",
            provider,
            event_id,
        )
        return raced, False
    session.refresh(event)
    logger.info(
        "Stored webhook provider=%s event_id=%s tenant_id=%s status=%s",
        provider,
        event_id,
        tenant_id,
        status,
    )
    return event, True
