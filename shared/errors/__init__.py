"""Error classification shared across FinSight layers.

``shared.errors.catalog`` is the single source of truth for stable error
codes, their category, default HTTP status, severity, retryability, and
recovery guidance. Nothing above this layer may redefine those facts.

The web layer (``apps.api.errors``) derives response bodies from the registry;
it does not own them.
"""

from __future__ import annotations

from shared.errors.catalog import (
    REGISTRY,
    ErrorCategory,
    ErrorCode,
    ErrorSpec,
    Severity,
    code_for_status,
    is_retryable,
    spec_for,
)

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
