"""Authorization boundary tests (APA-94 slice 3).

The tenant boundary has three layers, and each has a different failure
mode.  This module pins the behaviour of the two layers that decide
*whether a request may proceed at all*:

1. **Header gate** (``apps/api/middleware.py``) — a request without
   ``X-Tenant-ID``/``X-Role`` is 401; a request with a role outside the
   known set is 403.  Both are refused **before any database session is
   opened**, so an unauthorized caller cannot cause a query.
2. **Actor binding** — the tenant that the request runs under is the one
   in the header, and it is written into the RLS session context, so the
   database enforces the same boundary the middleware asserted.
3. **Role validity** — the role must be one the RBAC matrix knows.

The third layer, *role → permission* enforcement per action, is **not**
wired into the API: ``finplatform.rbac.matrix.check_permission`` is
referenced by no production module.  That is recorded as a known gap by
``test_role_permission_enforcement_is_not_wired_to_the_api`` rather than
being papered over with a passing test, because an API that accepts a
role without checking what the role may do is a real limitation, not a
test-coverage detail.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.middleware import TenantAuthMiddleware
from finplatform.rbac.matrix import ROLE_PERMISSIONS, check_permission

#: Every role the platform knows. A role outside this set is refused.
KNOWN_ROLES = tuple(sorted(ROLE_PERMISSIONS))


class RecordingSession:
    """Session double that records the SQL it was asked to run."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> RecordingSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Exit the context manager without suppressing exceptions."""

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.executed.append((str(statement), dict(params or {})))


def _build_app() -> tuple[FastAPI, list[RecordingSession]]:
    """Build an app with the real middleware and a recording session factory.

    Returns the app and the list of sessions the middleware opened. A
    session appears in that list only if the request got past the header
    gate — which is exactly the property under test.
    """
    sessions: list[RecordingSession] = []

    def factory() -> RecordingSession:
        session = RecordingSession()
        sessions.append(session)
        return session

    app = FastAPI()
    app.add_middleware(TenantAuthMiddleware, session_factory=factory)

    @app.get("/protected")
    async def protected(request: Request) -> dict[str, Any]:
        return {"actor": request.state.actor}

    @app.post("/protected")
    async def protected_post(request: Request) -> dict[str, Any]:
        return {"actor": request.state.actor}

    return app, sessions


class TestAuthorizationBeforeDataAccess:
    """A refused request must not reach the database."""

    def test_missing_tenant_opens_no_session(self) -> None:
        """No X-Tenant-ID: 401, and the database is never touched."""
        app, sessions = _build_app()
        response = TestClient(app).get("/protected", headers={"X-Role": "analyst"})
        assert response.status_code == 401
        assert response.json() == {"detail": "Missing X-Tenant-ID or X-Role header"}
        assert sessions == []

    def test_missing_role_opens_no_session(self) -> None:
        """No X-Role: 401, and the database is never touched."""
        app, sessions = _build_app()
        response = TestClient(app).get("/protected", headers={"X-Tenant-ID": "TENANT_A"})
        assert response.status_code == 401
        assert sessions == []

    def test_unknown_role_opens_no_session(self) -> None:
        """A role outside the known set: 403, and the database is never touched."""
        app, sessions = _build_app()
        response = TestClient(app).get(
            "/protected", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "ceo"}
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "Unknown role: ceo"}
        assert sessions == []

    def test_authorized_request_opens_exactly_one_session(self) -> None:
        """The contrast case: a permitted request does reach the database."""
        app, sessions = _build_app()
        response = TestClient(app).get(
            "/protected", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "analyst"}
        )
        assert response.status_code == 200
        assert len(sessions) == 1


class TestActorBinding:
    """The header tenant is the tenant the request runs under."""

    def test_rls_context_carries_the_header_tenant(self) -> None:
        """The tenant written into the session context is the header's tenant."""
        app, sessions = _build_app()
        response = TestClient(app).get(
            "/protected", headers={"X-Tenant-ID": "TENANT_B", "X-Role": "analyst"}
        )
        assert response.status_code == 200
        assert response.json()["actor"]["tenant_id"] == "TENANT_B"
        statement, params = sessions[0].executed[0]
        assert "set_config" in statement
        assert "app.tenant_id" in statement
        assert params == {"tenant_id": "TENANT_B"}

    def test_each_tenant_gets_its_own_context(self) -> None:
        """Two tenants produce two different RLS contexts — no bleed."""
        app, sessions = _build_app()
        client = TestClient(app)
        client.get("/protected", headers={"X-Tenant-ID": "TENANT_A", "X-Role": "analyst"})
        client.get("/protected", headers={"X-Tenant-ID": "TENANT_B", "X-Role": "analyst"})
        tenants = [params["tenant_id"] for _, params in (s.executed[0] for s in sessions)]
        assert tenants == ["TENANT_A", "TENANT_B"]

    def test_actor_tenant_is_the_header_tenant_not_the_body(self) -> None:
        """A caller cannot name a different tenant in the request body.

        The boundary is the header; nothing in the body can move the
        request to another tenant's rows.
        """
        app, sessions = _build_app()
        response = TestClient(app).post(
            "/protected",
            headers={"X-Tenant-ID": "TENANT_A", "X-Role": "analyst"},
            json={"tenant_id": "TENANT_B"},
        )
        assert response.status_code == 200
        assert response.json()["actor"]["tenant_id"] == "TENANT_A"
        assert sessions[0].executed[0][1] == {"tenant_id": "TENANT_A"}


class TestRoleValidity:
    """The role must be one the platform knows."""

    @pytest.mark.parametrize("role", KNOWN_ROLES)
    def test_every_known_role_is_accepted(self, role: str) -> None:
        """Each role in the RBAC matrix passes the header gate."""
        app, sessions = _build_app()
        response = TestClient(app).get(
            "/protected", headers={"X-Tenant-ID": "TENANT_A", "X-Role": role}
        )
        assert response.status_code == 200
        assert response.json()["actor"]["role"] == role
        assert len(sessions) == 1

    @pytest.mark.parametrize("role", ["ceo", "intern", "ADMIN", "analyst "])
    def test_unknown_roles_are_refused(self, role: str) -> None:
        """Anything outside the matrix is refused, including near-misses."""
        app, sessions = _build_app()
        response = TestClient(app).get(
            "/protected", headers={"X-Tenant-ID": "TENANT_A", "X-Role": role}
        )
        assert response.status_code == 403
        assert sessions == []

    def test_empty_role_is_treated_as_missing(self) -> None:
        """An empty role header is *missing*, so 401 — not 403.

        The middleware checks presence before validity, so a header that is
        present but empty takes the missing-header path. Both are refusals
        that open no session; only the status code differs.
        """
        app, sessions = _build_app()
        response = TestClient(app).get(
            "/protected", headers={"X-Tenant-ID": "TENANT_A", "X-Role": ""}
        )
        assert response.status_code == 401
        assert sessions == []

    def test_role_permission_enforcement_is_not_wired_to_the_api(self) -> None:
        """Record the gap: roles are validated, but not checked per action.

        The middleware proves the *role* is known; it does not ask the
        RBAC matrix whether that role may perform the requested action.
        ``check_permission`` is referenced by no production module, so a
        caller holding a valid but insufficient role (for example
        ``analyst``, which holds no ``approve_budget``) is not refused at
        the API boundary today.

        This test states that limitation explicitly.  It is written to
        FAIL if the API ever starts enforcing role permissions without
        this test being updated, so the change cannot land silently.
        """
        import finplatform.rbac.matrix as matrix_module

        production_callers = {
            path
            for path in (
                "apps/api/middleware.py",
                "apps/api/routes.py",
                "apps/api/execution_routes.py",
                "apps/api/approvals.py",
                "apps/api/observations.py",
            )
        }
        sources = {
            path: source
            for path in production_callers
            if (source := _read_source(path)) is not None
        }
        enforcing = [
            path
            for path, source in sources.items()
            if "check_permission" in source or "permissions_for" in source
        ]
        assert enforcing == [], (
            "role-permission enforcement now exists in "
            f"{enforcing} — update this test to assert the new behaviour"
        )
        # The matrix itself remains fail-closed and is the reference the
        # wiring would use.
        assert check_permission("analyst", "approve_budget") is False
        assert matrix_module.permissions_for("analyst")


class TestComputeRuntimeTenantAttribution:
    """The compute runtime takes its tenant from the request body, not the actor.

    ``JobSubmitRequest.tenant_id`` (``apps/api/schemas.py:224``) defaults to
    ``"CF001"`` and is taken straight from the body, so a caller whose header
    says ``TENANT_A`` can label a job ``TENANT_B``.

    This is recorded, not fixed, in this slice: the value reaches only
    ``python_runtime/telemetry.py:50`` (telemetry attribution) and no data
    access — the RLS context the middleware sets is still the header's
    tenant.  A mis-attributed telemetry row is a real but limited defect,
    and changing the API contract belongs in its own slice rather than in
    a test-only change.
    """

    def test_body_tenant_is_not_bound_to_the_actor_tenant(self) -> None:
        """Document the current behaviour: the body's tenant wins."""
        import asyncio

        from httpx import ASGITransport, AsyncClient

        from apps.api import middleware as middleware_module
        from apps.api.main import app

        class _NoopSession:
            """Session double: the compute path never issues tenant SQL."""

            def __enter__(self) -> _NoopSession:
                return self

            def __exit__(self, *exc_info: object) -> None:
                """Exit the context manager without suppressing exceptions."""

            def execute(self, *args: object, **kwargs: object) -> None:
                """Accept and ignore the RLS statement."""

        original = middleware_module._default_session_factory
        middleware_module._default_session_factory = lambda: _NoopSession()
        try:

            async def _submit() -> Any:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    return await client.post(
                        "/api/v1/jobs/submit",
                        headers={"X-Tenant-ID": "TENANT_A", "X-Role": "analyst"},
                        json={
                            "pipeline": "analytics",
                            "source_type": "csv",
                            "source_uri": "/tmp/does-not-matter.csv",
                            "params": {},
                            "tenant_id": "TENANT_B",
                        },
                    )

            response = asyncio.run(_submit())
        finally:
            middleware_module._default_session_factory = original

        # The request is accepted and the job is created — the body tenant
        # is not validated against the actor tenant.
        assert response.status_code == 202, response.text
        assert response.json()["job_id"]

    def test_compute_job_carries_the_body_tenant(self) -> None:
        """The job's tenant is the body's value, which is the defect."""
        from apps.api.schemas import JobSubmitRequest

        request = JobSubmitRequest(
            pipeline="analytics",
            source_type="csv",
            source_uri="/tmp/x.csv",
            params={},
            tenant_id="TENANT_B",
        )
        assert request.tenant_id == "TENANT_B"


def _read_source(relative_path: str) -> str | None:
    """Return a repository source file's text, or None when unreadable."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
