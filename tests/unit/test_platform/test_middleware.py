"""Tests for the tenant auth middleware (``apps.api.middleware``).

The middleware is exercised through a minimal FastAPI app wired with the real
``TenantAuthMiddleware`` and a fake session factory recording executed SQL, so
no Postgres connection is ever attempted. A handful of tests also run against
the real ``apps.api.main`` app to confirm the middleware is registered in the
production wiring.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.middleware import TenantAuthMiddleware

_VALID_HEADERS = {"X-Tenant-ID": "TENANT_A", "X-User-ID": "user_1", "X-Role": "analyst"}


class FakeSession:
    """A context-manager session that records executed statements."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, str]]] = []

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: object) -> None:
        """Exit the context manager without suppressing exceptions."""

    def execute(self, statement: Any, params: dict[str, str] | None = None) -> None:
        self.executed.append((str(statement), params or {}))


def _build_app() -> tuple[FastAPI, list[FakeSession]]:
    """Build a minimal app with the real middleware and a probe route.

    Returns the app and the list of sessions created by the injected fake
    session factory.
    """
    sessions: list[FakeSession] = []

    def factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    app = FastAPI()
    app.add_middleware(TenantAuthMiddleware, session_factory=factory)

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, Any]:
        return {"actor": request.state.actor}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app, sessions


class TestTenantAuthMiddleware:
    """Header validation, actor state and RLS tenant context wiring."""

    def test_valid_request_sets_actor_and_tenant_context(self) -> None:
        app, sessions = _build_app()
        client = TestClient(app)
        resp = client.get("/probe", headers=_VALID_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {
            "actor": {"tenant_id": "TENANT_A", "user_id": "user_1", "role": "analyst"}
        }
        assert len(sessions) == 1
        statement, params = sessions[0].executed[0]
        assert "set_config" in statement
        assert "app.tenant_id" in statement
        assert params == {"tenant_id": "TENANT_A"}

    def test_user_id_is_optional(self) -> None:
        app, sessions = _build_app()
        client = TestClient(app)
        resp = client.get("/probe", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "analyst"})
        assert resp.status_code == 200
        assert resp.json()["actor"]["user_id"] == ""
        assert len(sessions) == 1

    def test_missing_headers_returns_401(self) -> None:
        app, sessions = _build_app()
        client = TestClient(app)
        resp = client.get("/probe")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing X-Tenant-ID or X-Role header"
        assert sessions == []

    @pytest.mark.parametrize(
        "headers",
        [
            {"X-Tenant-ID": "TENANT_A"},
            {"X-Role": "analyst"},
            {},
        ],
    )
    def test_incomplete_headers_returns_401(self, headers: dict[str, str]) -> None:
        app, sessions = _build_app()
        client = TestClient(app)
        resp = client.get("/probe", headers=headers)
        assert resp.status_code == 401
        assert sessions == []

    def test_unknown_role_returns_403(self) -> None:
        app, sessions = _build_app()
        client = TestClient(app)
        resp = client.get("/probe", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "ceo"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Unknown role: ceo"
        assert sessions == []

    def test_health_is_excluded_from_tenant_context(self) -> None:
        app, sessions = _build_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert sessions == []


class TestRealAppWiring:
    """The real ``apps.api.main`` app has the middleware registered."""

    def test_health_excluded_on_real_app(self) -> None:
        from apps.api.main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200

    def test_missing_headers_returns_401_on_real_app(self) -> None:
        from apps.api.main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/status")
            assert resp.status_code == 401

    def test_unknown_role_returns_403_on_real_app(self) -> None:
        from apps.api.main import app

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/status", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "ceo"}
            )
            assert resp.status_code == 403
