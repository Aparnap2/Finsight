"""Pydantic-driven PostgreSQL migration discovery and application (shared layer).

Replaces hand-rolled SQL statement splitting with a declarative description of
each migration file and a small runner that executes the full file text through
psycopg3's native multi-statement ``ClientCursor`` support. Applied versions are
tracked in a ``schema_migrations`` table so idempotency comes from the version
table rather than from re-parsing SQL or swallowing arbitrary errors.

Transaction model
-----------------
Each migration file is executed as one multi-statement call. Files that contain
their own ``BEGIN; ... COMMIT;`` (e.g. 000/001/002/007/009/010) manage their own
transaction; files without an explicit block (003/004/005/006/008) are wrapped
in an implicit transaction by PostgreSQL because a multi-statement query is
atomic. The connection is opened with ``autocommit=True``; a failed file can
still leave the session in a failed-transaction state (when the file opened an
explicit ``BEGIN``), so :meth:`MigrationRunner._reset_transaction` rolls back
after every file to guarantee the next file starts from a clean session.

The runner tolerates ``duplicate object``-family errors *only* to bootstrap
against a database where migrations were already applied before tracking began
(e.g. the live dev database). Once a version is recorded in
``schema_migrations`` it is skipped purely via the version table.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

#: Name of the table recording applied migration versions.
SCHEMA_MIGRATIONS_TABLE = "schema_migrations"

#: Error classes indicating the referenced object already exists. Raised when a
#: migration is re-run against a database that was migrated before tracking began.
_DUPLICATE_ERRORS = (
    psycopg.errors.DuplicateObject,
    psycopg.errors.DuplicateTable,
    psycopg.errors.DuplicateFunction,
)

#: Matches migration filenames of the form ``NNN_name.sql`` (zero-padded version).
_FILENAME_RE = re.compile(r"(\d{3})_(.+)\.sql")


# pydantic mypy plugin unavailable on mypy 2.x (see pyproject.toml)
class Migration(BaseModel):
    """Declarative description of one SQL migration file."""

    model_config = ConfigDict(frozen=True)

    version: str
    name: str
    path: Path
    checksum: str

    @classmethod
    def from_file(cls, path: Path) -> Migration:
        """Build a :class:`Migration` from a ``NNN_name.sql`` file.

        The version and name are parsed from the filename convention; the
        checksum is the sha256 of the file contents. Raises ``ValueError`` for
        a filename that does not match the ``NNN_name.sql`` convention.
        """
        match = _FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise ValueError(f"unrecognized migration filename: {path.name}")
        version, name = match.groups()
        return cls(
            version=version,
            name=name,
            path=path,
            checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
        )


# pydantic mypy plugin unavailable on mypy 2.x (see pyproject.toml)
class MigrationResult(BaseModel):
    """Outcome of running (or skipping) one migration."""

    model_config = ConfigDict(frozen=True)

    version: str
    name: str
    applied_at: datetime
    status: str  # "applied" | "skipped" | "already_applied"


class MigrationRunner:
    """Applies migrations in version order using psycopg3 multi-statement execution.

    The wrapped connection must be in autocommit mode. Each pending migration is
    executed as a single multi-statement ``ClientCursor`` call; successes are
    recorded in ``schema_migrations``, versions already present are skipped, and
    ``duplicate object`` errors are tolerated and recorded as ``already_applied``
    so a pre-migrated database can be adopted gracefully.
    """

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        """Store the autocommit connection used for all migration work."""
        self._conn = conn

    def apply(self, migrations: Sequence[Migration]) -> list[MigrationResult]:
        """Apply every migration not yet recorded in ``schema_migrations``.

        Returns one :class:`MigrationResult` per migration in input order.
        """
        self._ensure_schema_migrations()
        applied_versions = self._applied_versions()
        results: list[MigrationResult] = []
        for migration in migrations:
            if migration.version in applied_versions:
                logger.debug(
                    "migration %s (%s) already applied, skipping",
                    migration.version,
                    migration.name,
                )
                results.append(
                    MigrationResult(
                        version=migration.version,
                        name=migration.name,
                        applied_at=datetime.now(UTC),
                        status="skipped",
                    )
                )
                continue
            results.append(self._apply_one(migration))
        return results

    def _ensure_schema_migrations(self) -> None:
        """Create the ``schema_migrations`` table if it does not exist."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} ("
                "version text PRIMARY KEY,"
                "name text NOT NULL,"
                "checksum text NOT NULL,"
                "applied_at timestamptz NOT NULL DEFAULT now(),"
                "status text NOT NULL)"
            )

    def _applied_versions(self) -> set[str]:
        """Return the set of versions recorded in ``schema_migrations``."""
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT version FROM {SCHEMA_MIGRATIONS_TABLE}")
            return {row[0] for row in cur.fetchall()}

    def _apply_one(self, migration: Migration) -> MigrationResult:
        """Execute one migration file and record its outcome.

        The full file text is run in a single multi-statement call via
        ``ClientCursor`` (psycopg3 requirement for multi-statement execution).
        ``duplicate object`` errors are tolerated and recorded as
        ``already_applied``; any other error propagates.
        """
        with psycopg.ClientCursor(self._conn) as cur:
            try:
                cur.execute(migration.path.read_text())
                status = "applied"
            except _DUPLICATE_ERRORS as exc:
                status = "already_applied"
                logger.warning(
                    "migration %s (%s) raised a duplicate-object error; "
                    "recording as already applied: %s",
                    migration.version,
                    migration.name,
                    exc.diag.message_primary,
                )
            finally:
                self._reset_transaction()
        return self._record(migration, status)

    def _record(self, migration: Migration, status: str) -> MigrationResult:
        """Insert an applied-migration row and return the matching result."""
        applied_at = datetime.now(UTC)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {SCHEMA_MIGRATIONS_TABLE} "
                "(version, name, checksum, applied_at, status) "
                "VALUES (%s, %s, %s, %s, %s)",
                (migration.version, migration.name, migration.checksum, applied_at, status),
            )
        return MigrationResult(
            version=migration.version,
            name=migration.name,
            applied_at=applied_at,
            status=status,
        )

    def _reset_transaction(self) -> None:
        """Roll back any open (or failed) transaction so the session is idle.

        A migration file that opens its own ``BEGIN`` leaves the session in a
        failed-transaction state when it errors; rolling back (a no-op when the
        session is already idle) keeps the next file from starting poisoned.
        """
        if self._conn.pgconn.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            self._conn.rollback()


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    """Return migrations found in ``migrations_dir``, sorted by version.

    Only files matching the ``NNN_name.sql`` convention are considered.
    """
    return sorted(
        (Migration.from_file(path) for path in migrations_dir.glob("[0-9][0-9][0-9]_*.sql")),
        key=lambda migration: migration.version,
    )
