"""Unit tests for the PostgreSQL DSN normalization contract.

SQLAlchemy resolves a bare ``postgresql://`` DSN to the psycopg 2 dialect,
but this project ships psycopg 3 (``psycopg[binary]``) and not psycopg 2, so
engine creation raised ``ModuleNotFoundError`` for every default or
env-supplied plain DSN. These tests pin the normalization at the
configuration boundary: scheme only, everything else byte-for-byte.

No database connection is opened; the engine tests only prove which dialect
SQLAlchemy loaded.
"""

import pytest
from sqlalchemy import create_engine

from shared.config.config import Settings, normalize_postgres_dsn

QUALIFIED = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"


@pytest.fixture(autouse=True)
def _clear_dsn_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these tests independent of ambient CI environment or a local .env."""
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    monkeypatch.delenv("MIGRATION_POSTGRES_URI", raising=False)


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_default_dsn_uses_the_psycopg3_dialect() -> None:
    assert _settings().postgres_uri == QUALIFIED


def test_environment_plain_dsn_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URI", "postgresql://app:secret@db:6543/finance")
    assert _settings().postgres_uri == "postgresql+psycopg://app:secret@db:6543/finance"


def test_environment_qualified_dsn_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_URI", QUALIFIED)
    assert _settings().postgres_uri == QUALIFIED


def test_migration_dsn_omitted_stays_empty() -> None:
    settings = _settings()
    assert settings.migration_postgres_uri == ""
    assert (settings.migration_postgres_uri or settings.postgres_uri) == QUALIFIED


def test_migration_dsn_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATION_POSTGRES_URI", "postgresql://migrator:migrate@db:5432/finance")
    assert _settings().migration_postgres_uri == (
        "postgresql+psycopg://migrator:migrate@db:5432/finance"
    )


def test_credentials_and_query_parameters_are_preserved_exactly() -> None:
    dsn = (
        "postgresql://svc%40app:p%40ss%2Fword@db.internal.example:6543/finance"
        "?sslmode=require&application_name=finsight&options=-c%20statement_timeout%3D30000"
    )
    normalized = normalize_postgres_dsn(dsn)
    assert normalized == dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    assert "p%40ss%2Fword" in normalized
    assert normalized.endswith(
        "?sslmode=require&application_name=finsight&options=-c%20statement_timeout%3D30000"
    )


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://app:secret@db:5432/finance",
        "postgresql+psycopg2://app:secret@db:5432/finance",
        "sqlite:///:memory:",
        "mysql://app:secret@db:3306/finance",
    ],
)
def test_other_schemes_are_left_alone(dsn: str) -> None:
    """An explicitly chosen driver is a deployment decision, not ours to rewrite."""
    assert normalize_postgres_dsn(dsn) == dsn


def test_empty_dsn_is_a_no_op() -> None:
    """Empty ``migration_postgres_uri`` must stay empty, not become a driver DSN.

    Callers rely on ``migration_postgres_uri or postgres_uri``; normalizing an
    empty string would silently pin migrations to the runtime DSN and make the
    fallback indistinguishable from an explicit override.
    """
    assert normalize_postgres_dsn("") == ""


def test_libpq_postgres_alias_is_normalized() -> None:
    """``postgres://`` is a libpq alias SQLAlchemy does not accept; it is ours."""
    assert normalize_postgres_dsn("postgres://app:secret@db:5432/finance") == (
        "postgresql+psycopg://app:secret@db:5432/finance"
    )


def test_sqlalchemy_selects_the_psycopg_dialect() -> None:
    """The normalized DSN resolves to the installed driver without connecting."""
    engine = create_engine(_settings().postgres_uri)
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    engine.dispose()
