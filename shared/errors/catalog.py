"""Canonical error registry for the FinSight API boundary.

This module is the **single source of truth** for API error classification.
The error envelope, the HTTP handlers, and the specification in
``docs/specs/ERROR_CATALOG.md`` all read from here; none of them restates it.

Ownership rules:

* :class:`ErrorCode` owns the stable code string.
* :class:`ErrorSpec` owns category, default HTTP status, severity,
  retryability, recovery guidance, and the responsible owner.
* Response bodies are *derived* from this registry. A response is never the
  place where a code is invented.

Framework-free by design: this module must not import FastAPI, Starlette, or
any layer above ``shared``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class ErrorCategory(StrEnum):
    """Coarse classification that fixes the default handling policy."""

    VALIDATION = "validation"
    BUSINESS_RULE = "business_rule"
    AUTHORIZATION = "authorization"
    SECURITY = "security"
    CONCURRENCY = "concurrency"
    RESOURCE = "resource"
    PROCESSING = "processing"
    INFRASTRUCTURE = "infrastructure"
    PROVIDER = "provider"


class Severity(StrEnum):
    """Operator-facing severity. Drives alerting thresholds in Stage 2."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorCode(StrEnum):
    """Stable error codes. Never rename one; add a new one instead."""

    # Validation
    BAD_REQUEST = "BAD_REQUEST"
    INVALID_FILE = "INVALID_FILE"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DUPLICATE_IMPORT = "DUPLICATE_IMPORT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"

    # Business rule
    CONFLICT = "CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    AMBIGUOUS_ALLOCATION = "AMBIGUOUS_ALLOCATION"

    # Authorization
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    TENANT_ACCESS_DENIED = "TENANT_ACCESS_DENIED"

    # Security
    TENANT_CONTEXT_MISSING = "TENANT_CONTEXT_MISSING"

    # Concurrency
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STATE_VERSION_CONFLICT = "STATE_VERSION_CONFLICT"
    DUPLICATE_DECISION = "DUPLICATE_DECISION"

    # Resource
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

    # Processing
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"

    # Infrastructure
    PERSISTENCE_UNAVAILABLE = "PERSISTENCE_UNAVAILABLE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

    # AI provider
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_AUTH = "PROVIDER_AUTH"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"


#: Who acts on a failure of this category.
_OWNER_BY_CATEGORY: Mapping[ErrorCategory, str] = MappingProxyType(
    {
        ErrorCategory.VALIDATION: "caller",
        ErrorCategory.BUSINESS_RULE: "operator",
        ErrorCategory.AUTHORIZATION: "caller",
        ErrorCategory.SECURITY: "security-owner",
        ErrorCategory.CONCURRENCY: "caller",
        ErrorCategory.RESOURCE: "caller",
        ErrorCategory.PROCESSING: "finsight-engineering",
        ErrorCategory.INFRASTRUCTURE: "platform",
        ErrorCategory.PROVIDER: "ai-platform",
    }
)


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """Everything the boundary needs to know about one error code."""

    category: ErrorCategory
    http_status: int
    severity: Severity
    retryable: bool
    recovery: str

    @property
    def owner(self) -> str:
        """Return the team or actor responsible for resolving this error."""
        return _OWNER_BY_CATEGORY[self.category]


def _spec(
    category: ErrorCategory,
    http_status: int,
    severity: Severity,
    retryable: bool,
    recovery: str,
) -> ErrorSpec:
    return ErrorSpec(
        category=category,
        http_status=http_status,
        severity=severity,
        retryable=retryable,
        recovery=recovery,
    )


_V = ErrorCategory.VALIDATION
_B = ErrorCategory.BUSINESS_RULE
_A = ErrorCategory.AUTHORIZATION
_S = ErrorCategory.SECURITY
_C = ErrorCategory.CONCURRENCY
_R = ErrorCategory.RESOURCE
_P = ErrorCategory.PROCESSING
_I = ErrorCategory.INFRASTRUCTURE
_PR = ErrorCategory.PROVIDER
_INFO = Severity.INFO
_WARN = Severity.WARNING
_ERR = Severity.ERROR

#: The registry. Keyed by :class:`ErrorCode`; insertion order is meaningful
#: only for readability, never for behaviour.
_REGISTRY: dict[ErrorCode, ErrorSpec] = {
    # -- Validation -------------------------------------------------------
    ErrorCode.BAD_REQUEST: _spec(_V, 400, _WARN, False, "Correct the request and resubmit."),
    ErrorCode.INVALID_FILE: _spec(
        _V, 400, _WARN, False, "Re-export the file with a supported encoding and format."
    ),
    ErrorCode.INVALID_SCHEMA: _spec(
        _V, 400, _WARN, False, "Align the column headers with the documented schema."
    ),
    ErrorCode.VALIDATION_FAILED: _spec(
        _V, 422, _WARN, False, "Fix the reported fields and resubmit."
    ),
    ErrorCode.DUPLICATE_IMPORT: _spec(
        _V, 409, _WARN, False, "Use the existing import or submit different content."
    ),
    ErrorCode.PAYLOAD_TOO_LARGE: _spec(
        _V, 413, _WARN, False, "Split the payload and resubmit within the limit."
    ),
    ErrorCode.METHOD_NOT_ALLOWED: _spec(
        _V, 405, _WARN, False, "Use a supported HTTP method for this resource."
    ),
    # -- Business rule ----------------------------------------------------
    ErrorCode.CONFLICT: _spec(
        _B, 409, _WARN, False, "Reload the resource and reconcile the conflict."
    ),
    ErrorCode.INVALID_STATE_TRANSITION: _spec(
        _B, 409, _WARN, False, "Check the current state and choose a permitted transition."
    ),
    ErrorCode.ILLEGAL_TRANSITION: _spec(
        _B, 409, _WARN, False, "Check the current state and choose a permitted transition."
    ),
    ErrorCode.AMBIGUOUS_ALLOCATION: _spec(
        _B, 422, _WARN, False, "Resolve the ambiguity through human review."
    ),
    # -- Authorization ----------------------------------------------------
    ErrorCode.UNAUTHORIZED: _spec(_A, 401, _WARN, False, "Authenticate and resubmit."),
    ErrorCode.FORBIDDEN: _spec(_A, 403, _WARN, False, "Request the role required for this action."),
    ErrorCode.TENANT_ACCESS_DENIED: _spec(
        _A, 403, _WARN, False, "Access only resources owned by your tenant."
    ),
    # -- Security ---------------------------------------------------------
    ErrorCode.TENANT_CONTEXT_MISSING: _spec(
        _S, 401, _ERR, False, "Send authenticated tenant context with the request."
    ),
    # -- Concurrency ------------------------------------------------------
    ErrorCode.IDEMPOTENCY_CONFLICT: _spec(
        _C, 409, _WARN, False, "Reuse the original request body or issue a new idempotency key."
    ),
    ErrorCode.STATE_VERSION_CONFLICT: _spec(
        _C, 409, _WARN, True, "Reload the resource and retry with the current version."
    ),
    ErrorCode.DUPLICATE_DECISION: _spec(
        _C, 409, _WARN, False, "Treat the existing decision as the outcome; no retry needed."
    ),
    # -- Resource ---------------------------------------------------------
    ErrorCode.RESOURCE_NOT_FOUND: _spec(
        _R, 404, _INFO, False, "Verify the identifier exists within your tenant scope."
    ),
    # -- Processing -------------------------------------------------------
    ErrorCode.INTERNAL_ERROR: _spec(
        _P, 500, _ERR, False, "Report the correlation ID; do not retry blindly."
    ),
    ErrorCode.RECONCILIATION_FAILED: _spec(
        _P, 500, _ERR, False, "Report the correlation ID with the run ID; do not retry blindly."
    ),
    ErrorCode.EXPORT_FAILED: _spec(
        _P, 500, _ERR, True, "Retry once; if it persists, report the correlation ID."
    ),
    # -- Infrastructure ---------------------------------------------------
    ErrorCode.PERSISTENCE_UNAVAILABLE: _spec(
        _I, 503, _ERR, True, "Back off and retry; the write is rolled back, not partial."
    ),
    ErrorCode.SERVICE_UNAVAILABLE: _spec(
        _I, 503, _ERR, True, "Back off and retry after the indicated interval."
    ),
    ErrorCode.GATEWAY_TIMEOUT: _spec(_I, 504, _ERR, True, "Retry after the indicated interval."),
    ErrorCode.RATE_LIMITED: _spec(
        _I, 429, _WARN, True, "Back off for the retry interval and resubmit."
    ),
    ErrorCode.BUDGET_EXHAUSTED: _spec(
        _I, 429, _WARN, True, "Reduce the request scope or wait for the budget window to reset."
    ),
    # -- AI provider ------------------------------------------------------
    ErrorCode.PROVIDER_TIMEOUT: _spec(
        _PR, 504, _WARN, True, "Retry the investigation; deterministic results remain available."
    ),
    ErrorCode.PROVIDER_UNAVAILABLE: _spec(
        _PR, 503, _WARN, True, "Retry later; deterministic results remain available."
    ),
    ErrorCode.PROVIDER_AUTH: _spec(
        _PR, 503, _WARN, False, "Fix the provider credentials; retrying will not help."
    ),
    ErrorCode.SCHEMA_VIOLATION: _spec(
        _PR, 422, _WARN, False, "Treat the investigation as failed and continue without it."
    ),
}

REGISTRY: Mapping[ErrorCode, ErrorSpec] = MappingProxyType(_REGISTRY)

#: Status-derived fallback for handlers that raise a bare ``HTTPException``.
#: An explicitly tagged code always wins over this map.
_STATUS_TO_CODE: Mapping[int, ErrorCode] = MappingProxyType(
    {
        400: ErrorCode.BAD_REQUEST,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.RESOURCE_NOT_FOUND,
        405: ErrorCode.METHOD_NOT_ALLOWED,
        409: ErrorCode.CONFLICT,
        413: ErrorCode.PAYLOAD_TOO_LARGE,
        422: ErrorCode.VALIDATION_FAILED,
        429: ErrorCode.RATE_LIMITED,
        500: ErrorCode.INTERNAL_ERROR,
        503: ErrorCode.SERVICE_UNAVAILABLE,
        504: ErrorCode.GATEWAY_TIMEOUT,
    }
)


def spec_for(code: ErrorCode) -> ErrorSpec:
    """Return the specification for ``code`` (KeyError if unregistered)."""
    return REGISTRY[code]


def code_for_status(status_code: int) -> ErrorCode:
    """Return a code for a status that arrived without an explicit tag.

    Unknown 4xx map to ``BAD_REQUEST`` and unknown 5xx to ``INTERNAL_ERROR`` so
    that no response is ever emitted without a classified code.
    """
    known = _STATUS_TO_CODE.get(status_code)
    if known is not None:
        return known
    if status_code >= 500:
        return ErrorCode.INTERNAL_ERROR
    return ErrorCode.BAD_REQUEST


def is_retryable(code: ErrorCode) -> bool:
    """Return whether the caller may retry the identical request."""
    return spec_for(code).retryable


__all__ = [
    "REGISTRY",
    "ErrorCategory",
    "ErrorCode",
    "ErrorSpec",
    "Severity",
    "code_for_status",
    "is_retryable",
    "spec_for",
]
