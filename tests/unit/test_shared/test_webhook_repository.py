"""Unit tests for the webhook envelope persistence contract.

Covers insert-or-create semantics, duplicate replay, the provider+event
unique boundary, raw immutability, and Decimal-only money. Uses an
in-memory SQLite database; no network or external services.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.models.database import Base, WebhookEvent
from shared.webhook_repository import insert_or_get_duplicate


@pytest.fixture()
def session() -> Iterator[Session]:
    """Provide an isolated in-memory SQLite session per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _envelope() -> dict[str, object]:
    """Build a minimal verbatim Stripe-style payload."""
    return {"id": "evt_123", "type": "charge.succeeded", "data": {"object": {}}}


def test_insert_returns_created_true(session: Session) -> None:
    """First delivery persists with RECEIVED status and returns created=True."""
    event, created = insert_or_get_duplicate(
        session,
        tenant_id="CF001",
        provider="stripe",
        event_id="evt_123",
        event_type="charge.succeeded",
        raw=_envelope(),
        fingerprint="a" * 64,
        amount=Decimal("500.00"),
        currency="USD",
    )
    assert created is True
    assert event.status == "RECEIVED"
    assert event.tenant_id == "CF001"
    assert event.raw == _envelope()
    assert event.amount == Decimal("500.00")


def test_duplicate_returns_existing_without_reinsert(session: Session) -> None:
    """Second delivery of the same envelope returns the stored row."""
    first, created_first = insert_or_get_duplicate(
        session,
        tenant_id="CF001",
        provider="stripe",
        event_id="evt_123",
        event_type="charge.succeeded",
        raw=_envelope(),
    )
    second, created_second = insert_or_get_duplicate(
        session,
        tenant_id="CF001",
        provider="stripe",
        event_id="evt_123",
        event_type="charge.succeeded",
        raw=_envelope(),
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert session.query(WebhookEvent).count() == 1


def test_same_event_id_different_provider_is_distinct(session: Session) -> None:
    """Uniqueness is scoped to (provider, event_id), not event_id alone."""
    _, created_a = insert_or_get_duplicate(
        session,
        tenant_id="CF001",
        provider="stripe",
        event_id="evt_123",
        event_type="charge.succeeded",
        raw=_envelope(),
    )
    _, created_b = insert_or_get_duplicate(
        session,
        tenant_id="CF001",
        provider="quickbooks",
        event_id="evt_123",
        event_type="charge.succeeded",
        raw=_envelope(),
    )
    assert created_a is True
    assert created_b is True
    assert session.query(WebhookEvent).count() == 2


def test_raw_payload_stored_verbatim(session: Session) -> None:
    """The raw envelope round-trips byte-identical (immutable contract)."""
    raw = {"id": "evt_9", "nested": {"fee": 0, "tags": ["a", "b"]}}
    event, _ = insert_or_get_duplicate(
        session,
        tenant_id="CF001",
        provider="stripe",
        event_id="evt_9",
        event_type="refund.created",
        raw=raw,
    )
    assert event.raw == raw


def test_float_money_rejected(session: Session) -> None:
    """Float amounts are rejected at the repository boundary."""
    with pytest.raises(ValueError, match="must be Decimal"):
        insert_or_get_duplicate(
            session,
            tenant_id="CF001",
            provider="stripe",
            event_id="evt_f",
            event_type="charge.succeeded",
            raw=_envelope(),
            amount=500.00,  # type: ignore[arg-type]
        )


def test_empty_identifiers_rejected(session: Session) -> None:
    """Empty tenant/provider/event identifiers are rejected."""
    with pytest.raises(ValueError, match="non-empty string"):
        insert_or_get_duplicate(
            session,
            tenant_id="",
            provider="stripe",
            event_id="evt_x",
            event_type="charge.succeeded",
            raw=_envelope(),
        )
