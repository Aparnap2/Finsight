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

import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

PG_DSN = os.environ.get(
    "FINSIGHT_TEST_DSN",
    "postgresql+psycopg://finsight:finsight@localhost:5432/finsight",
)
_PG_HOST = "localhost"
_PG_PORT = 5432
try:
    from urllib.parse import urlparse

    _parsed = urlparse(PG_DSN.replace("postgresql+psycopg://", "postgresql://"))
    _PG_HOST = _parsed.hostname or _PG_HOST
    _PG_PORT = _parsed.port or _PG_PORT
except Exception:  # noqa: BLE001 - fall back to defaults
    pass


def _pg_reachable() -> bool:
    """Return True when PostgreSQL answers."""
    try:
        socket.create_connection((_PG_HOST, _PG_PORT), timeout=2).close()
        return True
    except OSError:
        return False


needs_pg = pytest.mark.skipif(not _pg_reachable(), reason="needs PostgreSQL")


@pytest.fixture()
def engine() -> Iterator[Any]:
    """Engine migrated to head (alembic) for outbox tests."""
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy.exc import OperationalError

    from alembic import command

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", PG_DSN)
    try:
        command.upgrade(cfg, "head")
    except OperationalError:
        pytest.skip("integration database not usable")
    engine = create_engine(PG_DSN)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(engine: Any) -> Iterator[None]:
    """Isolate tests: the shared scratch PG persists across tests."""
    with Session(engine) as session:
        session.execute(text("DELETE FROM webhook_outbox"))
        session.execute(text("DELETE FROM webhook_events"))
        session.commit()
    yield


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
        from unittest.mock import patch

        from sqlalchemy.orm import Session as OrmSession

        from finance.ingestion.outbox import persist_inbox_and_outbox

        with Session(engine) as session:
            real_commit = session.commit
            calls = 0

            def _fail_once() -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("commit transport lost")
                real_commit()

            with (
                patch.object(OrmSession, "commit", lambda self: _fail_once()),
                pytest.raises(RuntimeError, match="commit transport lost"),
            ):
                persist_inbox_and_outbox(
                    session,
                    tenant_id="tenant-a",
                    provider="stripe",
                    envelope=_envelope("evt_outbox_boom"),
                    raw=b"{}",
                )
        with Session(engine) as session:
            inbox = session.execute(
                text("SELECT COUNT(*) FROM webhook_events WHERE event_id = :e"),
                {"e": "evt_outbox_boom"},
            ).scalar()
            outbox = session.execute(text("SELECT COUNT(*) FROM webhook_outbox")).scalar()
        assert inbox == 0
        assert outbox == 0

    def test_quarantined_event_never_dispatches(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            event, outbox, created = persist_inbox_and_outbox(
                session,
                tenant_id="UNROUTABLE",
                provider="stripe",
                envelope=_envelope("evt_quarantined_1"),
                raw=b"{}",
                status="IGNORED",
            )
        assert created is True
        assert outbox is None  # inbox persists for audit; no dispatch row ever
        pub = Publisher(engine, lambda row: None)
        assert pub.claim_due(limit=10) == []
        with Session(engine) as session:
            rows = session.execute(text("SELECT COUNT(*) FROM webhook_outbox")).scalar()
        assert rows == 0

    def test_duplicate_delivery_replays_without_second_outbox(self, engine: Any) -> None:
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
                text("SELECT COUNT(*) FROM webhook_outbox WHERE webhook_event_id = :id"),
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

        def _sender(row: Any) -> None:
            published.append(str(row.webhook_event_id))

        pub = Publisher(engine, _sender)
        claimed = pub.claim_due(limit=10)
        assert len(claimed) == 1
        # Crash window 1: sender succeeds externally, process dies before
        # publish() records success. Simulate by sending without recording.
        _sender(claimed[0])
        assert published == [str(event.id)]
        # Replacement publisher cannot see the leased row yet (no loss, no dup).
        pub2 = Publisher(engine, _sender)
        assert pub2.claim_due(limit=10) == []
        # Lease expires: the row becomes claimable again (recovery).
        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE webhook_outbox SET leased_until = now() - interval '1 hour' "
                    "WHERE webhook_event_id = :id"
                ),
                {"id": event.id},
            )
            session.commit()
        again = pub2.claim_due(limit=10)
        assert [str(r.webhook_event_id) for r in again] == [str(event.id)]
        pub2.publish(again[0])
        with Session(engine) as session:
            status = session.execute(
                text("SELECT status FROM webhook_outbox WHERE webhook_event_id = :id"),
                {"id": event.id},
            ).scalar()
            rows = session.execute(
                text("SELECT COUNT(*) FROM webhook_outbox WHERE webhook_event_id = :id"),
                {"id": event.id},
            ).scalar()
        assert status == "PUBLISHED"
        assert rows == 1  # redelivery never duplicates the dispatch row

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

    def test_stale_worker_cannot_mutate_reclaimed_claim(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            event, _, _ = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_stale"),
                raw=b"{}",
            )
        sent: list[str] = []
        worker_a = Publisher(engine, lambda row: sent.append(str(row.id)))
        (stale_claim,) = worker_a.claim_due(limit=10)
        # Lease expires; worker B reclaims the row with a fresh token.
        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE webhook_outbox SET leased_until = now() - interval '1 hour' "
                    "WHERE webhook_event_id = :id"
                ),
                {"id": event.id},
            )
            session.commit()
        worker_b = Publisher(engine, lambda row: sent.append(str(row.id)))
        (fresh_claim,) = worker_b.claim_due(limit=10)
        assert str(fresh_claim.claim_token) != str(stale_claim.claim_token)
        # Stale worker A's publish/fail must not touch B's claim.
        assert worker_a.publish(stale_claim) is False
        assert sent == []  # superseded worker never invokes the sender
        assert worker_a.fail(stale_claim, "late error") is False
        with Session(engine) as session:
            status = session.execute(
                text("SELECT status FROM webhook_outbox WHERE webhook_event_id = :id"),
                {"id": event.id},
            ).scalar()
        assert status == "CLAIMED"
        assert worker_b.publish(fresh_claim) is True

    def test_expired_unreclaimed_publish_refused_without_send(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        sent: list[str] = []
        with Session(engine) as session:
            persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_expired"),
                raw=b"{}",
            )
        worker = Publisher(engine, lambda row: sent.append(str(row.id)))
        (claimed,) = worker.claim_due(limit=10)
        # Lease lapses with no reclaimer: the claim is expired, so even
        # the owning worker must not send on it — reclaim first.
        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE webhook_outbox SET leased_until = now() - interval '1 hour' "
                    "WHERE status = 'CLAIMED'"
                )
            )
            session.commit()
        assert worker.publish(claimed) is False
        assert sent == []

    def test_attempts_bounded_then_terminal(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_bound"),
                raw=b"{}",
            )
            session.execute(text("UPDATE webhook_outbox SET attempts = 5 WHERE status = 'PENDING'"))
            session.commit()
        pub = Publisher(engine, lambda row: None, max_attempts=5)
        assert pub.claim_due(limit=10) == []
        with Session(engine) as session:
            status = session.execute(
                text("SELECT status FROM webhook_outbox WHERE event_id = :e"),
                {"e": "evt_pub_bound"},
            ).scalar()
        assert status == "TERMINAL"

    def test_fail_sanitizes_and_releases(self, engine: Any) -> None:
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope("evt_pub_fail"),
                raw=b"{}",
            )
        pub = Publisher(engine, lambda row: None)
        (claimed,) = pub.claim_due(limit=10)
        assert pub.fail(claimed, "timeout for user alice@example.com ssn 123") is True
        with Session(engine) as session:
            stored, status = session.execute(
                text("SELECT last_error, status FROM webhook_outbox WHERE event_id = :e"),
                {"e": "evt_pub_fail"},
            ).one()
        assert "alice@example.com" not in (stored or "")
        assert status == "PENDING"

    def test_production_composition_requires_engines(self, engine: Any) -> None:
        from finance.ingestion.consumer import consume_once
        from finance.ingestion.publisher import Publisher

        with pytest.raises(ValueError, match="durable engine"):
            Publisher(None, lambda row: None)
        with pytest.raises(ValueError, match="durable engine"):
            consume_once(None, "wh_ob_x", lambda: None)


@needs_pg
class TestConsumer:
    def _published_id(self, engine: Any, event_key: str) -> str:
        """Drive PENDING -> publisher claim -> PUBLISHED; return outbox id."""
        from finance.ingestion.outbox import persist_inbox_and_outbox
        from finance.ingestion.publisher import Publisher

        with Session(engine) as session:
            _, outbox, _ = persist_inbox_and_outbox(
                session,
                tenant_id="tenant-a",
                provider="stripe",
                envelope=_envelope(event_key),
                raw=b"{}",
            )
            assert outbox is not None
            outbox_id = str(outbox.id)
        pub = Publisher(engine, lambda row: None)
        assert len(pub.claim_due(limit=10)) == 1
        with Session(engine) as session:
            row = session.execute(
                text("SELECT id FROM webhook_outbox WHERE id = :id"), {"id": outbox_id}
            ).scalar()
            assert row is not None
        # Re-read the claimed row for its token, then publish.
        with Session(engine) as session:
            from shared.models.database import OutboxRow

            claimed = session.get(OutboxRow, outbox_id)
            assert claimed is not None
            assert pub.publish(claimed) is True
        return outbox_id

    def test_full_path_pending_to_consumed(self, engine: Any) -> None:
        from finance.ingestion.consumer import consume_once

        effects: list[str] = []
        outbox_id = self._published_id(engine, "evt_cons_full")

        def _execute() -> str:
            effects.append("ran")
            return "exec-1"

        result = consume_once(engine, outbox_id, _execute)
        assert result.consumed is True
        assert result.deduplicated is False
        assert result.execution_id == "exec-1"
        assert effects == ["ran"]
        with Session(engine) as session:
            status = session.execute(
                text("SELECT status FROM webhook_outbox WHERE id = :id"),
                {"id": outbox_id},
            ).scalar()
        assert status == "CONSUMED"

    def test_redelivery_single_effect(self, engine: Any) -> None:
        from finance.ingestion.consumer import consume_once

        effects: list[str] = []

        def _execute() -> str:
            effects.append("ran")
            return "exec-1"

        outbox_id = self._published_id(engine, "evt_cons_1")
        first = consume_once(engine, outbox_id, _execute)
        second = consume_once(engine, outbox_id, _execute)
        assert first.consumed is True
        assert second.deduplicated is True
        assert second.execution_id == first.execution_id == "exec-1"
        assert effects == ["ran"]

    def test_live_claim_is_busy_never_double_executes(self, engine: Any) -> None:
        from finance.ingestion.consumer import consume_once

        calls: list[str] = []
        outbox_id = self._published_id(engine, "evt_cons_busy")
        # Another live worker holds a CONSUMING claim (fault injection).
        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE webhook_outbox SET status = 'CONSUMING', "
                    "claimed_by = 'consumer', claim_token = 'tok-live', "
                    "leased_until = now() + interval '1 hour' WHERE id = :id"
                ),
                {"id": outbox_id},
            )
            session.commit()

        def _noop() -> str:
            calls.append("ran")
            return "exec-x"

        result = consume_once(engine, outbox_id, _noop)
        assert result.busy is True
        assert result.consumed is False
        assert calls == []

    def test_concurrent_reconcile_runs_hook_once(self, engine: Any) -> None:
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from finance.ingestion.consumer import consume_once

        outbox_id = self._published_id(engine, "evt_cons_race")
        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE webhook_outbox SET status = 'CONSUMING', "
                    "claimed_by = 'consumer', claim_token = 'tok-dead', "
                    "leased_until = now() - interval '1 hour' WHERE id = :id"
                ),
                {"id": outbox_id},
            )
            session.commit()
        hook_calls: list[str] = []
        gate = threading.Barrier(2)

        def _racer(_n: int) -> Any:
            gate.wait(timeout=10)

            def _hook() -> str:
                hook_calls.append("ran")
                return "exec-race"

            return consume_once(engine, outbox_id, lambda: "exec-race", reconcile=_hook)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(_racer, (0, 1)))
        assert hook_calls == ["ran"]  # exactly one reconciliation ran
        assert sum(1 for r in results if r.consumed) == 1
        assert sum(1 for r in results if r.busy) == 1

    def test_crashed_claim_needs_reconciliation_not_reexecution(self, engine: Any) -> None:
        from finance.ingestion.consumer import consume_once

        calls: list[str] = []
        outbox_id = self._published_id(engine, "evt_cons_crash")
        # Crash: CONSUMING lease expires with no execution recorded —
        # the effect may or may not have run (outcome UNKNOWN).
        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE webhook_outbox SET status = 'CONSUMING', "
                    "claimed_by = 'consumer', claim_token = 'tok-dead', "
                    "leased_until = now() - interval '1 hour' WHERE id = :id"
                ),
                {"id": outbox_id},
            )
            session.commit()

        def _execute() -> str:
            calls.append("ran")
            return "exec-x"

        result = consume_once(engine, outbox_id, _execute)
        assert result.needs_reconciliation is True
        assert calls == []  # never blindly re-executed
        recovered = consume_once(engine, outbox_id, _execute, reconcile=lambda: "exec-x")
        assert recovered.consumed is True
        assert recovered.deduplicated is True
        assert recovered.execution_id == "exec-x"
        assert calls == []


@needs_pg
class TestDurableStores:
    def test_volatile_defaults_refused(self) -> None:
        from finance.legacy_execution.record import ExecutionRecordStore
        from finance.legacy_execution.reservation import ReservationStore
        from shared.safety.durability import assert_durable
        from shared.safety.idempotency import IdempotencyStore

        for store, name in (
            (IdempotencyStore(), "IdempotencyStore"),
            (ReservationStore(), "ReservationStore"),
            (ExecutionRecordStore(), "ExecutionRecordStore"),
        ):
            with pytest.raises(RuntimeError, match="volatile"):
                assert_durable(store, store_name=name)
        with pytest.raises(RuntimeError, match="volatile"):
            assert_durable(None, store_name="Nothing")

    def test_explicit_engine_accepted(self) -> None:
        from sqlalchemy import create_engine as _create_engine

        from finance.legacy_execution.reservation import ReservationStore
        from shared.safety.durability import assert_durable
        from shared.safety.idempotency import IdempotencyStore

        memory = _create_engine("sqlite://")
        assert_durable(IdempotencyStore(memory), store_name="idem")
        assert_durable(ReservationStore(memory), store_name="resv")
        assert_durable(IdempotencyStore(), store_name="idem", allow_volatile=True)
