"""Tenant authentication/authorization boundary for the FinSight API.

Production note: authentication (who you are) is delegated to Better Auth
(frontend) + the FastAPI integration. This middleware is the *authorization
and tenant-context boundary* (what you may do, and which tenant's data you
see). It resolves the actor from demo headers (``X-Tenant-ID``, ``X-User-ID``,
``X-Role``), validates the role against the ``finplatform.rbac`` matrix, and
wires the tenant into PostgreSQL Row-Level Security via
``SELECT set_config('app.tenant_id', :tenant_id, true)`` on the request's DB
session so every downstream query is filtered by tenant.

The DB session is obtained through an injectable ``session_factory`` (a
callable returning a SQLAlchemy ``Session`` usable as a context manager), so
the middleware is testable without a real database and the factory can later be
swapped for async/engine-pooled sessions without touching request handling.
"""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from finplatform.rbac.matrix import ROLE_PERMISSIONS

logger = logging.getLogger(__name__)

#: Session factory type: a zero-arg callable returning a context-manager
#: session/connection with an ``execute`` method (e.g. a SQLAlchemy Session).
SessionFactory = Callable[[], Any]

_default_engine: Any = None


def _default_session_factory() -> Any:
    """Create a SQLAlchemy Session bound to the app's configured Postgres engine.

    The engine is created lazily on first use and cached module-wide. Imported
    lazily so importing the middleware never requires DB configuration.
    """
    global _default_engine
    if _default_engine is None:
        from sqlalchemy import create_engine

        from shared.config import get_settings

        _default_engine = create_engine(get_settings().postgres_uri)
    from sqlalchemy.orm import Session

    return Session(_default_engine)


class TenantAuthMiddleware(BaseHTTPMiddleware):
    """Enforce tenant + role on every request and set the RLS tenant context.

    Health endpoints (paths ending in ``/health``) are excluded from
    enforcement. Requests missing ``X-Tenant-ID``/``X-Role`` get 401; requests
    carrying an unknown role get 403. The resolved actor is attached to
    ``request.state.actor`` as ``{"tenant_id", "user_id", "role"}``.
    """

    def __init__(
        self,
        app: Any,
        session_factory: SessionFactory | None = None,
    ) -> None:
        """Store the app and the (DI-friendly) session factory."""
        super().__init__(app)
        self._session_factory: SessionFactory = session_factory or _default_session_factory

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Validate headers, set actor state and the RLS tenant variable."""
        path = request.url.path
        if path == "/health" or path.endswith("/health"):
            return await call_next(request)

        tenant_id = request.headers.get("X-Tenant-ID")
        role = request.headers.get("X-Role")
        if not tenant_id or not role:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing X-Tenant-ID or X-Role header"},
            )

        if role not in ROLE_PERMISSIONS:
            return JSONResponse(status_code=403, content={"detail": f"Unknown role: {role}"})

        user_id = request.headers.get("X-User-ID", "")
        request.state.actor = {"tenant_id": tenant_id, "user_id": user_id, "role": role}

        try:
            self._set_tenant_context(tenant_id)
        except Exception:
            logger.exception("RLS tenant context setup failed for tenant %s", tenant_id)
            raise

        return await call_next(request)

    def _set_tenant_context(self, tenant_id: str) -> None:
        """Set ``app.tenant_id`` for RLS on the request's DB session.

        Uses ``set_config(..., is_local=true)`` so the value applies to the
        session's transaction only — every request re-establishes its tenant
        context. Fail-closed: a failure here propagates (500) rather than
        letting an unfiltered (cross-tenant) query run.
        """
        from sqlalchemy import text

        with self._session_factory() as session:
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
