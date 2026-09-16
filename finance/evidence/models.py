"""Evidence models.

Every claim made by the LLM must reference supporting evidence.
P5-04 grounding ladder requires tenant ownership, content hash,
retrieval time (tz-aware), provenance, and immutability.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceProvenance(BaseModel):
    """Provenance for one retrieved artifact (adapter, endpoint, correlation)."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    adapter: str
    endpoint: str
    correlation_id: str

    @field_validator("adapter", "endpoint", "correlation_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provenance fields must be non-blank.")
        return value


class EvidenceItem(BaseModel):
    """A single piece of evidence supporting a claim."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    claim: str
    source_type: str
    source_id: str
    source_value: Decimal | None = None
    supporting_metrics: list[str] = []
    confidence: str = "medium"
    assumptions: list[str] = []
    limitations: list[str] = []
    # P5-04 grounding lineage (optional for legacy callers, required for VERIFIED)
    tenant_id: str | None = None
    content_hash: str | None = None
    retrieved_at: datetime | None = None
    provenance: EvidenceProvenance | None = None

    @field_validator("claim", "source_type", "source_id")
    @classmethod
    def _not_blank_core(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("core evidence fields must be non-blank.")
        return value

    @field_validator("tenant_id")
    @classmethod
    def _validate_tenant(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("tenant_id must be non-blank when provided.")
        return value

    @field_validator("content_hash")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SHA256_RE.match(value):
            raise ValueError("content_hash must be 64-char lowercase hex sha256.")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _validate_retrieved_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be tz-aware.")
        return value
