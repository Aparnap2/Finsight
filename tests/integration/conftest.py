"""Integration-tier fixtures.

The only job here is to make schema bootstrap explicit and order-independent.

Previously the schema was created as a side effect of whichever module ran
first (``test_ledger_rls`` sorts before the reconciliation modules). The
full-directory run therefore passed while a single-module run against a fresh
database failed with ``relation ... does not exist``. Since reproducible
initialization is a release requirement, the session applies the documented
migration sequence once, up front, regardless of which tests are selected.

The fixture deliberately does *not* skip the session when the database is
unreachable: several integration modules exercise code paths that need no
database at all, and they must keep running. Modules that do need Postgres keep
their own reachability guards.
"""

from __future__ import annotations

import pytest

from tests.integration import _schema_bootstrap


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_schema() -> None:
    """Apply the documented migration sequence once per session (idempotent)."""
    if not _schema_bootstrap.db_reachable():
        return
    _schema_bootstrap.apply_migrations()
