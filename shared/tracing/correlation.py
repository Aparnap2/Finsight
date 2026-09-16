"""Correlation ID propagation: webhook → S3 → LLM → execution.

Derives a single tenant-safe ``correlation_id`` that links webhook
``fingerprint``/``idempotency_key`` → S3 ``ObjectMeta.key``
→ ``InvestigationRequest``/``InvestigationContext`` → execution
``idempotency_key``. Tenant-safe means no PII beyond tenant/case
identifiers: only ``[A-Za-z0-9._-]{1,128}`` with a leading alphanumeric.

Usage::

    from shared.tracing.correlation import (
        derive_correlation_id,
        from_fingerprint,
        from_s3_key,
        validate_correlation_id,
    )
"""

from __future__ import annotations

import hashlib
import re

_CORRELATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_S3_TENANT_PREFIX_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_\-]{0,127})/(.+)$")


def validate_correlation_id(value: str) -> str:
    """Validate that ``value`` is tenant-safe (no PII).

    Args:
        value: Candidate correlation identifier.

    Returns:
        The validated identifier.

    Raises:
        ValueError: If blank or violates the tenant-safe pattern.
        TypeError: If not a string.
    """
    if not isinstance(value, str):
        raise TypeError(f"correlation_id must be a string, got {type(value).__name__}.")
    if not value.strip():
        raise ValueError("correlation_id must be a non-blank string.")
    if not _CORRELATION_RE.match(value):
        raise ValueError(f"correlation_id {value!r} violates tenant-safe pattern.")
    if "@" in value or " " in value:
        raise ValueError(f"correlation_id {value!r} must not contain PII (email/space).")
    return value


def from_fingerprint(fingerprint: str) -> str:
    """Derive a tenant-safe correlation_id from a webhook fingerprint.

    Fingerprints are sha256 hex (64 lower-hex chars). Use the full hex
    as tenant-safe correlation_id (already matches the pattern, prefixed
    with a safe char to guarantee leading alphanumeric is hex).

    Args:
        fingerprint: ``hashlib.sha256(raw).hexdigest()`` from webhook ingestion.

    Returns:
        Tenant-safe correlation_id.

    Raises:
        ValueError: If fingerprint is malformed.
    """
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ValueError("fingerprint must be a non-blank string.")
    fp = fingerprint.strip().lower()
    if not _FINGERPRINT_RE.match(fp):
        raise ValueError(f"fingerprint {fingerprint!r} must be 64-char hex sha256.")
    return fp


def from_idempotency_key(key: str) -> str:
    """Derive a tenant-safe correlation_id from an idempotency key.

    Idempotency keys are caller-supplied but tenant-safe per spec
    (no PII). Validate the pattern and return verbatim.

    Args:
        key: Idempotency key (e.g. approval ``appr_<hex>`` or webhook).

    Returns:
        Tenant-safe correlation_id (the key itself).

    Raises:
        ValueError: If blank or violates tenant-safe pattern.
    """
    return validate_correlation_id(key.strip())


def from_s3_key(key: str) -> str:
    """Extract the tenant-safe correlation/case id from an S3 key.

    Keys follow ``{tenant_id}/{case_id}/{filename}`` (port.py). The
    ``case_id`` segment is the correlation_id (e.g. ``CASE-1027``).

    Args:
        key: S3 object key.

    Returns:
        The ``case_id`` segment as correlation_id.

    Raises:
        ValueError: If key does not match tenant-prefixed shape.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("S3 key must be a non-blank string.")
    m = _S3_TENANT_PREFIX_RE.match(key.strip())
    if not m:
        raise ValueError(f"S3 key {key!r} must be tenant-prefixed.")
    remainder = m.group(2)
    # remainder is case_id/... or case_id
    case_id = remainder.split("/", 1)[0].strip()
    if not case_id:
        raise ValueError(f"S3 key {key!r} missing case segment.")
    return validate_correlation_id(case_id)


def derive_correlation_id(
    *,
    fingerprint: str | None = None,
    idempotency_key: str | None = None,
    s3_key: str | None = None,
    exception_id: str | None = None,
) -> str:
    """Unify the correlation_id across webhook → S3 → LLM → execution.

    Precedence: ``exception_id`` (case) > ``s3_key`` case segment >
    ``fingerprint`` > ``idempotency_key``. At least one source must be
    provided. All candidates must be tenant-safe; PII (emails, spaces)
    is rejected. When multiple sources are supplied they must agree when
    they refer to the same case (s3 case vs exception_id); fingerprint
    and idempotency_key are treated as independent lineage anchors and
    are not compared for equality.

    Args:
        fingerprint: Webhook sha256 hex.
        idempotency_key: Execution/approval idempotency key.
        s3_key: Tenant-prefixed S3 key.
        exception_id: Case/exception identifier (tenant-safe).

    Returns:
        Single tenant-safe correlation_id for the trace.

    Raises:
        ValueError: If no source provided, any source violates tenant-safe,
            or s3 case mismatches exception_id.
    """
    candidates: list[str] = []

    if exception_id is not None:
        eid = validate_correlation_id(exception_id.strip())
        candidates.append(("exception_id", eid))

    s3_case: str | None = None
    if s3_key is not None:
        s3_case = from_s3_key(s3_key)
        candidates.append(("s3_key", s3_case))

    fp_val: str | None = None
    if fingerprint is not None:
        fp_val = from_fingerprint(fingerprint)
        candidates.append(("fingerprint", fp_val))

    ik_val: str | None = None
    if idempotency_key is not None:
        ik_val = from_idempotency_key(idempotency_key)
        candidates.append(("idempotency_key", ik_val))

    if not candidates:
        raise ValueError("At least one correlation source must be provided.")

    # Consistency gate: s3 case must match exception_id when both present
    if (
        exception_id is not None
        and s3_case is not None
        and exception_id.strip() != s3_case
    ):
        raise ValueError(
            f"Correlation mismatch: exception_id {exception_id!r} != S3 case {s3_case!r}."
        )

    # Return the highest-precedence candidate
    if exception_id is not None:
        return validate_correlation_id(exception_id.strip())
    if s3_case is not None:
        return s3_case
    if fp_val is not None:
        return fp_val
    return ik_val  # type: ignore[return-value]


def is_tenant_safe_id(value: str) -> bool:
    """Return True when ``value`` is tenant-safe (no PII, pattern OK)."""
    try:
        validate_correlation_id(value)
        return True
    except (ValueError, TypeError):
        return False


def correlation_for_trace(
    correlation_id: str,
    tenant_id: str,
    case_id: str,
) -> dict[str, str]:
    """Build a tenant-safe identity map for trace metadata.

    Only tenant_id, correlation_id, and case_id are retained; no PII
    or free-text beyond these three invariants.

    Args:
        correlation_id: Unified correlation identifier.
        tenant_id: Tenant scope.
        case_id: Case/exception identifier.

    Returns:
        Tenant-safe metadata dict for trace spans.
    """
    return {
        "correlation_id": validate_correlation_id(correlation_id),
        "tenant_id": validate_correlation_id(tenant_id),
        "case_id": validate_correlation_id(case_id),
    }


def hash_for_audit(value: str) -> str:
    """Return sha256 hex for an audit value (PII hashing, not correlation)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
