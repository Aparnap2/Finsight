"""Provenance envelope carried by every P6-03 canonical fact.

A fact without adapter identity, endpoint binding, correlation id, a
64-hex content hash, and a timezone-aware retrieval timestamp is
rejected at the boundary per contract section 1.7: anonymous facts
never reconcile. The company scope is frozen to meridian.
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
"""Content hashes are lowercase sha256 hex digests."""


class FactProvenance(BaseModel):
    """Ingest identity bound to one canonical fact.

    ``adapter`` names the deterministic reader version, ``endpoint``
    names the owning P6-01 contract (for example ``C-RAZORPAY``), and
    ``content_hash`` binds the exact source bytes so redelivery of the
    same hash absorbs idempotently while a changed hash conflicts.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    adapter: str
    """Deterministic reader name plus version, never empty."""

    endpoint: str
    """Owning source contract (for example ``C-RAZORPAY``)."""

    correlation_id: str
    """Ingest run correlation id, never empty."""

    content_hash: str
    """Lowercase sha256 hex digest of the source record."""

    retrieved_at: datetime
    """Timezone-aware retrieval timestamp (naive datetimes rejected)."""

    company_id: str = "meridian"
    """Single-company scope; anything else is refused."""

    @field_validator("adapter", "endpoint", "correlation_id")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Require non-empty identity strings."""
        if not value.strip():
            raise ValueError("Provenance identity fields must be non-empty.")
        return value.strip()

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        """Require a 64-character lowercase hex digest."""
        if _HASH_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "content_hash must be a 64-char lowercase hex digest, "
                f"got {value!r}."
            )
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _validate_retrieved_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware retrieval timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware.")
        return value

    @field_validator("company_id")
    @classmethod
    def _validate_company_id(cls, value: str) -> str:
        """Enforce the single-company boundary (meridian only)."""
        if value != "meridian":
            raise ValueError(
                "company_id must be 'meridian' (single-company boundary), "
                f"got {value!r}."
            )
        return value
