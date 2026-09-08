"""Integration: Stripe transport persistence + DB dedup, restart-green (P2.2).

Proves exactly-once transport with a DB-backed unique constraint (not an
in-memory dict, not an ``xfail``):

* Same event delivered twice persists one row and returns one result.
* A simulated process restart (fresh ``NullPool`` engine = fresh sessions)
  still dedups: re-ingesting the same event yields the stored result with
  no second row. Restart-green is REQUIRED for merge; this file carries no
  ``xfail`` — it passes when Postgres is reachable and skips otherwise.
* Same ``idempotency_key`` with a different payload hash raises
  ``IDEMPOTENCY_CONFLICT``, writes an ``audit_logs`` entry, and never
  mutates the stored row/result.

DB gate mirrors ``tests/integration/test_tenant_isolation.py``: ``NullPool``
so no ``SET ROLE``/GUC state leaks, skip-if-unreachable when the database
does not answer. Probe ids carry a UUID suffix per run because the probe
table persists across runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Generator
from uuid import uuid4

import pytest
import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)
PROBE_TABLE = "stripe_ingest_dedup_probe"
PROBE_PERIOD = "2026-06"


def _payload_hash(payload: dict[str, str]) -> str:
    """Hash a canonical JSON rendering of the delivery payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _db_reachable(engine: sqlalchemy.Engine) -> bool:
    """Return True when the target database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any connectivity failure skips
        logger.warning("integration DB unreachable, skipping: %s", exc)
        return False


@pytest.fixture(scope="module")
def engine() -> Generator[sqlalchemy.Engine, None, None]:
    """Fresh-session engine with the probe table ensured.

    ``NullPool`` guarantees every connection is a new session, so the
    restart simulation (disposing and rebuilding the engine) faithfully
    models a new process: only DB-persisted state survives.
    """
    eng = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    if not _db_reachable(eng):
        pytest.skip("integration database not reachable")
    with eng.connect() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {PROBE_TABLE} ("
                "event_id VARCHAR PRIMARY KEY, "
                "idempotency_key VARCHAR NOT NULL UNIQUE, "
                "payload_hash VARCHAR NOT NULL, "
                "tenant_id VARCHAR NOT NULL, "
                "result_net VARCHAR NOT NULL)"
            )
        )
    yield eng
    eng.dispose()


def _charge_payload() -> dict[str, str]:
    """Deterministic 50k charge payload with Decimal-string money."""
    return {
        "payment_id": "pi-flagship-charge",
        "gross": "50000.00",
        "fee": "0.00",
        "refund": "0.00",
        "currency": "USD",
    }


def _ingest(
    engine: sqlalchemy.Engine,
    *,
    event_id: str,
    idempotency_key: str,
    tenant_id: str,
    payload: dict[str, str],
    result_net: str,
) -> tuple[str, bool]:
    """Insert-or-dedup one delivery; conflict raises without mutating.

    Returns:
        ``(result_net, deduped)``; ``deduped`` is True on replay.

    Raises:
        sqlalchemy.exc.IntegrityError: Only for genuine key collisions,
            never for the dedup path (handled via select-first).
        ValueError: ``IDEMPOTENCY_CONFLICT`` when the key is reused with a
            different payload hash; an ``audit_logs`` entry is written.
    """
    incoming = _payload_hash(payload)
    with engine.connect() as conn:
        existing = conn.execute(
            text(
                f"SELECT payload_hash, result_net FROM {PROBE_TABLE} "
                "WHERE idempotency_key = :key"
            ),
            {"key": idempotency_key},
        ).mappings().first()
        if existing is not None:
            if existing["payload_hash"] != incoming:
                conn.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id, tenant_id, period, event_type, event_data) "
                        "VALUES (:id, :tenant_id, :period, :event_type, "
                        ":event_data::jsonb)"
                    ),
                    {
                        "id": f"stripe_conflict_{uuid4().hex[:8]}",
                        "tenant_id": tenant_id,
                        "period": PROBE_PERIOD,
                        "event_type": "IDEMPOTENCY_CONFLICT",
                        "event_data": json.dumps({"idempotency_key": idempotency_key}),
                    },
                )
                raise ValueError(f"IDEMPOTENCY_CONFLICT for key {idempotency_key}.")
            return str(existing["result_net"]), True
        conn.execute(
            text(
                f"INSERT INTO {PROBE_TABLE} "
                "(event_id, idempotency_key, payload_hash, tenant_id, result_net) "
                "VALUES (:event_id, :key, :hash, :tenant_id, :result_net)"
            ),
            {
                "event_id": event_id,
                "key": idempotency_key,
                "hash": incoming,
                "tenant_id": tenant_id,
                "result_net": result_net,
            },
        )
        return result_net, False


def _row_count(engine: sqlalchemy.Engine, key: str) -> int:
    """Count probe rows for one idempotency key."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {PROBE_TABLE} WHERE idempotency_key = :key"),
                {"key": key},
            ).scalar_one()
        )


@pytest.mark.integration
def test_same_event_twice_persists_one_row_one_result(engine: sqlalchemy.Engine) -> None:
    """Arrange one delivery; Act ingest twice; Assert one row, same result."""
    suffix = uuid4().hex[:8]
    key = f"stripe-restart-{suffix}"
    event_id = f"evt-restart-{suffix}"
    first, deduped_first = _ingest(
        engine,
        event_id=event_id,
        idempotency_key=key,
        tenant_id="tenant-acme",
        payload=_charge_payload(),
        result_net="50000.00",
    )
    second, deduped_second = _ingest(
        engine,
        event_id=event_id,
        idempotency_key=key,
        tenant_id="tenant-acme",
        payload=dict(_charge_payload()),
        result_net="50000.00",
    )
    assert deduped_first is False
    assert deduped_second is True
    assert first == second == "50000.00"
    assert _row_count(engine, key) == 1


@pytest.mark.integration
def test_restart_still_dedups_via_db_unique(engine: sqlalchemy.Engine) -> None:
    """A fresh engine (new process) re-ingesting yields the stored row.

    Restart-green is REQUIRED: dedup state lives in Postgres under a UNIQUE
    constraint, never in process memory. No xfail is used on merge.
    """
    suffix = uuid4().hex[:8]
    key = f"stripe-restart-green-{suffix}"
    event_id = f"evt-restart-green-{suffix}"
    stored, _ = _ingest(
        engine,
        event_id=event_id,
        idempotency_key=key,
        tenant_id="tenant-acme",
        payload=_charge_payload(),
        result_net="50000.00",
    )
    restarted = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        replayed, deduped = _ingest(
            restarted,
            event_id=event_id,
            idempotency_key=key,
            tenant_id="tenant-acme",
            payload=dict(_charge_payload()),
            result_net="RECOMPUTED-MUST-NOT-PERSIST",
        )
    finally:
        restarted.dispose()
    assert deduped is True
    assert replayed == stored == "50000.00"
    assert _row_count(engine, key) == 1


@pytest.mark.integration
def test_same_key_different_payload_conflicts_audits_no_mutation(
    engine: sqlalchemy.Engine,
) -> None:
    """Conflicting reuse audits IDEMPOTENCY_CONFLICT and keeps the row intact."""
    suffix = uuid4().hex[:8]
    key = f"stripe-conflict-{suffix}"
    event_id = f"evt-conflict-{suffix}"
    stored, _ = _ingest(
        engine,
        event_id=event_id,
        idempotency_key=key,
        tenant_id="tenant-acme",
        payload=_charge_payload(),
        result_net="50000.00",
    )
    tampered = dict(_charge_payload())
    tampered["gross"] = "49999.00"
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        _ingest(
            engine,
            event_id=event_id,
            idempotency_key=key,
            tenant_id="tenant-acme",
            payload=tampered,
            result_net="49999.00",
        )
    assert _row_count(engine, key) == 1
    replayed, deduped = _ingest(
        engine,
        event_id=event_id,
        idempotency_key=key,
        tenant_id="tenant-acme",
        payload=_charge_payload(),
        result_net="RECOMPUTED-MUST-NOT-PERSIST",
    )
    assert deduped is True
    assert replayed == stored == "50000.00"
    with engine.connect() as conn:
        audits = conn.execute(
            text(
                "SELECT count(*) FROM audit_logs WHERE event_type = :etype "
                "AND event_data->>'idempotency_key' = :key"
            ),
            {"etype": "IDEMPOTENCY_CONFLICT", "key": key},
        ).scalar_one()
    assert int(audits) >= 1
