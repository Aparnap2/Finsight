"""Idempotent schema bootstrap for the integration tier.

Why this module exists
----------------------
The integration suite needs a migrated database. Until now that happened as a
side effect of whichever module ran first: ``test_ledger_rls.py`` and
``test_tenant_isolation.py`` each applied migrations in a module-scoped
fixture. Collection order is alphabetical, so ``test_ledger_rls`` always won
and the full-directory run looked healthy.

That made the suite order-dependent. Running a single module on a fresh
database failed with ``relation ... does not exist`` even though the exact same
tests passed in the full run::

    pytest tests/integration/test_reconciliation_http.py   # 10 failed on empty DB

Reproducible initialization is a release requirement, so the bootstrap is now
explicit (``tests/integration/conftest.py`` applies it once per session) and
this module holds the single implementation. ``test_tenant_isolation`` imports
from here instead of keeping a private copy.

Ordering is load-bearing and matches ``docs/release/LOCAL_DEPLOYMENT.md`` §5:

1. ``alembic upgrade head`` — base tables (``webhook_events``, ledger keys) and
   the reconciliation schema.
2. SQL ``000``-``010`` — extensions, constraints, RLS, audit triggers, identity.
3. ORM ``create_all`` for ``finance.exceptions.models.Base`` — ``exceptions``
   and ``exception_audits``, which no alembic revision creates.
4. SQL ``011``-``013`` — RLS for exceptions, audit allowlist widening, ledger RLS.

Every step is idempotent: alembic's version table, ``schema_migrations``, and
``create_all`` semantics all make re-application a no-op.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg
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


def psycopg_dsn() -> str:
    """Translate the SQLAlchemy DSN (``postgresql+psycopg://``) to a psycopg DSN."""
    return DSN.replace("postgresql+psycopg://", "postgresql://", 1)


def db_reachable() -> bool:
    """Return True when the target database answers a trivial query."""
    try:
        engine = create_engine(DSN, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        return True
    except Exception as exc:  # noqa: BLE001 - any connectivity failure is treated the same
        logger.warning("integration DB unreachable, skipping: %s", exc)
        return False


def apply_alembic_base() -> None:
    """Bring the alembic-tracked base schema to head (idempotent, version-tracked).

    File 011 needs base tables (e.g. ``webhook_events``) that exist only in the
    alembic chain, so the alembic base must precede the SQL set on a fresh DB.
    Honors the same DSN the fixture uses (``FINSIGHT_TEST_DSN``); alembic's
    ``env.py`` otherwise defaults to ``localhost:5432``. Safe to re-run.
    """
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DSN)
    command.upgrade(cfg, "head")


def apply_migrations() -> None:
    """Apply alembic base, then every migration file in version order.

    Fresh-DB order is load-bearing: ``alembic upgrade head`` first (base
    tables such as ``webhook_events``), then SQL 000-010, then the ORM
    ``create_all`` for the ``exceptions``/``exception_audits`` tables (created
    only by ``finance.exceptions.models.Base``), then 011 which enables RLS on
    them. Uses a dedicated psycopg3 connection in autocommit mode; each file is
    executed as one multi-statement ``ClientCursor`` call. Idempotency comes
    from alembic's version table, the ``schema_migrations`` version table, and
    ``create_all`` semantics; duplicate-object errors are tolerated only to
    adopt a database migrated before tracking began.
    """
    apply_alembic_base()
    migrations = discover_migrations(MIGRATIONS_DIR)
    if not migrations:
        # Fail loudly instead of running against a schema without RLS: this is
        # how a missing database/ directory in the image used to look (zero
        # migrations, confusing tenant-isolation failures).
        raise RuntimeError(f"no SQL migrations discovered under {MIGRATIONS_DIR}")
    pre = [m for m in migrations if m.version <= "010"]
    post = [m for m in migrations if m.version > "010"]
    results = []
    with psycopg.connect(psycopg_dsn(), autocommit=True) as conn:
        results.extend(MigrationRunner(conn).apply(pre))
    orm_engine = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        ExceptionsBase.metadata.create_all(orm_engine)
        # Alembic-first shadowing: alembic creates audit_logs without the
        # 000_init DEFAULT NOW() on created_at (000's CREATE TABLE IF NOT
        # EXISTS becomes a no-op), while 002 still sets NOT NULL — so the
        # probe INSERT omitting created_at would fail. Restore the default
        # the SQL chain owns; idempotent, fixture bootstrap only.
        with orm_engine.connect() as conn:
            conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN created_at SET DEFAULT NOW()"))
    finally:
        orm_engine.dispose()
    with psycopg.connect(psycopg_dsn(), autocommit=True) as conn:
        results.extend(MigrationRunner(conn).apply(post))
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    logger.info(
        "applied %d migrations: %s",
        len(migrations),
        ", ".join(f"{status}={count}" for status, count in sorted(counts.items())),
    )


def is_migrated(engine: sqlalchemy.Engine) -> bool:
    """Return True when the reconciliation schema is present in the database."""
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT to_regclass('public.reconciliation_runs') IS NOT NULL")
            ).scalar()
        )
