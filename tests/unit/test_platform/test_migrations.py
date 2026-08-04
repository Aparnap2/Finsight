"""Tests for the structured migration discovery layer (``shared.migrations``).

Covers the declarative parsing of ``NNN_name.sql`` filenames into
:class:`~shared.migrations.Migration` models (version, name, sha256 checksum)
and the version-sorted discovery helper. The runner itself is exercised by the
integration suite against a real Postgres; no database is needed here.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.migrations import Migration, discover_migrations

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"


def test_migration_from_file_parses_version_name_path_and_checksum() -> None:
    """``Migration.from_file`` derives metadata from the filename and contents."""
    path = MIGRATIONS_DIR / "000_init.sql"
    migration = Migration.from_file(path)

    assert migration.version == "000"
    assert migration.name == "init"
    assert migration.path == path
    assert len(migration.checksum) == 64  # sha256 hex digest


def test_migration_checksum_is_sha256_of_file_contents() -> None:
    """The checksum equals the sha256 hex digest of the file bytes."""
    import hashlib

    path = MIGRATIONS_DIR / "010_tenant_backfill.sql"
    migration = Migration.from_file(path)
    assert migration.checksum == hashlib.sha256(path.read_bytes()).hexdigest()


def test_migration_rejects_unconventional_filename() -> None:
    """A filename that does not match ``NNN_name.sql`` is rejected."""
    with pytest.raises(ValueError, match="unrecognized migration filename"):
        Migration.from_file(Path("database/migrations/readme.txt"))


def test_discover_migrations_sorts_by_version() -> None:
    """Discovery returns every ``NNN_*.sql`` file in version order."""
    migrations = discover_migrations(MIGRATIONS_DIR)

    assert len(migrations) == 11
    assert [migration.version for migration in migrations] == [
        "000", "001", "002", "003", "004", "005", "006", "007", "008", "009", "010",
    ]
    # Each discovered migration is frozen and carries a non-empty checksum.
    for migration in migrations:
        assert migration.checksum
        with pytest.raises(ValidationError):
            setattr(migration, "version", "999")  # noqa: B010 — frozen model rejects assignment at runtime
