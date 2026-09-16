"""Boto3-backed S3 adapter — MiniStack or real AWS via shared/aws/config.

Uses ``shared.aws.config.AwsSettings`` (endpoint/region/test credentials)
and a single bucket per deployment (``s3_evidence_bucket``). Tenant
isolation is enforced before any boto3 call: keys must be
``{tenant_id}/...`` and the adapter's ``tenant_id`` constructor fixes
the allowed tenant. Cross-tenant attempts raise without network.

Only S3 is supported (``SERVICES=s3`` in compose). No SQS/SNS.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from finance.object_store.errors import (
    AdapterUnavailableError,
    BucketNotFoundError,
    ObjectNotFoundError,
    ObjectStoreError,
    TenantIsolationError,
)
from finance.object_store.port import ObjectMeta
from shared.aws.config import AwsSettings, get_aws_settings

logger = logging.getLogger(__name__)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tenant_from_key(key: str) -> str:
    if not key or "/" not in key:
        return ""
    return key.split("/", 1)[0].strip()


class S3Adapter:
    """Boto3 S3 adapter — tenant-scoped, hash-checked, test-credential safe."""

    def __init__(
        self,
        tenant_id: str,
        *,
        settings: AwsSettings | None = None,
        bucket: str | None = None,
    ) -> None:
        tenant = tenant_id.strip()
        if not tenant:
            raise ValueError("S3Adapter tenant_id must be non-empty.")
        self._tenant_id = tenant
        self._settings = settings or get_aws_settings()
        self._bucket = bucket or self._settings.s3_evidence_bucket
        self._client: Any | None = None

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

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3  # noqa: F401  # availability checked via ImportError branch
        except ImportError as exc:
            raise AdapterUnavailableError("boto3 not installed for S3 adapter.") from exc
        try:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.aws_endpoint_url,
                region_name=self._settings.aws_region,
                aws_access_key_id=self._settings.aws_access_key_id,
                aws_secret_access_key=self._settings.aws_secret_access_key,
            )
            return self._client
        except Exception as exc:
            raise AdapterUnavailableError(
                f"S3 client init failed for {self._settings.aws_endpoint_url}: {exc}"
            ) from exc

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectMeta:
        self._require_tenant_key(key)
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes.")
        if not isinstance(content_type, str) or not content_type.strip():
            raise ValueError("content_type must be non-empty string.")
        client = self._client_or_raise()
        try:
            client.put_object(
                Bucket=self._bucket, Key=key, Body=bytes(data), ContentType=content_type
            )
        except Exception as exc:
            # Bucket missing → typed error; endpoint down → AdapterUnavailable
            msg = str(exc)
            if "NoSuchBucket" in msg or "bucket" in msg.lower() and "not" in msg.lower():
                raise BucketNotFoundError(
                    f"Bucket {self._bucket!r} not initialized.", key=key
                ) from exc
            if (
                "EndpointConnectionError" in type(exc).__name__
                or "Connection" in type(exc).__name__
            ):
                raise AdapterUnavailableError(
                    f"S3 endpoint unreachable {self._settings.aws_endpoint_url}: {exc}"
                ) from exc
            # Preserve typed ClientError not-found vs generic
            try:
                from botocore.exceptions import ClientError as _CE  # noqa: N814

                if isinstance(exc, _CE):
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code == "NoSuchBucket":
                        raise BucketNotFoundError(
                            f"Bucket {self._bucket!r} not initialized.", key=key
                        ) from exc
            except Exception:
                pass
            raise
        logger.info(
            "S3 put: %s -> %s (%d bytes, hash %s)", self._bucket, key, len(data), _hash(data)[:8]
        )
        return ObjectMeta(
            key=key, content_hash=_hash(data), content_length=len(data), tenant_id=self._tenant_id
        )

    def get_object(self, key: str) -> tuple[bytes, ObjectMeta]:
        self._require_tenant_key(key)
        client = self._client_or_raise()
        try:
            resp = client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = resp["Body"].read()
            return body, ObjectMeta(
                key=key,
                content_hash=_hash(body),
                content_length=len(body),
                tenant_id=self._tenant_id,
            )
        except Exception as exc:
            try:
                from botocore.exceptions import ClientError as _CE  # noqa: N814

                if isinstance(exc, _CE):
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code in ("NoSuchKey", "NoSuchBucket", "404"):
                        if code == "NoSuchBucket":
                            raise BucketNotFoundError(
                                f"Bucket {self._bucket!r} not initialized.", key=key
                            ) from exc
                        raise ObjectNotFoundError(f"Object not found: {key!r}.", key=key) from exc
                    # Tenant isolation at S3 level is key-prefix; 404 is already not-found
            except ObjectStoreError:
                raise
            except Exception:
                pass
            if "NoSuchKey" in str(exc) or "Not Found" in str(exc):
                raise ObjectNotFoundError(f"Object not found: {key!r}.", key=key) from exc
            if "EndpointConnectionError" in type(exc).__name__:
                raise AdapterUnavailableError(f"S3 endpoint unreachable: {exc}") from exc
            raise

    def exists(self, key: str) -> bool:
        self._require_tenant_key(key)
        client = self._client_or_raise()
        try:
            client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as exc:
            try:
                from botocore.exceptions import ClientError as _CE  # noqa: N814

                if isinstance(exc, _CE):
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code in ("404", "NoSuchKey", "NotFound"):
                        return False
            except Exception:
                pass
            if "404" in str(exc) or "NoSuchKey" in str(exc) or "NotFound" in str(exc):
                return False
            raise

    def delete(self, key: str) -> None:
        self._require_tenant_key(key)
        client = self._client_or_raise()
        client.delete_object(Bucket=self._bucket, Key=key)
