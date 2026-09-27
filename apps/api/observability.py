"""API observability helpers: request IDs, structured access logs, readiness.

Additive-only seam (Phase 8): no changes to existing routes, contracts, or
frozen P6/P7/P8 behavior. Stdlib ``logging`` only — no metrics backends,
tracers, or vendors.

What lives here:
- :class:`RequestIDMiddleware`: propagate/echo ``X-Request-ID``.
- :func:`format_request_log`: structured per-request record.
- :func:`create_readiness_router`: ``/ready`` (DB probe) vs ``/live``.
- :func:`budget_check_response`: surface existing P8 ``Budget`` refusals.

Redaction: records carry IDs/route/disposition/latency only — never
headers, bodies, credentials, HMAC material, or prompt text. Every value
passes through :mod:`shared.safety.secrets` scrubbing.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from shared.safety.secrets import contains_secret_literal, scrub_text

logger = logging.getLogger("finsight.request")

#: Header carrying the request ID in and echoing it back out.
REQUEST_ID_HEADER = "X-Request-ID"

#: Incoming IDs outside this pattern are replaced (log-forgery safety).
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


def generate_request_id() -> str:
    """Mint a tenant-safe request ID (16 hex chars)."""
    return uuid.uuid4().hex[:16]


def coerce_request_id(raw: str | None) -> str:
    """Return a safe request ID: the incoming value or a fresh one."""
    if raw and _SAFE_ID_RE.fullmatch(raw):
        return raw
    return generate_request_id()


def disposition_for(status_code: int) -> str:
    """Classify a status code for the per-request record."""
    if status_code < 400:
        return "success"
    if status_code < 500:
        return "client_error"
    return "server_error"


def format_request_log(
    *,
    request_id: str,
    tenant_id: str,
    situation_id: str,
    method: str,
    route: str,
    status_code: int,
    latency_ms: float,
) -> dict[str, Any]:
    """Build a scrubbed structured per-request record (pure, no I/O)."""
    record: dict[str, Any] = {
        "request_id": scrub_text(request_id),
        "tenant_id": scrub_text(tenant_id or "unknown"),
        "situation_id": scrub_text(situation_id or "none"),
        "method": scrub_text(method),
        "route": scrub_text(route),
        "status_code": status_code,
        "disposition": disposition_for(status_code),
        "latency_ms": round(latency_ms, 3),
    }
    text = " ".join(str(v) for v in record.values())
    if contains_secret_literal(text):  # fail-closed: never emit a leaking record
        return {
            "request_id": record["request_id"],
            "tenant_id": "[REDACTED]",
            "situation_id": "[REDACTED]",
            "method": record["method"],
            "route": record["route"],
            "status_code": status_code,
            "disposition": record["disposition"],
            "latency_ms": record["latency_ms"],
        }
    return record


def _emit(record: dict[str, Any]) -> None:
    """Emit one structured access line (IDs/route/disposition/latency only)."""
    logger.info(
        "request request_id=%s tenant_id=%s situation_id=%s method=%s route=%s "
        "status=%s disposition=%s latency_ms=%s",
        record["request_id"],
        record["tenant_id"],
        record["situation_id"],
        record["method"],
        record["route"],
        record["status_code"],
        record["disposition"],
        record["latency_ms"],
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate/propagate ``X-Request-ID`` and emit one scrubbed log line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach the request ID, echo it, and log the scrubbed record."""
        request_id = coerce_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000.0
        actor: Any = getattr(request.state, "actor", None)
        tenant_id = ""
        if isinstance(actor, dict):
            tenant_id = str(actor.get("tenant_id", ""))
        tenant_id = tenant_id or request.headers.get("X-Tenant-ID", "")
        situation_id = str(request.query_params.get("situation_id", ""))
        response.headers[REQUEST_ID_HEADER] = request_id
        _emit(
            format_request_log(
                request_id=request_id,
                tenant_id=tenant_id,
                situation_id=situation_id,
                method=request.method,
                route=request.url.path,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )
        )
        return response


def default_db_probe() -> bool:
    """Return True when Postgres answers ``SELECT 1`` (fail-closed False)."""
    try:
        from sqlalchemy import create_engine, text

        from shared.config import get_settings

        engine = create_engine(get_settings().postgres_uri)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logging.getLogger(__name__).exception("readiness DB probe failed")
        return False


def create_readiness_router(probe: Callable[[], bool] | None = None) -> APIRouter:
    """Build a readiness/liveness router with an injectable DB probe."""
    check: Callable[[], bool] = probe or default_db_probe
    router = APIRouter()

    @router.get("/live")
    async def live() -> dict[str, str]:
        """Liveness: the process is alive (no dependency checks)."""
        return {"status": "alive"}

    @router.get("/ready")
    async def ready() -> JSONResponse:
        """Readiness: 200 only when the DB probe succeeds, else 503."""
        try:
            ok = check()
        except Exception:
            ok = False
        if ok:
            return JSONResponse(status_code=200, content={"status": "ready"})
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    return router


def budget_check_response(budget: Any, usage: Any) -> JSONResponse | None:
    """Surface an existing P8 ``Budget`` refusal as a 429, or None in-budget.

    Uses the frozen ``check_budget`` — invents no new bounds. Pure except
    for one scrubbed warning line on refusal.
    """
    from agents.p8_runtime.contract import BudgetExhaustedError, check_budget

    try:
        check_budget(budget, usage)
    except BudgetExhaustedError as exc:
        logger.warning("budget exhausted: %s", scrub_text(str(exc)))
        return JSONResponse(
            status_code=429, content={"detail": "Budget exhausted", "code": "BUDGET_EXHAUSTED"}
        )
    return None


__all__ = [
    "REQUEST_ID_HEADER",
    "RequestIDMiddleware",
    "budget_check_response",
    "coerce_request_id",
    "create_readiness_router",
    "default_db_probe",
    "disposition_for",
    "format_request_log",
    "generate_request_id",
]
