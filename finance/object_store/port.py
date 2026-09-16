"""Object-store port — tenant-scoped, hash-checked, transport-only.

S3 is transport and artifact store only. PostgreSQL remains the
financial/idempotency authority. The LLM never retrieves arbitrary
objects through this port.

Key convention: ``{tenant_id}/{case_or_batch_id}/{filename}``
Keys are validated as tenant-prefixed; cross-tenant access raises
``TenantIsolationError`` without touching the backing store.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ObjectMeta:
    """Metadata for a stored object — content-hash and length precomputed."""

    key: str
    content_hash: str  # sha256 hex of raw bytes
    content_length: int
    tenant_id: str


def _content_hash(data: bytes) -> str:
    """Return sha256 hex for raw bytes."""
    return hashlib.sha256(data).hexdigest()


class ObjectStorePort(Protocol):
    """Domain port for tenant-scoped object storage (S3 contract)."""

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectMeta:
        """Store bytes at tenant key; returns hash+length. Idempotent for same key+bytes."""
        ...

    def get_object(self, key: str) -> tuple[bytes, ObjectMeta]:
        """Retrieve bytes + meta; raises ObjectNotFoundError or TenantIsolationError."""
        ...

    def exists(self, key: str) -> bool:
        """Return True when key exists for the calling tenant."""
        ...

    def delete(self, key: str) -> None:
        """Delete key if present (cleanup only; idempotent)."""
        ...
