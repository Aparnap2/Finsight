"""Centralised exception-to-response mapping for the API boundary.

Every error response is *derived* from :mod:`shared.errors.catalog`. This
module never invents a code, a status, or a retryability flag; it looks them
up. If a handler needs a new code, the registry gains it first.

Compatibility contract (Stage 1 of the error-envelope transition):

* The legacy top-level ``detail`` key is preserved **verbatim** for every
  response shape that already emitted it, so existing clients keep working.
* The structured ``error`` object, ``request_id``, and ``correlation_id`` are
  **additive**. A client that ignores them observes no change.
* No existing status code changes.

Unexpected exceptions map to a generic ``INTERNAL_ERROR`` body. The traceback
is recorded in protected logs only; it is never serialised to the client.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.observability import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    coerce_correlation_id,
    coerce_request_id,
)
from shared.errors import ErrorCode, code_for_status, spec_for

logger = logging.getLogger("finsight.error")

#: Message shown when a response carries no user-safe text of its own.
GENERIC_INTERNAL_MESSAGE = "Internal server error."


class ApiError(HTTPException):
    """An ``HTTPException`` that carries an explicit registry code.

    Subclasses FastAPI's ``HTTPException`` (not Starlette's directly) so the
    existing ``except HTTPException: raise`` pass-through blocks keep working
    unchanged. Routes raise this when the failure has a precise
    classification; a bare ``HTTPException`` still gets a status-derived code.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: ErrorCode,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.details = details or {}


def _request_ids(request: Request) -> tuple[str, str]:
    """Return the (request_id, correlation_id) for this request.

    The middleware sets both before calling the route, and ``request.state``
    survives even when the middleware has already unwound on an exception.
    """
    state = getattr(request, "state", None)
    request_id = str(getattr(state, "request_id", "") or "")
    correlation_id = str(getattr(state, "correlation_id", "") or "")
    headers = request.headers
    if not request_id:
        request_id = coerce_request_id(headers.get(REQUEST_ID_HEADER))
    if not correlation_id:
        correlation_id = coerce_correlation_id(headers.get(CORRELATION_ID_HEADER))
    return request_id, correlation_id


def build_error_body(
    *,
    code: ErrorCode,
    legacy_detail: Any,
    request: Request,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the response body for ``code``.

    ``legacy_detail`` is echoed unchanged under ``detail``; ``message`` is the
    user-safe text carried inside the ``error`` object. When no message is
    supplied, a string ``legacy_detail`` is reused so the two never disagree.
    """
    spec = spec_for(code)
    request_id, correlation_id = _request_ids(request)
    safe_message = message
    if safe_message is None:
        safe_message = legacy_detail if isinstance(legacy_detail, str) else spec.recovery
    return {
        "detail": legacy_detail,
        "error": {
            "code": code.value,
            "category": spec.category.value,
            "message": safe_message,
            "details": details or {},
            "retryable": spec.retryable,
        },
        "request_id": request_id,
        "correlation_id": correlation_id,
    }


def _response(
    body: dict[str, Any],
    *,
    status_code: int,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    merged: dict[str, str] = dict(headers or {})
    merged.setdefault(REQUEST_ID_HEADER, str(body["request_id"]))
    merged.setdefault(CORRELATION_ID_HEADER, str(body["correlation_id"]))
    return JSONResponse(status_code=status_code, content=body, headers=merged)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map a typed or bare ``HTTPException`` onto the error contract."""
    assert isinstance(exc, StarletteHTTPException)
    code = exc.code if isinstance(exc, ApiError) else code_for_status(exc.status_code)
    details = exc.details if isinstance(exc, ApiError) else None
    body = build_error_body(
        code=code,
        legacy_detail=exc.detail,
        request=request,
        details=details,
    )
    return _response(body, status_code=exc.status_code, headers=exc.headers)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map an unexpected exception to a generic body; keep the trace server-side."""
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    body = build_error_body(
        code=ErrorCode.INTERNAL_ERROR,
        legacy_detail=GENERIC_INTERNAL_MESSAGE,
        request=request,
        message=GENERIC_INTERNAL_MESSAGE,
    )
    return _response(body, status_code=500)


def register_error_handlers(app: FastAPI) -> None:
    """Install the error contract on ``app``.

    ``RequestValidationError`` is registered separately (with scrubbing) by the
    caller, because validation bodies need field-level redaction.
    """
    app.add_exception_handler(StarletteHTTPException, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)


__all__ = [
    "ApiError",
    "GENERIC_INTERNAL_MESSAGE",
    "api_error_handler",
    "build_error_body",
    "register_error_handlers",
    "unhandled_error_handler",
]
