"""PENDING_EVIDENCE emitter for incomplete detection coverage.

Partial data never promotes into a DETECTED case with a guessed
variance (section 4.1): the missing legs are named in a
detection-attempt log and detection retries when coverage completes.
"""

import hashlib
import re
from collections.abc import Collection

from pydantic import BaseModel, ConfigDict, field_validator

_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
"""Attempt fingerprints are lowercase sha256 hex digests."""


class PendingAttempt(BaseModel):
    """One named detection-attempt log for missing coverage."""

    model_config = ConfigDict(frozen=True, strict=True)

    fact_id: str
    """The leg or window the attempt waited on, never empty."""

    missing_fields: frozenset[str]
    """Named missing legs or fields; never empty."""

    fingerprint: str
    """Stable digest binding the attempt identity."""

    @field_validator("fact_id")
    @classmethod
    def _validate_fact_id(cls, value: str) -> str:
        """Require a non-empty attempt identity."""
        if not value.strip():
            raise ValueError("fact_id must be non-empty.")
        return value.strip()

    @field_validator("missing_fields")
    @classmethod
    def _validate_missing(cls, value: frozenset[str]) -> frozenset[str]:
        """Require at least one named missing field."""
        if len(value) == 0:
            raise ValueError("missing_fields must name at least one field.")
        return value

    @field_validator("fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        """Require a 64-character lowercase hex digest."""
        if _FINGERPRINT_PATTERN.fullmatch(value) is None:
            raise ValueError("fingerprint must be a 64-char hex digest.")
        return value


def emit_pending(
    fact_id: str,
    missing_fields: Collection[str],
    fingerprint_source: str,
) -> PendingAttempt:
    """Emit a detection-attempt log naming the missing coverage.

    Args:
        fact_id: The leg or window the attempt waited on.
        missing_fields: Names of the absent legs or fields.
        fingerprint_source: Stable window key binding the digest.

    Returns:
        The immutable pending attempt with a stable fingerprint.

    Raises:
        ValueError: If no missing field is named.
    """
    cleaned = frozenset(
        field.strip() for field in missing_fields if field.strip()
    )
    if len(cleaned) == 0:
        raise ValueError("missing_fields must name at least one field.")
    canonical = "|".join([fact_id, ",".join(sorted(cleaned)), fingerprint_source])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return PendingAttempt(
        fact_id=fact_id, missing_fields=cleaned, fingerprint=digest
    )
