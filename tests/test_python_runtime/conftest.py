"""Shared test fixtures for Python Compute Runtime tests."""

from pathlib import Path
from typing import Any

import polars as pl
import pytest


@pytest.fixture
def sample_dataframe() -> pl.DataFrame:
    """Standard 5-row financial DataFrame for all pipeline tests."""
    return pl.DataFrame(
        {
            "account_id": ["A100", "A101", "A102", "A103", "A104"],
            "period": ["2026-Q1"] * 5,
            "amount": [1000.0, 2500.0, 0.0, 500.0, 7500.0],
            "department": ["Sales", "Engineering", "Sales", "Marketing", "Engineering"],
            "currency": ["USD", "USD", "EUR", "USD", "USD"],
        }
    )


@pytest.fixture
def sample_csv_path(tmp_path: Path, sample_dataframe: pl.DataFrame) -> str:
    """Write sample_dataframe to a temp CSV and return the path."""
    path = tmp_path / "test_data.csv"
    sample_dataframe.write_csv(path)
    return str(path)


class _FakeSession:
    """Session double that records the RLS statements it was asked to run."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: Any = None) -> None:
        """Record an executed statement; the real DB is not involved."""
        self.executed.append((str(statement), dict(params or {})))

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None


@pytest.fixture
def fake_rls_session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    """Replace the tenant middleware's DB session with a recording double.

    ``TenantAuthMiddleware`` takes an injectable ``session_factory`` so the
    boundary can be exercised without a live database (see the module
    docstring in ``apps/api/middleware.py``).  The Compute Runtime API tests
    are not database tests: they exercise the job submit/poll/cancel flow
    and the tenant header gate.  Swapping the factory keeps them
    database-free while still running the real middleware logic — header
    validation, role resolution, and the RLS tenant statement.

    The double still records the ``set_config('app.tenant_id', ...)``
    statement, so a test can assert the tenant context was set.
    """
    from apps.api import middleware as middleware_module

    session = _FakeSession()

    def _factory() -> _FakeSession:
        return session

    # The middleware resolves its session factory at construction time, and
    # Starlette builds the middleware stack lazily on the first request.
    # Patch the module global (covers a stack that is not built yet) and
    # any already-built instance (covers a stack built by an earlier test).
    monkeypatch.setattr(middleware_module, "_default_session_factory", _factory)
    monkeypatch.setattr(middleware_module, "_default_engine", None, raising=False)

    from apps.api.main import app

    stack = getattr(app, "middleware_stack", None)
    node = stack
    while node is not None:
        if isinstance(node, middleware_module.TenantAuthMiddleware):
            monkeypatch.setattr(node, "_session_factory", _factory, raising=False)
            break
        node = getattr(node, "app", None)
    return session
