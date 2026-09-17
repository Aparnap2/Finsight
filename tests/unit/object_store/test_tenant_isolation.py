"""P5-03 tenant isolation — object_store (boundaries 5, 9, 11) unit suite.

Tenant isolation is key-prefix ``{tenant_id}/...`` enforced BEFORE store/network.

- Buckets are per-deployment (finsight-evidence-test etc.) — not per-tenant.
- FakeS3 + S3Adapter both call ``_require_tenant_key`` first; cross-tenant
  raises ``TenantIsolationError`` uniformly (no ObjectNotFoundError leak,
  no timing/size oracle, no credential leak).
- S3Adapter never reaches boto3 on cross-tenant (monkeypatched client would
  be called if isolation were after network).

Gated: not ministack — zero network/Docker required.
"""

from __future__ import annotations

import hashlib
import unittest.mock as mock

import pytest

from finance.object_store.errors import ObjectNotFoundError, TenantIsolationError
from finance.object_store.fake import FakeS3
from finance.object_store.s3_adapter import S3Adapter
from shared.aws.config import AwsSettings


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ── positive: own tenant succeeds ──────────────────────────────────────────


def test_positive_own_tenant_put_get_exists_delete() -> None:
    s3 = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/CASE-1027/evidence.json"
    data = b'{"amount": "35000.00"}'
    meta = s3.put_object(key, data, content_type="application/json")
    assert meta.tenant_id == "tenant-a"
    assert meta.content_hash == _hash(data)
    assert s3.exists(key) is True
    got, got_meta = s3.get_object(key)
    assert got == data
    assert got_meta.content_hash == _hash(data)
    s3.delete(key)
    assert s3.exists(key) is False


def test_positive_s3_adapter_own_tenant_before_network_stub() -> None:
    """S3Adapter positive path still delegates to boto3 — but tenant already validated."""
    settings = AwsSettings(aws_endpoint_url="http://localhost:4566")
    adapter = S3Adapter(tenant_id="tenant-a", settings=settings)
    fake_client = mock.MagicMock()
    fake_client.put_object.return_value = {}
    fake_client.get_object.return_value = {
        "Body": mock.MagicMock(read=mock.MagicMock(return_value=b"hello"))
    }
    fake_client.head_object.return_value = {}
    adapter._client = fake_client  # inject stub, no real boto3
    key = "tenant-a/case-1027/file.json"
    meta = adapter.put_object(key, b"hello")
    assert meta.tenant_id == "tenant-a"
    fake_client.put_object.assert_called_once()
    got, _ = adapter.get_object(key)
    assert got == b"hello"
    assert adapter.exists(key) is True
    adapter.delete(key)
    fake_client.delete_object.assert_called_once_with(Bucket=settings.s3_evidence_bucket, Key=key)


def test_positive_tenant_prefix_with_case_id_correlation() -> None:
    """CASE-1027 correlation id preserved in key, tenant still enforced."""
    s3 = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/CASE-1027/legacy-batch-001.csv"
    data = b"batch,data\n1,100.00\n"
    s3.put_object(key, data)
    _, meta = s3.get_object(key)
    assert "CASE-1027" in meta.key
    assert meta.tenant_id == "tenant-a"


# ── negative: cross-tenant before store/network ────────────────────────────


def test_negative_cross_tenant_fake_all_ops() -> None:
    s3_a = FakeS3(tenant_id="tenant-a")
    s3_b = FakeS3(tenant_id="tenant-b")
    key_a = "tenant-a/case-1/secret.json"
    key_b = "tenant-b/case-1/secret.json"
    s3_a.put_object(key_a, b"a-secret")
    s3_b.put_object(key_b, b"b-secret")
    with pytest.raises(TenantIsolationError):
        s3_a.get_object(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.put_object(key_b, b"evil")
    with pytest.raises(TenantIsolationError):
        s3_a.exists(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.delete(key_b)
    # own still ok
    assert s3_a.get_object(key_a)[0] == b"a-secret"


def test_negative_cross_tenant_s3_adapter_no_boto3_call() -> None:
    """S3Adapter cross-tenant must not touch boto3 client at all."""
    settings = AwsSettings(aws_endpoint_url="http://localhost:4566")
    adapter = S3Adapter(tenant_id="tenant-a", settings=settings)
    fake_client = mock.MagicMock()
    adapter._client = fake_client
    for bad_key in (
        "tenant-b/case-1/secret.json",
        "other-tenant/case-1/file",
        "tenant-a-bad/case/file",  # prefix mismatch
    ):
        with pytest.raises(TenantIsolationError):
            adapter.get_object(bad_key)
        with pytest.raises(TenantIsolationError):
            adapter.put_object(bad_key, b"x")
        with pytest.raises(TenantIsolationError):
            adapter.exists(bad_key)
        with pytest.raises(TenantIsolationError):
            adapter.delete(bad_key)
    fake_client.put_object.assert_not_called()
    fake_client.get_object.assert_not_called()
    fake_client.head_object.assert_not_called()
    fake_client.delete_object.assert_not_called()


def test_negative_cross_tenant_even_if_object_exists_in_other_store() -> None:
    """Even if tenant-b's object exists, tenant-a must get TenantIsolationError not 404."""
    s3_b = FakeS3(tenant_id="tenant-b")
    key_b = "tenant-b/case-1/exists.json"
    s3_b.put_object(key_b, b"exists")
    s3_a = FakeS3(tenant_id="tenant-a")
    # Not ObjectNotFoundError — uniform isolation error
    with pytest.raises(TenantIsolationError) as exc:
        s3_a.get_object(key_b)
    assert exc.value.key == key_b
    with pytest.raises(TenantIsolationError):
        s3_a.exists(key_b)


def test_negative_malformed_key_before_store() -> None:
    s3 = FakeS3(tenant_id="tenant-a")
    with pytest.raises(ValueError):
        s3.put_object("no-tenant-prefix.json", b"x")
    with pytest.raises(ValueError):
        s3.get_object("")
    with pytest.raises(ValueError):
        s3.exists("tenant-a")  # no slash


# ── adversarial: uniform error, no leak, no oracle ─────────────────────────


def test_adversarial_uniform_error_no_existential_leak() -> None:
    """Many tenant-b keys yield same TenantIsolationError — no 404 vs 403 leak."""
    s3_a = FakeS3(tenant_id="tenant-a")
    # tenant-b has one real object, one missing — attacker sees same error for both
    s3_b = FakeS3(tenant_id="tenant-b")
    s3_b.put_object("tenant-b/real/exists.json", b"real")
    for key in (
        "tenant-b/real/exists.json",
        "tenant-b/missing/notfound.json",
        "tenant-b/case-999/batch.csv",
    ):
        with pytest.raises(TenantIsolationError) as exc:
            s3_a.get_object(key)
        # error carries key, not existence hint
        assert exc.value.key == key
        # never ObjectNotFoundError — no leak whether B's object exists
        assert not isinstance(exc.value, ObjectNotFoundError)


def test_adversarial_no_credential_leak() -> None:
    s3 = FakeS3(tenant_id="tenant-a")
    try:
        s3.get_object("tenant-a/missing.json")
    except ObjectNotFoundError as exc:
        msg = str(exc).lower()
        assert "aws" not in msg
    try:
        s3.get_object("tenant-b/secret.json")
    except TenantIsolationError as exc2:
        msg2 = str(exc2).lower()
        assert "aws" not in msg2
        assert exc2.key == "tenant-b/secret.json"


def test_adversarial_malicious_metadata_not_bypass() -> None:
    """Object content claiming tenant-b does not bypass prefix check."""
    s3_a = FakeS3(tenant_id="tenant-a")
    # Store as tenant-a, content contains tenant-b claim — still tenant-a key
    key = "tenant-a/case-1/report.json"
    malicious = b'{"tenant_id": "tenant-b", "amount": "999999"}'
    s3_a.put_object(key, malicious)
    got, meta = s3_a.get_object(key)
    assert got == malicious
    # meta tenant is adapter's tenant, not content's claim
    assert meta.tenant_id == "tenant-a"
    # Cross-tenant key with malicious content still blocked before store
    with pytest.raises(TenantIsolationError):
        s3_a.put_object("tenant-b/case-1/report.json", malicious)


def test_adversarial_timing_oracle_same_error_path() -> None:
    """Cross-tenant isolation is prefix-check only — same code path regardless of store state."""
    s3_a = FakeS3(tenant_id="tenant-a")
    s3_a.put_object("tenant-a/case-1/own.json", b"own")
    # Both missing and existing B keys take same prefix-check path
    s3_b = FakeS3(tenant_id="tenant-b")
    s3_b.put_object("tenant-b/case-1/exists.json", b"exists")
    for key in ("tenant-b/case-1/exists.json", "tenant-b/case-1/missing.json"):
        with pytest.raises(TenantIsolationError):
            # exists() also uniform — never reveals whether B's object exists
            s3_a.exists(key)


def test_bucket_is_per_deployment_not_per_tenant() -> None:
    """All tenants share same bucket, isolation is key prefix — verify via S3Adapter bucket."""
    settings = AwsSettings()
    a = S3Adapter(tenant_id="tenant-a", settings=settings)
    b = S3Adapter(tenant_id="tenant-b", settings=settings)
    # Same bucket name for both tenants
    assert a._bucket == b._bucket == settings.s3_evidence_bucket
    assert a._bucket == "finsight-evidence-test"
    # Isolation is via key, not bucket
    assert a._tenant_id != b._tenant_id
