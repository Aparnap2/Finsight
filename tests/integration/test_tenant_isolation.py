"""Integration tests: tenant isolation enforced by Postgres Row-Level Security.

These tests require a real, reachable Postgres (the dockerized ``finsight``
instance) and are skipped when the database is unreachable. They bootstrap the
migrations 000-010 idempotently, create a NOLOGIN limited role that is subject
to RLS (the superuser bypasses RLS), and assert:

  a) A limited role without a tenant context sees no rows (RLS is deny-by-default)
  b) A limited role scoped to tenant A sees only tenant A's rows
  c) A limited role scoped to tenant B sees only tenant B's rows
  d) The superuser (table owner) bypasses RLS and sees all rows

The ``audit_logs`` table is used as the probe because it is tenant_id-boundary,
RLS-enabled, and accepts INSERTs (its only trigger prevents UPDATE/DELETE).
Because that trigger makes the table append-only, probe rows are given ids
unique per test run (UUID suffix) and are never deleted.

Migrations are applied by the Pydantic-driven ``shared.migrations`` runner:
each file is executed as one multi-statement psycopg3 ``ClientCursor`` call
(no hand-rolled SQL splitting), and applied versions are tracked in the
``schema_migrations`` table. The engine uses ``NullPool`` so every connection
starts with a clean session (no leaked ``SET ROLE`` or GUC state), and the RLS
policies are probed with an explicitly-set session-level ``app.tenant_id`` GUC
(the policy reads ``current_setting('app.tenant_id')``, which errors when the
GUC is absent).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from shared.migrations import MigrationRunner, discover_migrations

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)

ACME_TENANT_ID = "11111111-1111-4111-8111-111111111111"
GLOBEX_TENANT_ID = "22222222-2222-4222-8222-222222222222"

LIMITED_ROLE = "test_rls_limited"
PROBE_EVENT_TYPE = "row_inserted"
PROBE_PERIOD = "2026-06"


def _psycopg_dsn() -> str:
    """Translate the SQLAlchemy DSN (``postgresql+psycopg://``) to a psycopg DSN."""
    return DSN.replace("postgresql+psycopg://", "postgresql://", 1)


def _db_reachable(engine: sqlalchemy.Engine) -> bool:
    """Return True when the target database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any connectivity failure is treated the same
        logger.warning("integration DB unreachable, skipping: %s", exc)
        return False


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.fixture(scope="module")  # type: ignore[untyped-decorator]
def engine() -> sqlalchemy.Engine:
    """Engine bound to the integration database, with migrations + role applied.

    ``NullPool`` guarantees every ``engine.connect()`` opens a fresh session, so
    ``SET ROLE`` and GUC changes from one test can never leak into the next via
    a recycled pooled connection.
    """
    engine = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    if not _db_reachable(engine):
        pytest.skip("integration database not reachable")
    _apply_migrations()
    _ensure_limited_role(engine)
    yield engine
    engine.dispose()


def _apply_migrations() -> None:
    """Apply every migration file in version order via the structured runner.

    Uses a dedicated psycopg3 connection in autocommit mode; each file is
    executed as one multi-statement ``ClientCursor`` call. Idempotency comes
    from the ``schema_migrations`` version table; duplicate-object errors are
    tolerated only to adopt a database migrated before tracking began.
    """
    migrations = discover_migrations(MIGRATIONS_DIR)
    with psycopg.connect(_psycopg_dsn(), autocommit=True) as conn:
        results = MigrationRunner(conn).apply(migrations)
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    logger.info(
        "applied %d migrations: %s",
        len(migrations),
        ", ".join(f"{status}={count}" for status, count in sorted(counts.items())),
    )


def _ensure_limited_role(engine: sqlalchemy.Engine) -> None:
    """Create (idempotently) a NOLOGIN role subject to RLS with table grants."""
    with engine.connect() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
                f"'{LIMITED_ROLE}') THEN CREATE ROLE {LIMITED_ROLE} NOLOGIN; END IF; END $$;"
            )
        )
        conn.execute(text(f"GRANT CONNECT ON DATABASE finsight TO {LIMITED_ROLE}"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {LIMITED_ROLE}"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                f"TO {LIMITED_ROLE}"
            )
        )


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.fixture(scope="module")  # type: ignore[untyped-decorator]
def probe_rows(engine: sqlalchemy.Engine) -> Generator[tuple[str, str], None, None]:
    """Insert one audit_logs row per tenant; yield the two row ids.

    Row ids carry a UUID suffix unique to this test run because ``audit_logs``
    is append-only: migration 007 installs ``trg_prevent_update_delete_audit_logs``
    so DELETE always raises. Rows from earlier runs persist, but the unique
    suffix keeps this run's probe rows unambiguous (RLS assertions filter by id).
    """
    row_a = f"intg_tenant_a_{uuid4().hex[:8]}"
    row_b = f"intg_tenant_b_{uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_logs (id, tenant_id, period, event_type, event_data) "
                "VALUES (:id, :tenant_id, :period, :event_type, '{}'::jsonb)"
            ),
            {"id": row_a, "tenant_id": ACME_TENANT_ID, "period": PROBE_PERIOD,
             "event_type": PROBE_EVENT_TYPE},
        )
        conn.execute(
            text(
                "INSERT INTO audit_logs (id, tenant_id, period, event_type, event_data) "
                "VALUES (:id, :tenant_id, :period, :event_type, '{}'::jsonb)"
            ),
            {"id": row_b, "tenant_id": GLOBEX_TENANT_ID, "period": PROBE_PERIOD,
             "event_type": PROBE_EVENT_TYPE},
        )
    yield row_a, row_b


def _count_rows(engine: sqlalchemy.Engine, row_ids: tuple[str, str]) -> int:
    with engine.connect() as conn:
        return cast(
            int,
            conn.execute(
                text("SELECT count(*) FROM audit_logs WHERE id IN (:ida, :idb)"),
                {"ida": row_ids[0], "idb": row_ids[1]},
            ).scalar_one(),
        )


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.mark.integration  # type: ignore[untyped-decorator]
def test_a_no_tenant_context_sees_nothing(
    engine: sqlalchemy.Engine, probe_rows: tuple[str, str]
) -> None:
    """RLS is deny-by-default: a limited role without a tenant context sees no rows.

    The RLS policy evaluates ``current_setting('app.tenant_id')``, which errors
    when the GUC is absent; an explicit empty value stands for "no context".
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', '', false)"))
        conn.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        count = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE id IN (:ida, :idb)"),
            {"ida": probe_rows[0], "idb": probe_rows[1]},
        ).scalar_one()
        conn.execute(text("RESET ROLE"))
    assert count == 0


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.mark.integration  # type: ignore[untyped-decorator]
def test_b_tenant_a_sees_only_own_rows(
    engine: sqlalchemy.Engine, probe_rows: tuple[str, str]
) -> None:
    """Scoped to tenant A, the limited role sees A's row but not B's."""
    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, false)"), {"tid": ACME_TENANT_ID}
        )
        conn.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        seen_a = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE id = :id"),
            {"id": probe_rows[0]},
        ).scalar_one()
        seen_b = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE id = :id"),
            {"id": probe_rows[1]},
        ).scalar_one()
        conn.execute(text("RESET ROLE"))
        conn.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    assert seen_a == 1
    assert seen_b == 0


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.mark.integration  # type: ignore[untyped-decorator]
def test_c_tenant_b_sees_only_own_rows(
    engine: sqlalchemy.Engine, probe_rows: tuple[str, str]
) -> None:
    """Scoped to tenant B, the limited role sees B's row but not A's."""
    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, false)"), {"tid": GLOBEX_TENANT_ID}
        )
        conn.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        seen_a = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE id = :id"),
            {"id": probe_rows[0]},
        ).scalar_one()
        seen_b = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE id = :id"),
            {"id": probe_rows[1]},
        ).scalar_one()
        conn.execute(text("RESET ROLE"))
        conn.execute(text("SELECT set_config('app.tenant_id', '', false)"))
    assert seen_a == 0
    assert seen_b == 1


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.mark.integration  # type: ignore[untyped-decorator]
def test_d_superuser_bypasses_rls(engine: sqlalchemy.Engine, probe_rows: tuple[str, str]) -> None:
    """The superuser (table owner) bypasses RLS and sees all rows regardless of context."""
    assert _count_rows(engine, probe_rows) == 2


# pytest does not ship type stubs; the decorator type is Any under strict mypy.
@pytest.mark.integration  # type: ignore[untyped-decorator]
def test_tenant_ids_populated_across_boundary_tables(engine: sqlalchemy.Engine) -> None:
    """010 backfill left no NULL tenant_id rows across the 27 tenant-scoped tables."""
    tables = [
        "review_decisions", "action_items", "commentary_versions", "audit_logs",
        "pipeline_runs", "assertions_db", "tool_result_cache", "data_quality_snapshots",
        "policy_decision_logs", "bridge_analysis_results", "variance_snapshots",
        "root_cause_findings_db", "entities", "gl_accounts", "trial_balance",
        "budget_lines", "forecast_lines", "actuals", "headcount_data", "vendor_invoices",
        "sales_pipeline", "agent_runs", "variances", "root_causes", "commentary_drafts",
        "scenarios", "review_logs",
    ]
    with engine.connect() as conn:
        for table in tables:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            ).scalar_one_or_none()
            if not exists:
                continue
            nulls = conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")
            ).scalar_one()
            assert nulls == 0, f"{table} has {nulls} NULL tenant_id rows"
