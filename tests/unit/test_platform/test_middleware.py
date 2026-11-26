"""Tests for the tenant auth middleware (``apps.api.middleware``).

The middleware is a header/actor gate only: it never opens a database session.
RLS tenant wiring happens on each route's own session, because a GUC set in
middleware on a separate, short-lived session is rolled back before the route
query runs (see ``TestReconciliationSessionTenantContext``). These tests wire
the real middleware into a minimal FastAPI app and assert the authorization
outcomes, plus the routing exemptions for health/liveness/readiness.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.middleware import TenantAuthMiddleware

_VALID_HEADERS = {"X-Tenant-ID": "TENANT_A", "X-User-ID": "user_1", "X-Role": "analyst"}


def _build_app() -> FastAPI:
    """Build a minimal app with the real middleware and probe routes."""
    app = FastAPI()
    app.add_middleware(TenantAuthMiddleware)

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, Any]:
        return {"actor": request.state.actor}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    return app


class TestTenantAuthMiddleware:
    """Header validation and actor state."""

    def test_valid_request_sets_actor(self) -> None:
        client = TestClient(_build_app())
        resp = client.get("/probe", headers=_VALID_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == {
            "actor": {"tenant_id": "TENANT_A", "user_id": "user_1", "role": "analyst"}
        }

    def test_user_id_is_optional(self) -> None:
        client = TestClient(_build_app())
        resp = client.get("/probe", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "analyst"})
        assert resp.status_code == 200
        assert resp.json()["actor"]["user_id"] == ""

    def test_missing_headers_returns_401(self) -> None:
        client = TestClient(_build_app())
        resp = client.get("/probe")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing X-Tenant-ID or X-Role header"

    @pytest.mark.parametrize(
        "headers",
        [
            {"X-Tenant-ID": "TENANT_A"},
            {"X-Role": "analyst"},
            {},
        ],
    )
    def test_incomplete_headers_returns_401(self, headers: dict[str, str]) -> None:
        client = TestClient(_build_app())
        resp = client.get("/probe", headers=headers)
        assert resp.status_code == 401

    def test_unknown_role_returns_403(self) -> None:
        client = TestClient(_build_app())
        resp = client.get("/probe", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "ceo"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Unknown role: ceo"

    @pytest.mark.parametrize("path", ["/health", "/ready", "/live"])
    def test_health_paths_are_not_gated_on_tenant_headers(self, path: str) -> None:
        """Health/liveness/readiness must answer without tenant identity."""
        client = TestClient(_build_app())
        resp = client.get(path)
        assert resp.status_code == 200
