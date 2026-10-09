"""Integration tests: RLS on the P9 execution/idempotency ledger (Slice 3).

Failing until GREEN (``013_ledger_rls.sql`` does not exist): the most
security-critical tables — ``execution_records`` and
``idempotency_keys`` — currently rely on application-level tenant
scoping only. This extends the established 006/011 RLS convention
(deny-by-default, ``app.tenant_id`` GUC) to the ledger.

Requires a real, reachable Postgres; skipped otherwise (same DSN
convention as ``test_tenant_isolation.py``: ``FINSIGHT_TEST_DSN``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import sqlalchemy
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from alembic import command
from finance.exceptions.models import Base as ExceptionsBase
from shared.migrations import MigrationRunner, discover_migrations

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)

LIMITED_ROLE = "test_ledger_rls_limited"


def _reachable(engine: sqlalchemy.Engine) -> bool:
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
    """Engine with alembic head + SQL migrations + limited role + seeds."""
    engine = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    if not _reachable(engine):
        pytest.skip("integration database not reachable")
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DSN)
    command.upgrade(cfg, "head")
    psycopg_dsn = DSN.replace("postgresql+psycopg://", "postgresql://", 1)
    migrations = discover_migrations(MIGRATIONS_DIR)
    pre = [m for m in migrations if m.version <= "010"]
    post = [m for m in migrations if m.version > "010"]
    with psycopg.connect(psycopg_dsn, autocommit=True) as conn:
        results = MigrationRunner(conn).apply(pre)
    orm_engine = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        ExceptionsBase.metadata.create_all(orm_engine)
    finally:
        orm_engine.dispose()
    with psycopg.connect(psycopg_dsn, autocommit=True) as conn:
        results.extend(MigrationRunner(conn).apply(post))
    logger.info("applied %d SQL migrations", len(results))
    with engine.connect() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '"
                + LIMITED_ROLE
                + "') THEN CREATE ROLE "
                + LIMITED_ROLE
                + " NOLOGIN; END IF; END $$"
            )
        )
        conn.execute(
            text(f"GRANT CONNECT ON DATABASE {conn.engine.url.database} TO {LIMITED_ROLE}")
        )
        conn.execute(text("GRANT USAGE ON SCHEMA public TO " + LIMITED_ROLE))
        for table in ("execution_records", "idempotency_keys"):
            conn.execute(text(f"GRANT SELECT, INSERT ON {table} TO {LIMITED_ROLE}"))
        conn.execute(
            text(
                "INSERT INTO execution_records "
                "(tenant_id, idempotency_key, execution_id, exception_id, "
                " proposal_id, payload_hash, result) VALUES "
                "('tenant-rls-a', 'rls-key-a', 'exec-a', 'exc-a', 'prop-a', 'h', 'SUCCEEDED'),"
                "('tenant-rls-b', 'rls-key-b', 'exec-b', 'exc-b', 'prop-b', 'h', 'SUCCEEDED')"
                " ON CONFLICT DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(tenant_id, idempotency_key, payload_hash, created_at, updated_at) VALUES "
                "('tenant-rls-a', 'rls-key-a', 'h', now(), now()),"
                "('tenant-rls-b', 'rls-key-b', 'h', now(), now())"
                " ON CONFLICT DO NOTHING"
            )
        )
    yield engine
    engine.dispose()


def _as_role(engine: sqlalchemy.Engine, role: str, tenant: str | None) -> list[Any]:
    """Select ledger rows as the limited role with an optional tenant GUC."""
    with engine.connect() as conn:
        conn.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        if tenant is not None:
            conn.execute(text(f"SET app.tenant_id = '{tenant}'"))
        rows = conn.execute(
            text("SELECT tenant_id, idempotency_key FROM execution_records ORDER BY 2")
        ).all()
        conn.execute(text("RESET ROLE"))
        return list(rows)


class TestLedgerRls:
    def test_rls_enabled_on_ledger(self, engine: sqlalchemy.Engine) -> None:
        with engine.connect() as conn:
            flags: dict[str, bool] = {
                row[0]: row[1]
                for row in conn.execute(
                    text(
                        "SELECT relname, relrowsecurity FROM pg_class "
                        "WHERE relname IN ('execution_records', 'idempotency_keys')"
                    )
                ).all()
            }
        assert flags.get("execution_records") is True
        assert flags.get("idempotency_keys") is True

    def test_no_guc_sees_nothing(self, engine: sqlalchemy.Engine) -> None:
        assert _as_role(engine, LIMITED_ROLE, None) == []

    def test_tenant_a_sees_only_a(self, engine: sqlalchemy.Engine) -> None:
        rows = _as_role(engine, LIMITED_ROLE, "tenant-rls-a")
        assert [(r[0], r[1]) for r in rows] == [("tenant-rls-a", "rls-key-a")]

    def test_owner_bypass_sees_all(self, engine: sqlalchemy.Engine) -> None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tenant_id FROM execution_records "
                    "WHERE idempotency_key IN ('rls-key-a', 'rls-key-b') ORDER BY 1"
                )
            ).all()
        assert [r[0] for r in rows] == ["tenant-rls-a", "tenant-rls-b"]
