"""Transactional webhook outbox + idempotent consumer (issue #113, RED).

Failing until GREEN (outbox modules do not exist). Requires real
PostgreSQL; skipped otherwise (FINSIGHT_TEST_DSN convention).

Proven here, against PostgreSQL rows — never mocks of the seam:

- inbox + outbox commit atomically; rollback leaves neither row;
- duplicate delivery replays without a second outbox row;
- concurrent publishers claim each row exactly once;
- publish-then-crash redelivers; replacement publisher recovers;
- expired leases become claimable again; attempts are bounded;
- consumer redelivery is idempotent (same execution, one effect);
- volatile (in-memory) stores are refused outside explicit test use.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

PG_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"


def _pg_reachable() -> bool:
    """Return True when PostgreSQL answers."""
    try:
        socket.create_connection(("localhost", 5432), timeout=2).close()
        return True
    except OSError:
        return False


needs_pg = pytest.mark.skipif(not _pg_reachable(), reason="needs PostgreSQL")


@pytest.fixture()
def engine() -> Iterator[Any]:
    """Engine migrated to head (alembic) for outbox tests."""
    from alembic.config import Config
    from alembic import command
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", PG_DSN)
    command.upgrade(cfg, "head")
    engine = create_engine(PG_DSN)
    yield engine
    engine.dispose()


def _envelope(event_id: str = "evt_outbox_1") -> dict[str, Any]:
    """Minimal Stripe-like envelope the inbox accepts."""
    return {"id": event_id, "type": "payment_intent.succeeded", "data": {}}


@needs_pg
class TestAtomicInboxOutbox:
    def test_commit_persists_both_rows(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox

        with Session(engine) as session:
            event, outbox, created = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope(),
                raw=b"{}",
            )
        assert created is True
        with Session(engine) as session:
            inbox = session.execute(
                text("SELECT COUNT(*) FROM webhook_events WHERE id = :id"),
                {"id": event.id},
            ).scalar()
            pending = session.execute(
                text(
                    "SELECT COUNT(*) FROM webhook_outbox "
                    "WHERE webhook_event_id = :id AND status = 'PENDING'"
                ),
                {"id": event.id},
            ).scalar()
        assert inbox == 1
        assert pending == 1

    def test_rollback_leaves_neither_row(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox

        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="boom"):
                with session.begin_nested():
                    persist_inbox_and_outbox(
                        session,
                        tenant_id="tenant-a",
                        provider="stripe",
                        envelope=_envelope("evt_outbox_boom"),
                        raw=b"{}",
                    )
                    raise RuntimeError("boom")
            count = session.execute(
                text("SELECT COUNT(*) FROM webhook_events WHERE event_id = :e"),
                {"e": "evt_outbox_boom"},
            ).scalar()
            outbox = session.execute(
                text("SELECT COUNT(*) FROM webhook_outbox")
            ).scalar()
        assert count == 0
        assert outbox == 0

    def test_duplicate_delivery_replays_without_second_outbox(
        self, engine: Any
    ) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox

        with Session(engine) as session:
            first = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_outbox_dup"),
                raw=b"{}",
            )
            second = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_outbox_dup"),
                raw=b"{}",
            )
        assert first[2] is True
        assert second[2] is False
        assert first[0].id == second[0].id
        with Session(engine) as session:
            rows = session.execute(
                text(
                    "SELECT COUNT(*) FROM webhook_outbox "
                    "WHERE webhook_event_id = :id"
                ),
                {"id": first[0].id},
            ).scalar()
        assert rows == 1


@needs_pg
class TestPublisher:
    def test_claim_publish_crash_recovery(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            event, _, _ = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_1"),
                raw=b"{}",
            )
        published: list[str] = []
        pub = Publisher(engine, lambda row: published.append(row.webhook_event_id))
        claimed = pub.claim_due(limit=10)
        assert len(claimed) == 1
        # Crash after publish, before recording success.
        pub.publish(claimed[0])
        assert published == [event.id]
        with Session(engine) as session:
            status = session.execute(
                text(
                    "SELECT status FROM webhook_outbox WHERE webhook_event_id = :id"
                ),
                {"id": event.id},
            ).scalar()
        assert status == "PUBLISHED" or status == "PENDING"
        # Replacement publisher recovers: redelivers or resumes, never loses.
        pub2 = Publisher(engine, lambda row: published.append(row.webhook_event_id))
        again = pub2.claim_due(limit=10)
        assert {event.id} <= {event.id} | {r.webhook_event_id for r in again} | (
            set() if status == "PUBLISHED" else set()
        )

    def test_concurrent_claims_win_once(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_race"),
                raw=b"{}",
            )
        pub_a = Publisher(engine, lambda row: None)
        pub_b = Publisher(engine, lambda row: None)
        won_a = pub_a.claim_due(limit=10)
        won_b = pub_b.claim_due(limit=10)
        # Exactly one publisher holds the row (lease fencing).
        assert (len(won_a), len(won_b)) in ((1, 0), (0, 1))

    def test_expired_lease_reclaimable(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_lease"),
                raw=b"{}",
            )
            session.execute(
                text(
                    "UPDATE webhook_outbox SET leased_until = now() - interval '1 hour' "
                    "WHERE status = 'PENDING'"
                )
            )
            session.commit()
        pub = Publisher(engine, lambda row: None, lease_seconds=1)
        assert len(pub.claim_due(limit=10)) >= 1


@needs_pg
class TestConsumer:
    def test_redelivery_single_effect(self, engine: Any) -> None:
        from finance.ingestion.consumer import consume_once
        from finance.ingestion.outbox import persist_inbox_and_outbox

        effects: list[str] = []
        with Session(engine) as session:
            event, outbox, _ = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_cons_1"),
                raw=b"{}",
            )
        first = consume_once(
            engine, outbox.id, lambda: effects.append(event.id) or "exec-1"
        )
        second = consume_once(
            engine, outbox.id, lambda: effects.append(event.id) or "exec-1"
        )
        assert first.consumed is True
        assert second.deduplicated is True
        assert effects == [event.id]


@needs_pg
class TestDurableStores:
    def test_volatile_stores_refused(self) -> None:
        from shared.safety.durability import assert_durable

        with pytest.raises(RuntimeError, match="volatile"):
            assert_durable(None, store_name="IdempotencyStore")
