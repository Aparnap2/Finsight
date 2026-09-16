"""Object-store domain (S3) — port + adapters + bounded failures.

Tenant-scoped keys, content-hash integrity, and explicit failure modes.
PostgreSQL remains the financial/idempotency authority; S3 is transport
and artifact store only (evidence/batch files). No financial truth moves
into S3, and no LLM path retrieves arbitrary S3 objects.
"""

from finance.object_store.errors import ObjectStoreError
from finance.object_store.fake import FakeS3
from finance.object_store.port import ObjectStorePort

__all__ = ["FakeS3", "ObjectStoreError", "ObjectStorePort"]
