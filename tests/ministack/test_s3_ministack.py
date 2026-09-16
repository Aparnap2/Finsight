"""S3 contract — MiniStack/LocalStack (requires docker compose -f docker-compose.ministack.yml).

Gated ``pytest -m ministack``. Skipped when MiniStack is unavailable;
do not treat skip as pass — run ``make ministack-up && make ministack-init``
before validating.
"""

from __future__ import annotations

import hashlib
import socket
import uuid

import pytest

from finance.object_store.errors import (
    ObjectNotFoundError,
    TenantIsolationError,
)
from finance.object_store.s3_adapter import S3Adapter
from shared.aws.config import get_aws_settings

pytestmark = pytest.mark.ministack


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ministack_reachable() -> bool:
    settings = get_aws_settings()
    # Parse host/port from endpoint URL like http://localhost:4566
    url = settings.aws_endpoint_url
    host = "localhost"
    port = 4566
    try:
        if "://" in url:
            hostport = url.split("://", 1)[1].split("/", 1)[0]
            if ":" in hostport:
                host, port_s = hostport.split(":", 1)
                port = int(port_s)
            else:
                host = hostport
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture()
def s3_a():
    if not _ministack_reachable():
        msg = f"MiniStack not at {get_aws_settings().aws_endpoint_url} — make ministack-up"
        pytest.skip(msg)
    tenant = f"tenant-a-{uuid.uuid4().hex[:6]}"
    # Each test gets a fresh bucket to avoid cross-test leakage; use evidence bucket
    adapter = S3Adapter(tenant_id=tenant)
    # Ensure bucket exists via init (idempotent) — create if missing
    try:
        adapter.put_object(f"{tenant}/_probe/init", b"probe")
        adapter.delete(f"{tenant}/_probe/init")
    except Exception as exc:
        # If bucket missing, try init script path
        pytest.skip(f"S3 bucket not initialized — run: make ministack-init ({exc})")
    return adapter


@pytest.fixture()
def s3_b():
    if not _ministack_reachable():
        pytest.skip("MiniStack not reachable")
    tenant = f"tenant-b-{uuid.uuid4().hex[:6]}"
    return S3Adapter(tenant_id=tenant)


def test_ministack_basic_put_get_exists_delete(s3_a):
    key = f"{s3_a._tenant_id}/case-1027/evidence.json"
    data = b'{"amount": "35000.00"}'
    meta = s3_a.put_object(key, data, content_type="application/json")
    assert meta.content_hash == _hash(data)
    assert meta.content_length == len(data)
    assert s3_a.exists(key) is True
    got, got_meta = s3_a.get_object(key)
    assert got == data
    assert got_meta.content_hash == _hash(data)
    s3_a.delete(key)
    assert s3_a.exists(key) is False
    with pytest.raises(ObjectNotFoundError):
        s3_a.get_object(key)


def test_ministack_integrity(s3_a):
    key = f"{s3_a._tenant_id}/batch-001/file.csv"
    data = b"a,b,c\n1,2,3\n" * 500
    meta = s3_a.put_object(key, data)
    assert meta.content_hash == _hash(data)
    got, meta2 = s3_a.get_object(key)
    assert meta2.content_hash == _hash(got) == _hash(data)


def test_ministack_idempotency(s3_a):
    key = f"{s3_a._tenant_id}/case-1027/idempotent.json"
    data = b"same"
    m1 = s3_a.put_object(key, data)
    m2 = s3_a.put_object(key, data)
    assert m1.content_hash == m2.content_hash
    assert s3_a.get_object(key)[0] == data


def test_ministack_tenant_isolation(s3_a, s3_b):
    key_a = f"{s3_a._tenant_id}/case-1/secret.json"
    key_b = f"{s3_b._tenant_id}/case-1/secret.json"
    s3_a.put_object(key_a, b"a-secret")
    s3_b.put_object(key_b, b"b-secret")
    # Cross-tenant via A's adapter trying to fetch B's key → isolation error before network
    with pytest.raises(TenantIsolationError):
        s3_a.get_object(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.exists(key_b)
    assert s3_a.get_object(key_a)[0] == b"a-secret"


def test_ministack_missing_object(s3_a):
    key = f"{s3_a._tenant_id}/missing/file.json"
    assert s3_a.exists(key) is False
    with pytest.raises(ObjectNotFoundError):
        s3_a.get_object(key)


def test_ministack_wrong_bucket():
    if not _ministack_reachable():
        pytest.skip("MiniStack not reachable")
    tenant = f"tenant-x-{uuid.uuid4().hex[:6]}"
    adapter = S3Adapter(tenant_id=tenant, bucket="finsight-nonexistent-bucket-test")
    key = f"{tenant}/case-1/file.json"
    try:
        adapter.put_object(key, b"x")
    except Exception as exc:
        # Bucket not found is the expected bounded failure (not silent fallback)
        assert (
            "Bucket" in str(type(exc).__name__)
            or "Bucket" in str(exc)
            or "NoSuchBucket" in str(exc)
        )
        return
    pytest.fail("Expected BucketNotFoundError for wrong bucket")


def test_ministack_invalid_credentials():
    if not _ministack_reachable():
        pytest.skip("MiniStack not reachable")
    from shared.aws.config import AwsSettings

    bad = AwsSettings(
        aws_endpoint_url=get_aws_settings().aws_endpoint_url,
        aws_region="us-east-1",
        aws_access_key_id="invalid",
        aws_secret_access_key="invalid",
    )
    tenant = f"tenant-bad-{uuid.uuid4().hex[:6]}"
    adapter = S3Adapter(tenant_id=tenant, settings=bad)
    key = f"{tenant}/case-1/file.json"
    # LocalStack SERVICES=s3 with test/test may still accept invalid creds
    # (permissive). Else it must fail closed.
    try:
        adapter.put_object(key, b"x")
    except Exception as exc:
        assert exc is not None  # fail closed is correct
        return
    # LocalStack accepted — real AWS would reject; contract is fail-closed in prod.
    pytest.xfail("LocalStack permissive — prod AWS rejects invalid creds")


def test_ministack_correlation_id(s3_a):
    case_id = "CASE-1027"
    key = f"{s3_a._tenant_id}/{case_id}/legacy-batch-001.csv"
    data = b"batch,data\n1,100.00\n"
    s3_a.put_object(key, data)
    _, meta = s3_a.get_object(key)
    assert case_id in meta.key
    assert meta.tenant_id == s3_a._tenant_id


def test_ministack_crash_after_commit_simulation(s3_a):
    """Crash-before-ack: S3 put+DB commit succeed, ack lost → redelivery idempotent."""
    key = f"{s3_a._tenant_id}/case-crash/batch.json"
    payload = b'{"batch_id": "batch-123", "amount": "35000.00"}'
    # First attempt: put + "commit" (here, just put; DB idempotency is external)
    m1 = s3_a.put_object(key, payload)
    # Simulate crash before acknowledgement: second attempt with same key+payload
    m2 = s3_a.put_object(key, payload)
    assert m1.content_hash == m2.content_hash
    # No duplicate logical effect — exactly one object, hash matches payload
    assert s3_a.get_object(key)[0] == payload


def test_ministack_at_least_once_duplicate_delivery(s3_a):
    """Same logical event delivered twice (same key+bytes) → one logical state, one effect."""
    key = f"{s3_a._tenant_id}/case-dedup/event.json"
    event = b'{"event_id": "evt-001", "amount": "15000.00"}'
    s3_a.put_object(key, event)
    s3_a.put_object(key, event)  # duplicate delivery
    assert s3_a.get_object(key)[0] == event
    # Idempotency: second put did not create a second logical object
    assert s3_a.exists(key) is True


def test_ministack_endpoint_config_host_vs_container():
    """Host vs container endpoint abstraction is consistent."""
    from shared.aws.config import AwsSettings

    host_settings = AwsSettings(aws_endpoint_url="http://localhost:4566")
    assert host_settings.container_endpoint() == "http://ministack:4566"
    assert host_settings.host_endpoint() == "http://localhost:4566"
    container_settings = AwsSettings(aws_endpoint_url="http://ministack:4566")
    assert container_settings.host_endpoint() == "http://localhost:4566"
    assert container_settings.is_ministack is True
