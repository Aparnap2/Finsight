"""Readiness probe resource lifecycle.

Health checks run on a timer. Building a fresh SQLAlchemy engine — and so a
fresh connection pool — on every probe leaks descriptors and Postgres
connections until the pool is garbage collected. These tests pin the
observable consequence of that defect: the number of engines created must not
grow with the number of probes.

The fake engine records construction and disposal without touching a database.
"""

from __future__ import annotations

from typing import Any

import pytest

import apps.api.observability as obs


class _FakeConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, statement: Any) -> None:
        if self._fail:
            raise RuntimeError("connection refused")


class _FakeEngine:
    """Minimal stand-in: counts connections and records disposal."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.connections_opened = 0
        self.disposed = False

    def connect(self) -> _FakeConnection:
        self.connections_opened += 1
        return _FakeConnection(fail=self._fail)

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture(autouse=True)
def _reset_engine_cache() -> Any:
    """Start and end each test from a clean module-level engine cache."""
    obs.dispose_readiness_engine()
    yield
    obs.dispose_readiness_engine()


def _install(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> dict[str, Any]:
    created: dict[str, Any] = {"engines": []}

    def fake_create_engine(*args: Any, **kwargs: Any) -> _FakeEngine:
        engine = _FakeEngine(fail=fail)
        created["engines"].append(engine)
        return engine

    monkeypatch.setattr(obs, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        obs, "get_settings", lambda: type("S", (), {"postgres_uri": "postgresql://fake"})()
    )
    return created


def test_repeated_probes_reuse_one_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ten probes must not create ten pools."""
    created = _install(monkeypatch)

    results = [obs.default_db_probe() for _ in range(10)]

    assert results == [True] * 10
    assert len(created["engines"]) == 1, "a new engine per probe leaks the pool"
    assert created["engines"][0].connections_opened == 10, "each probe still checks the DB"


def test_dispose_forces_a_fresh_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """After disposal the next probe rebuilds, and the old engine is closed."""
    created = _install(monkeypatch)

    assert obs.default_db_probe() is True
    first = created["engines"][0]
    obs.dispose_readiness_engine()
    assert first.disposed is True

    assert obs.default_db_probe() is True
    assert len(created["engines"]) == 2


def test_probe_fails_closed_when_the_database_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable database reports not-ready; it never raises."""
    _install(monkeypatch, fail=True)

    assert obs.default_db_probe() is False


def test_probe_failure_is_logged_with_its_trace(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A silent failure would hide an outage; the trace must be recorded."""
    _install(monkeypatch, fail=True)

    with caplog.at_level("ERROR"):
        obs.default_db_probe()

    records = [r for r in caplog.records if "readiness DB probe failed" in r.message]
    assert records, "probe failure produced no log record"
    assert records[0].exc_info is not None, "probe failure was logged without its traceback"
