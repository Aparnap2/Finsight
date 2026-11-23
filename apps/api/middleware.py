"""Tenant authentication/authorization boundary for the FinSight API.

Production note: authentication (who you are) is delegated to Better Auth
(frontend) + the FastAPI integration. This middleware is the *authorization
and tenant-context boundary* (what you may do, and which tenant's data you
see). It resolves the actor from demo headers (``X-Tenant-ID``, ``X-User-ID``,
``X-Role``), validates the role against the ``finplatform.rbac`` matrix, and
wires the tenant into PostgreSQL Row-Level Security via
``SELECT set_config('app.tenant_id', :tenant_id, true)`` on the *same* session
the route uses, so every downstream query is filtered by tenant. That wiring
lives in each router (``_db_session``), because a GUC set on a separate,
short-lived session is transaction-scoped and discarded before the route runs.

The middleware itself never opens a database session. RLS wiring needs the
``app.tenant_id`` GUC on the *same* connection that runs the query, and a GUC
set in middleware on a separate, short-lived session is transaction-scoped and
rolled back before the route's session ever sees it. Each router therefore sets
it on its own session (``apps/api/reconciliation_routes._db_session`` and the
equivalents in observations/approvals/webhooks).
"""

from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from finplatform.rbac.matrix import ROLE_PERMISSIONS

_default_engine: Any = None


def _default_session_factory() -> Any:
    """Create a SQLAlchemy Session bound to the app's configured Postgres engine.

    The engine is created lazily on first use and cached module-wide. Imported
    lazily so importing the middleware never requires DB configuration.

    Slice 3: bounded pool (pool_size + max_overflow + checkout timeout) and a
    per-connection statement timeout, so a hung database fails requests
    instead of exhausting the service.
    """
    global _default_engine
    if _default_engine is None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import QueuePool

        from shared.config import get_settings

        settings = get_settings()
        options = f"-c statement_timeout={settings.db_statement_timeout_ms}"
        _default_engine = create_engine(
            settings.postgres_uri,
            poolclass=QueuePool,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            pool_timeout=settings.db_pool_timeout_s,
            pool_pre_ping=True,
            connect_args={"options": options} if settings.db_statement_timeout_ms else {},
        )
    from sqlalchemy.orm import Session

    return Session(_default_engine)


class TenantAuthMiddleware(BaseHTTPMiddleware):
    """Enforce tenant + role on every request and attach the actor.

    Health endpoints are excluded from enforcement. Requests missing
    ``X-Tenant-ID``/``X-Role`` get 401; requests carrying an unknown role get
    403. The resolved actor is attached to ``request.state.actor`` as
    ``{"tenant_id", "user_id", "role"}``. The RLS tenant GUC is set by each
    route on its own DB session, not here (see the class body comment).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Validate headers and attach the resolved actor to request state."""
        path = request.url.path
        if path == "/health" or path.endswith("/health"):
            return await call_next(request)
        if path in ("/live", "/ready", "/health/live", "/health/ready"):
            # Liveness/readiness must answer even when Postgres is down. Health
            # endpoints are unauthenticated by API_CONTRACT.md §1, so they carry
            # no tenant and must not be gated on tenant headers.
            return await call_next(request)
        if path == "/gui" or path.startswith("/gui/"):
            # UI-1: operator console page chrome is a page-loading
            # concern only. Browser navigations cannot carry tenant
            # headers, so the mount prefix (pages, websocket, static)
            # bypasses the header gate. Data authorization is unchanged:
            # every observation handler still denies anonymous callers,
            # and console data calls carry explicit server-side headers.
            return await call_next(request)
        if path == "/webhooks/stripe" or path.startswith("/webhooks/"):
            # Commit 2: Stripe webhook ingest authenticates via HMAC-SHA256
            # over the raw body in apps/api/webhooks.py, not via user
            # TenantAuth headers. Bypass the header gate here; tenant
            # isolation is enforced per-delivery through the trusted
            # stripe_account map plus the Postgres RLS tenant context.
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

        # RLS tenant context is wired by each route on its own DB session (see
        # apps/api/reconciliation_routes._db_session and the equivalents in
        # observations/approvals/webhooks). Setting it here on a separate,
        # short-lived session would be transaction-scoped and rolled back before
        # the route's session sees it, so it never protected production data.
        return await call_next(request)
