"""Fake in-memory S3 for unit and contract testing — hash-checked, tenant-isolated."""

from __future__ import annotations

import hashlib
import logging

from finance.object_store.errors import ObjectNotFoundError, TenantIsolationError
from finance.object_store.port import ObjectMeta

logger = logging.getLogger(__name__)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tenant_from_key(key: str) -> str:
    """Extract tenant prefix before first ``/``; empty key raises."""
    if not key or "/" not in key:
        return ""
    return key.split("/", 1)[0].strip()


class FakeS3:
    """In-memory S3 fake — validates tenant prefix, preserves hash/length, no network."""

    def __init__(self, tenant_id: str) -> None:
        tenant = tenant_id.strip()
        if not tenant:
            raise ValueError("FakeS3 tenant_id must be non-empty.")
        self._tenant_id = tenant
        self._store: dict[str, tuple[bytes, str]] = {}  # key -> (bytes, content_type)

    def _require_tenant_key(self, key: str) -> None:
        if not key or not key.strip():
            raise ValueError("Key must be non-empty.")
        if "/" not in key:
            raise ValueError("Key must be tenant-prefixed as {tenant_id}/...")
        tenant = _tenant_from_key(key)
        if tenant != self._tenant_id:
            raise TenantIsolationError(
                f"Tenant {self._tenant_id!r} cannot access key {key!r}.", key=key
            )

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectMeta:
        self._require_tenant_key(key)
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes.")
        if not isinstance(content_type, str) or not content_type.strip():
            raise ValueError("content_type must be non-empty string.")
        # Idempotent: same key+bytes → same hash; overwrite is allowed but logged
        existing = self._store.get(key)
        if existing is not None and existing[0] == data:
            logger.debug("FakeS3 idempotent put: %s (hash %s)", key, _hash(data))
        else:
            logger.info("FakeS3 put: %s (%d bytes)", key, len(data))
        self._store[key] = (bytes(data), content_type)
        return ObjectMeta(
            key=key, content_hash=_hash(data), content_length=len(data), tenant_id=self._tenant_id
        )

    def get_object(self, key: str) -> tuple[bytes, ObjectMeta]:
        self._require_tenant_key(key)
        entry = self._store.get(key)
        if entry is None:
            raise ObjectNotFoundError(f"Object not found: {key!r}.", key=key)
        data, _ = entry
        return data, ObjectMeta(
            key=key, content_hash=_hash(data), content_length=len(data), tenant_id=self._tenant_id
        )

    def exists(self, key: str) -> bool:
        self._require_tenant_key(key)
        return key in self._store

    def delete(self, key: str) -> None:
        self._require_tenant_key(key)
        self._store.pop(key, None)

    # Introspection for failure-matrix tests only (not part of port)
    def _clear(self) -> None:
        self._store.clear()
