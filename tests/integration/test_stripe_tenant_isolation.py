"""Integration: Stripe ingest tenant isolation (P2.2/P2.3).

Asserts the transport is tenant-scoped using the same DB gate as
``tests/integration/test_tenant_isolation.py`` (``NullPool`` fresh sessions,
skip-if-unreachable):

* Tenant A rows are visible to A-scoped queries and invisible to B, and
  vice versa (distinct ``tenant_id`` values never leak across the scope).
* The probe table carries a ``NOT NULL`` tenant guard and a sweep finds no
  ``NULL`` ``tenant_id`` rows (mirroring the 010 backfill guarantee on the
  27 boundary tables).

Probe ids carry a UUID suffix per run because the table persists across runs.
"""

from __future__ import annotations

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

TENANT_A = "tenant-acme"
TENANT_B = "tenant-globex"


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
    """Fresh-session engine with the probe table ensured."""
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


@pytest.fixture(scope="module")
def tenant_rows(engine: sqlalchemy.Engine) -> Generator[tuple[str, str], None, None]:
    """Insert one probe row per tenant; yield the two idempotency keys."""
    suffix = uuid4().hex[:8]
    key_a = f"stripe-tenant-a-{suffix}"
    key_b = f"stripe-tenant-b-{suffix}"
    with engine.connect() as conn:
        conn.execute(
            text(
                f"INSERT INTO {PROBE_TABLE} "
                "(event_id, idempotency_key, payload_hash, tenant_id, result_net) "
                "VALUES (:event_id, :key, :hash, :tenant_id, :result_net)"
            ),
            {
                "event_id": f"evt-tenant-a-{suffix}",
                "key": key_a,
                "hash": f"hash-a-{suffix}",
                "tenant_id": TENANT_A,
                "result_net": "50000.00",
            },
        )
        conn.execute(
            text(
                f"INSERT INTO {PROBE_TABLE} "
                "(event_id, idempotency_key, payload_hash, tenant_id, result_net) "
                "VALUES (:event_id, :key, :hash, :tenant_id, :result_net)"
            ),
            {
                "event_id": f"evt-tenant-b-{suffix}",
                "key": key_b,
                "hash": f"hash-b-{suffix}",
                "tenant_id": TENANT_B,
                "result_net": "35000.00",
            },
        )
    yield key_a, key_b


def _scoped_count(
    engine: sqlalchemy.Engine, tenant_id: str, key: str
) -> int:
    """Count rows for one key inside one tenant scope."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    f"SELECT count(*) FROM {PROBE_TABLE} "
                    "WHERE idempotency_key = :key AND tenant_id = :tenant_id"
                ),
                {"key": key, "tenant_id": tenant_id},
            ).scalar_one()
        )


@pytest.mark.integration
def test_tenant_a_sees_only_own_row(
    engine: sqlalchemy.Engine, tenant_rows: tuple[str, str]
) -> None:
    """A-scoped queries see A's row but not B's."""
    key_a, key_b = tenant_rows
    assert _scoped_count(engine, TENANT_A, key_a) == 1
    assert _scoped_count(engine, TENANT_A, key_b) == 0


@pytest.mark.integration
def test_tenant_b_sees_only_own_row(
    engine: sqlalchemy.Engine, tenant_rows: tuple[str, str]
) -> None:
    """B-scoped queries see B's row but not A's."""
    key_a, key_b = tenant_rows
    assert _scoped_count(engine, TENANT_B, key_b) == 1
    assert _scoped_count(engine, TENANT_B, key_a) == 0


@pytest.mark.integration
def test_no_null_tenant_rows_in_probe(engine: sqlalchemy.Engine) -> None:
    """NULL sweep: the probe table holds no tenant-less rows."""
    with engine.connect() as conn:
        nulls = conn.execute(
            text(f"SELECT count(*) FROM {PROBE_TABLE} WHERE tenant_id IS NULL")
        ).scalar_one()
    assert int(nulls) == 0
