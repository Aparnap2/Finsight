"""Integration tests: RLS tenant scoping for the reconciliation workflow.

The reconciliation tables carry ``ENABLE`` + ``FORCE ROW LEVEL SECURITY`` with a
``tenant_id = current_setting('app.tenant_id', true)::uuid`` policy. This file
proves the API's tenant wiring actually reaches a query: ``_set_tenant_context``
is applied to the *same* session that runs the query (the middleware used to
set it on a separate, short-lived session, where the transaction-scoped GUC was
rolled back before the route ran).

Requires a reachable Postgres (``FINSIGHT_TEST_DSN``); skipped otherwise. A
``NOLOGIN`` limited role is used because the owning superuser bypasses RLS.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from alembic import command

logger = logging.getLogger(__name__)

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)

TENANT_A = "7d6f8b65-5e40-55b5-967f-69b85912dd87"  # Acme
TENANT_B = "ea7639b2-4a8e-5954-84a2-f8630e89d206"  # Globex
LIMITED_ROLE = "test_recon_rls_limited"
LOGIN_ROLE = "test_recon_rls_login"


def _db_reachable() -> bool:
    try:
        engine = create_engine(DSN, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception as exc:  # noqa: BLE001 - unreachable DB skips the module
        logger.warning("integration DB unreachable, skipping: %s", exc)
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="Postgres unreachable")


@pytest.fixture(scope="module")
def engine() -> Generator[sqlalchemy.Engine, None, None]:
    """Engine with the reconciliation schema and a limited role applied.

    ``NullPool`` guarantees every ``connect()`` is a fresh session, so the
    ``SET ROLE`` used to exercise RLS cannot leak into a later test through a
    recycled pooled connection.
    """
    engine = create_engine(DSN, pool_pre_ping=True, poolclass=NullPool)
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DSN)
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
                f"'{LIMITED_ROLE}') THEN CREATE ROLE {LIMITED_ROLE} NOLOGIN; END IF; END $$;"
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {LIMITED_ROLE}"))
        conn.execute(text(f"GRANT SELECT ON reconciliation_runs TO {LIMITED_ROLE}"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def limited_engine(engine: sqlalchemy.Engine) -> Generator[sqlalchemy.Engine, None, None]:
    """Engine that *connects* as a non-superuser role, so every connection is
    subject to RLS (the owning superuser always bypasses it)."""
    from sqlalchemy.engine import make_url

    url = make_url(DSN)
    import secrets

    password = secrets.token_urlsafe(24)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
                f"'{LOGIN_ROLE}') THEN CREATE ROLE {LOGIN_ROLE} LOGIN NOSUPERUSER; "
                "END IF; END $$;"
            )
        )
        conn.execute(text(f"ALTER ROLE {LOGIN_ROLE} WITH PASSWORD '{password}'"))
        conn.execute(text(f"GRANT CONNECT ON DATABASE {url.database} TO {LOGIN_ROLE}"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {LOGIN_ROLE}"))
        conn.execute(text(f"GRANT SELECT ON reconciliation_runs TO {LOGIN_ROLE}"))
    login_engine = create_engine(url.set(username=LOGIN_ROLE, password=password))
    yield login_engine
    login_engine.dispose()


@pytest.fixture()
def probe_runs(engine: sqlalchemy.Engine) -> tuple[str, str]:
    """Insert one run per tenant; return ``(run_a, run_b)`` ids."""
    run_a = str(uuid4())
    run_b = str(uuid4())
    session_a = str(uuid4())
    session_b = str(uuid4())
    with engine.begin() as conn:
        for session_id, tenant_id in ((session_a, TENANT_A), (session_b, TENANT_B)):
            conn.execute(
                text(
                    "INSERT INTO import_sessions "
                    "(session_id, tenant_id, actor_id, period_start, period_end, status) "
                    "VALUES (:sid, :tid, 'rls-probe', '2026-01-01', '2026-01-31', 'READY')"
                ),
                {"sid": session_id, "tid": tenant_id},
            )
        for run_id, session_id, tenant_id in (
            (run_a, session_a, TENANT_A),
            (run_b, session_b, TENANT_B),
        ):
            conn.execute(
                text(
                    "INSERT INTO reconciliation_runs "
                    "(run_id, session_id, tenant_id, actor_id, idempotency_key, status, "
                    " engine_version, input_fingerprint, input_snapshot_ref) "
                    "VALUES (:rid, :sid, :tid, 'rls-probe', :key, 'SUCCEEDED', "
                    " 'dev', :fp, 'probe')"
                ),
                {
                    "rid": run_id,
                    "sid": session_id,
                    "tid": tenant_id,
                    "key": f"rls-{run_id}",
                    "fp": "0" * 64,
                },
            )
    return run_a, run_b


def _visible_run_ids(session: Session, run_a: str, run_b: str) -> list[str]:
    return list(
        session.execute(
            text("SELECT run_id FROM reconciliation_runs WHERE run_id IN (:a, :b) ORDER BY run_id"),
            {"a": run_a, "b": run_b},
        ).scalars()
    )


def _scope(session: Session, tenant_id: str) -> None:
    """Set the RLS tenant GUC for the current transaction."""
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


def test_without_tenant_context_the_route_sees_nothing(
    engine: sqlalchemy.Engine, probe_runs: tuple[str, str]
) -> None:
    """A limited role with no GUC sees no rows — including after another
    session set and rolled back the GUC (the old middleware behaviour)."""
    with Session(engine) as stale:
        stale.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        _scope(stale, TENANT_A)
    # The context above died with its transaction; a fresh query starts blind.

    with Session(engine) as session:
        session.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        assert _visible_run_ids(session, *probe_runs) == []


def test_tenant_context_scopes_rows_to_own_tenant(
    engine: sqlalchemy.Engine, probe_runs: tuple[str, str]
) -> None:
    """Setting the GUC on the query session reveals only that tenant's row."""
    run_a, run_b = probe_runs
    with Session(engine) as session:
        session.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        _scope(session, TENANT_A)
        assert _visible_run_ids(session, run_a, run_b) == [run_a]

    with Session(engine) as session:
        session.execute(text(f"SET ROLE {LIMITED_ROLE}"))
        _scope(session, TENANT_B)
        assert _visible_run_ids(session, run_a, run_b) == [run_b]


def test_owner_superuser_bypasses_rls(
    engine: sqlalchemy.Engine, probe_runs: tuple[str, str]
) -> None:
    """The superuser sees both probe rows regardless of GUC (fixture sanity)."""
    with Session(engine) as session:
        assert _visible_run_ids(session, *probe_runs) == sorted(probe_runs)


def test_route_session_reapplies_tenant_after_commit(
    limited_engine: sqlalchemy.Engine,
    probe_runs: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_db_session`` keeps the tenant context across a mid-request commit.

    Routes commit and then read again (``session.get`` after ``commit``, or an
    expired-attribute refresh). A one-shot ``set_config`` is transaction-scoped
    and lost at that point, so the session must re-apply it on every transaction.
    """
    from types import SimpleNamespace

    import apps.api.middleware as middleware
    from apps.api import reconciliation_routes

    run_a, run_b = probe_runs
    monkeypatch.setattr(middleware, "_default_session_factory", lambda: Session(limited_engine))

    request = SimpleNamespace(
        state=SimpleNamespace(actor={"tenant_id": TENANT_A, "user_id": "u", "role": "cfo"})
    )
    session = reconciliation_routes._db_session(request)  # type: ignore[arg-type]
    try:
        assert _visible_run_ids(session, run_a, run_b) == [run_a]
        session.commit()
        assert _visible_run_ids(session, run_a, run_b) == [run_a]
    finally:
        session.close()
