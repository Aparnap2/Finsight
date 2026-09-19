"""P6-07 T2 S3 transport — stage E4 (courier, never author).

Moves the exact E3 bytes to ``finsight-legacy-outbound`` with read-back
SHA-256 verification (X25), a bounded retry budget of 1 initial attempt +
3 retries (A4), and prefix isolation before any network call (X24/D10).

Recovery probe (A2): :func:`recover_receipt` reads the deterministic key
first. Hash match records the receipt with 0 PUTs; absence performs
exactly one PUT+verify cycle (``put_verified(..., max_attempts=1)`` — the
probe path never runs a retry loop, keeping the per-execution total
bounded; callers needing the full 1+3 budget call :func:`put_verified`
directly); differing bytes refuse with ``EXEC_HASH_MISMATCH`` and are
never reserialized.

Determinism notes: ``backoff``/``timeout_s`` are declared and validated
budgets carried for the production runtime — this module never sleeps and
never reads a clock (``now`` is caller-supplied and must be tz-aware).
Retries resend the identical ``artifact.file_bytes`` object; no stage
re-serializes between E3 and E4 (X23/X27). Mismatching objects are left
in place for operator triage. No LLM, no new dependencies.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finance.legacy.protocol import (
    CompanyIsolationError,
    validate_s3_key_tenant,
)
from finance.object_store.errors import (
    ObjectNotFoundError,
    TenantIsolationError,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTBOUND_BUCKET = "finsight-legacy-outbound"

PREFIX_ESCAPE_CODE = "EXEC_PREFIX_ESCAPE"
HASH_MISMATCH_CODE = "EXEC_HASH_MISMATCH"
TRANSPORT_REFUSED_CODE = "EXEC_TRANSPORT_REFUSED"

DEFAULT_MAX_ATTEMPTS = 4  # 1 initial + 3 retries per A4
DEFAULT_BACKOFF_S = (1.0, 2.0, 4.0)
DEFAULT_TIMEOUT_S = 10.0

_FILE_NAME_RE = "CORRECTION_"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PrefixEscapeError(Exception):
    """Cross-company key refused before any network call (D10)."""

    code = PREFIX_ESCAPE_CODE

    def __init__(self, detail: str) -> None:
        super().__init__(f"{PREFIX_ESCAPE_CODE}: {detail}")


class HashMismatchError(Exception):
    """Read-back bytes do not hash to the artifact digest (D4 / A2)."""

    code = HASH_MISMATCH_CODE

    def __init__(self, detail: str) -> None:
        super().__init__(f"{HASH_MISMATCH_CODE}: {detail}")


class TransportRefusedError(Exception):
    """Retry budget exhausted without a verified PUT."""

    code = TRANSPORT_REFUSED_CODE

    def __init__(self, detail: str) -> None:
        super().__init__(f"{TRANSPORT_REFUSED_CODE}: {detail}")


# ---------------------------------------------------------------------------
# Models (frozen, strict)
# ---------------------------------------------------------------------------


class TransportReceipt(BaseModel):
    """E4 permit output — the sole precondition for E5 observation (X28)."""

    model_config = ConfigDict(frozen=True, strict=True)

    execution_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., pattern=r"^LEGACY-\d{8}-\d{4}$")
    key: str = Field(..., min_length=1)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(..., ge=0)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _require_tz_aware(cls, value: datetime) -> datetime:
        """Receipt time is caller-supplied and must carry a timezone."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be tz-aware (caller-supplied)")
        return value


class _StorePort(Protocol):
    """Minimal structural seam of the object-store port (FakeS3 in tests)."""

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> Any:
        """Store bytes at key; may raise on S3 failure."""
        ...

    def get_object(self, key: str) -> tuple[bytes, Any]:
        """Read bytes back; raises ObjectNotFoundError when absent."""
        ...


# ---------------------------------------------------------------------------
# Key derivation + prefix gate (X24, before any network call)
# ---------------------------------------------------------------------------


def _require_clean_company(company_id: str) -> str:
    """Validate the tenant segment; escape attempts refuse pre-network."""
    company = company_id.strip()
    if not company or "/" in company or "\\" in company or ".." in company:
        raise PrefixEscapeError(f"bad company segment {company_id!r}")
    if any(ch.isspace() for ch in company):
        raise PrefixEscapeError(f"bad company segment {company_id!r}")
    return company


def derive_outbound_key(company_id: str, batch_id: str, file_name: str) -> str:
    """Derive ``{company_id}/{batch_id}/{file_name}`` with prefix checks.

    The key is composed from the A5 generic file name (the frozen
    ``build_outbound_key`` helper still encodes the old fixed-``231``
    filename, so composition keeps the same ``company/batch/file`` shape
    while honoring generic SEQ). Tenant semantics come from the frozen
    ``validate_s3_key_tenant`` check — never reimplemented.
    """
    company = _require_clean_company(company_id)
    if not file_name.startswith(_FILE_NAME_RE) or ".." in file_name:
        raise PrefixEscapeError(f"bad file name {file_name!r}")
    if ".." in batch_id or "/" in batch_id:
        raise PrefixEscapeError(f"bad batch segment {batch_id!r}")
    key = f"{company}/{batch_id}/{file_name}"
    if ".." in key:
        raise PrefixEscapeError(f"key escapes prefix: {key!r}")
    try:
        validate_s3_key_tenant(key, company)
    except CompanyIsolationError as exc:
        raise PrefixEscapeError(str(exc)) from exc
    return key


def _key_for(
    artifact: Any, company_id: str, bucket_outbound: str, now: datetime
) -> str:
    """Run every pre-network gate; return the deterministic OUTBOUND key."""
    if not isinstance(bucket_outbound, str) or not bucket_outbound.strip():
        raise ValueError("bucket_outbound must be a non-empty string")
    if not isinstance(now, datetime):
        raise ValueError("now must be a tz-aware datetime")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be tz-aware (caller-supplied)")
    company = _require_clean_company(company_id)
    artifact_company = getattr(artifact, "company_id", None)
    if artifact_company is not None and artifact_company != company:
        raise PrefixEscapeError(
            f"company {company!r} != artifact company {artifact_company!r}"
        )
    return derive_outbound_key(company, artifact.batch_id, artifact.file_name)


def _receipt_for(artifact: Any, key: str, now: datetime) -> TransportReceipt:
    """Build the transport receipt bound to execution + batch (X28)."""
    return TransportReceipt(
        execution_id=artifact.execution_id,
        batch_id=artifact.batch_id,
        key=key,
        sha256=artifact.outbound_sha256,
        byte_count=len(artifact.file_bytes),
        timestamp=now,
    )


# ---------------------------------------------------------------------------
# PUT + read-back verify (X25/X26, A4 budget)
# ---------------------------------------------------------------------------


def _probe_present(store: _StorePort, key: str) -> bytes | None:
    """Return the stored bytes at ``key``, or None when absent (A2 probe).

    A present object lets the caller recover a receipt with zero PUTs;
    absence authorizes exactly one PUT cycle. Tenant errors refuse;
    other S3 failures propagate to the retry loop.
    """
    try:
        present, _meta = store.get_object(key)
    except ObjectNotFoundError:
        return None
    except (TenantIsolationError, CompanyIsolationError) as exc:
        raise PrefixEscapeError(str(exc)) from exc
    return present


def put_verified(
    store: _StorePort,
    artifact: Any,
    *,
    company_id: str,
    bucket_outbound: str,
    now: datetime,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff: tuple[float, ...] = DEFAULT_BACKOFF_S,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> TransportReceipt:
    """PUT the exact E3 bytes and read-back-verify the SHA-256 (X25).

    Prefix gates run before any network call (D10). Each cycle sends the
    identical ``artifact.file_bytes``; read-back mismatch refuses at once
    with ``EXEC_HASH_MISMATCH`` (object left for triage, no fix-up, no
    retry on corrupted bytes). PUT/read failures retry up to
    ``max_attempts`` total cycles (default 4 = 1+3 per A4); exhaustion
    refuses with ``EXEC_TRANSPORT_REFUSED``. ``backoff``/``timeout_s``
    are validated budgets the production runtime applies — never slept
    or clocked here.
    """
    key = _key_for(artifact, company_id, bucket_outbound, now)
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 4:
        raise ValueError("max_attempts must be an int in 1..4 (A4 budget)")
    if any(b < 0 for b in backoff):
        raise ValueError("backoff entries must be non-negative")
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    payload: bytes = bytes(artifact.file_bytes)
    want = artifact.outbound_sha256
    probed = _probe_present(store, key)
    if probed is not None:
        if probed != payload or hashlib.sha256(probed).hexdigest() != want:
            raise HashMismatchError(
                f"probe collision for {key!r}: stored bytes differ from "
                f"{want_short(artifact)}"
            )
        return _receipt_for(artifact, key, now)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            store.put_object(key, payload, content_type="application/octet-stream")
            read_bytes, _meta = store.get_object(key)
        except (PrefixEscapeError, HashMismatchError):
            raise
        except (TenantIsolationError, CompanyIsolationError) as exc:
            raise PrefixEscapeError(str(exc)) from exc
        except Exception as exc:  # S3 failure: retry identical bytes only
            last_error = exc
            if attempt >= max_attempts:
                raise TransportRefusedError(
                    f"attempt {attempt}/{max_attempts} failed for {key!r}: {exc}"
                ) from exc
            continue
        if read_bytes != payload or hashlib.sha256(read_bytes).hexdigest() != want:
            raise HashMismatchError(
                f"read-back mismatch for {key!r}: want {want}, "
                f"got {hashlib.sha256(read_bytes).hexdigest()}"
            )
        return _receipt_for(artifact, key, now)
    assert last_error is not None  # narrow for type-checkers; loop always raises
    raise TransportRefusedError(f"no verified PUT for {key!r}: {last_error}")


# ---------------------------------------------------------------------------
# Recovery probe (A2)
# ---------------------------------------------------------------------------


def recover_receipt(
    store: _StorePort,
    artifact: Any,
    *,
    company_id: str,
    bucket_outbound: str,
    now: datetime,
) -> TransportReceipt:
    """A2 crash-recovery probe on the deterministic OUTBOUND key.

    Present + hash match → record the receipt with 0 PUTs. Absent →
    exactly one PUT+verify cycle (single attempt, no retry loop on the
    probe path). Present + differing bytes → refuse with
    ``EXEC_HASH_MISMATCH`` (integrity wins over retransmission; never
    reserialized, object left for escalation).
    """
    key = _key_for(artifact, company_id, bucket_outbound, now)
    try:
        read_bytes, _meta = store.get_object(key)
    except ObjectNotFoundError:
        return put_verified(
            store,
            artifact,
            company_id=company_id,
            bucket_outbound=bucket_outbound,
            now=now,
            max_attempts=1,
        )
    except (TenantIsolationError, CompanyIsolationError) as exc:
        raise PrefixEscapeError(str(exc)) from exc
    if read_bytes != bytes(artifact.file_bytes) or (
        hashlib.sha256(read_bytes).hexdigest() != artifact.outbound_sha256
    ):
        raise HashMismatchError(
            f"probe collision for {key!r}: stored bytes differ from {want_short(artifact)}"
        )
    return _receipt_for(artifact, key, now)


def want_short(artifact: Any) -> str:
    """Render the wanted digest for probe-collision messages."""
    return str(getattr(artifact, "outbound_sha256", "?"))
