"""Bounded failure modes for the object-store port."""

from __future__ import annotations


class ObjectStoreError(Exception):
    """Base for all object-store failures — never leaks credentials."""

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


class ObjectNotFoundError(ObjectStoreError):
    """Requested key does not exist."""


class TenantIsolationError(ObjectStoreError):
    """Tenant attempted to access another tenant's key/prefix."""


class BucketNotFoundError(ObjectStoreError):
    """Target bucket does not exist or is not initialized."""


class AdapterUnavailableError(ObjectStoreError):
    """MiniStack/S3 endpoint unreachable (healthcheck/infra failure)."""
