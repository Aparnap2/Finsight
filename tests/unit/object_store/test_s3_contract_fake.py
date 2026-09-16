"""S3 contract — FakeS3 (zero-network, fast). Gated NOT ministack."""

from __future__ import annotations

import hashlib

import pytest

from finance.object_store.errors import ObjectNotFoundError, TenantIsolationError
from finance.object_store.fake import FakeS3


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_put_get_exists_delete_basic():
    """Basic lifecycle: put → exists → get → delete → not exists."""
    s3 = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/case-1027/evidence.json"
    data = b'{"amount": "35000.00"}'
    meta = s3.put_object(key, data, content_type="application/json")
    assert meta.key == key
    assert meta.content_hash == _hash(data)
    assert meta.content_length == len(data)
    assert meta.tenant_id == "tenant-a"
    assert s3.exists(key) is True
    got, got_meta = s3.get_object(key)
    assert got == data
    assert got_meta.content_hash == _hash(data)
    assert got_meta.content_length == len(data)
    s3.delete(key)
    assert s3.exists(key) is False
    with pytest.raises(ObjectNotFoundError):
        s3.get_object(key)


def test_integrity_content_hash_preserved():
    """Content hash and length are preserved exactly."""
    s3 = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/batch-001/file.csv"
    data = b"a,b,c\n1,2,3\n" * 100
    meta = s3.put_object(key, data)
    assert meta.content_hash == _hash(data)
    assert meta.content_length == len(data)
    got, meta2 = s3.get_object(key)
    assert meta2.content_hash == _hash(got)
    assert len(got) == len(data)


def test_idempotency_same_key_same_bytes():
    """Repeated put with same key+bytes → same hash, single logical object."""
    s3 = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/case-1027/idempotent.json"
    data = b"same"
    m1 = s3.put_object(key, data)
    m2 = s3.put_object(key, data)
    assert m1.content_hash == m2.content_hash == _hash(data)
    # Last write wins for different bytes (no silent duplicate financial effect)
    data2 = b"different"
    m3 = s3.put_object(key, data2)
    assert m3.content_hash == _hash(data2)
    assert m3.content_hash != m1.content_hash
    got, _ = s3.get_object(key)
    assert got == data2


def test_tenant_isolation():
    """Tenant A cannot get/put/exists/delete Tenant B's prefix."""
    s3_a = FakeS3(tenant_id="tenant-a")
    s3_b = FakeS3(tenant_id="tenant-b")
    key_a = "tenant-a/case-1/secret.json"
    key_b = "tenant-b/case-1/secret.json"
    s3_a.put_object(key_a, b"a-secret")
    s3_b.put_object(key_b, b"b-secret")
    # Cross-tenant attempts must raise without touching backing store
    with pytest.raises(TenantIsolationError):
        s3_a.get_object(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.put_object(key_b, b"evil")
    with pytest.raises(TenantIsolationError):
        s3_a.exists(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.delete(key_b)
    # Legitimate tenant can still read own
    assert s3_a.get_object(key_a)[0] == b"a-secret"


def test_failure_missing_object():
    """Missing object → bounded ObjectNotFoundError, not silent fallback."""
    s3 = FakeS3(tenant_id="tenant-a")
    with pytest.raises(ObjectNotFoundError):
        s3.get_object("tenant-a/missing/file.json")
    # exists returns False, not raise
    assert s3.exists("tenant-a/missing/file.json") is False


def test_failure_malformed_key():
    """Non-tenant-prefixed key → ValueError (never reaches store)."""
    s3 = FakeS3(tenant_id="tenant-a")
    with pytest.raises(ValueError):
        s3.put_object("no-tenant-prefix.json", b"x")
    with pytest.raises(ValueError):
        s3.get_object("")
    with pytest.raises(ValueError):
        s3.exists("tenant-a")  # no slash


def test_failure_wrong_content_type():
    """Empty content_type → ValueError, credentials never logged."""
    s3 = FakeS3(tenant_id="tenant-a")
    with pytest.raises(ValueError):
        s3.put_object("tenant-a/c/a.json", b"x", content_type=" ")


def test_failure_wrong_tenant_wrong_key_prefix():
    """Wrong bucket/prefix simulated as wrong tenant prefix → TenantIsolationError."""
    s3 = FakeS3(tenant_id="tenant-a")
    for bad_key in ("tenant-b/a.json", "other/case/file"):
        with pytest.raises(TenantIsolationError):
            s3.put_object(bad_key, b"x")


def test_security_no_credential_leak_in_exception():
    """Exceptions never carry credentials."""
    s3 = FakeS3(tenant_id="tenant-a")
    try:
        s3.get_object("tenant-a/notfound.json")
    except ObjectNotFoundError as exc:
        assert "AWS" not in str(exc)
        assert "secret" not in str(exc).lower()
        assert "access" not in str(exc).lower()
        assert exc.key == "tenant-a/notfound.json"


def test_correlation_id_preserved_through_key():
    """Case correlation id encoded in key survives put→get."""
    s3 = FakeS3(tenant_id="tenant-a")
    case_id = "CASE-1027"
    key = f"tenant-a/{case_id}/legacy-batch-001.csv"
    data = b"batch,data\n1,100.00\n"
    s3.put_object(key, data)
    _, meta = s3.get_object(key)
    assert case_id in meta.key
    assert meta.tenant_id == "tenant-a"


def test_ledger_batch_idempotency_simulation():
    """Same logical batch bytes with same key → idempotent, not duplicate financial effect."""
    s3 = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/batch-123/result.csv"
    payload = b"tenant-a,batch-123,35000.00\n"
    m1 = s3.put_object(key, payload)
    m2 = s3.put_object(key, payload)
    assert m1.content_hash == m2.content_hash
    assert s3.get_object(key)[0] == payload
