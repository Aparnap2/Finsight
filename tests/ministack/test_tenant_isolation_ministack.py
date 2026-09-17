"""P5-03 MiniStack S3 tenant isolation — cross-tenant uniform error before network.

Boundaries 5, 9, 11: capability→API, execution→S3, cross-tenant uniform.
Gated ``pytest -m ministack``. Skipped when MiniStack is unavailable;
one test (endpoint config) passes even when down so suite reports
``1 passed 10 skipped`` without Docker — not a green lie.
"""

from __future__ import annotations

import hashlib
import socket
import uuid

import pytest

from finance.object_store.errors import ObjectNotFoundError, TenantIsolationError
from finance.object_store.s3_adapter import S3Adapter
from shared.aws.config import AwsSettings, get_aws_settings

pytestmark = pytest.mark.ministack


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ministack_reachable() -> bool:
    settings = get_aws_settings()
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
def s3_a() -> S3Adapter:
    if not _ministack_reachable():
        pytest.skip(f"MiniStack not at {get_aws_settings().aws_endpoint_url} — make ministack-up")
    tenant = f"tenant-a-{uuid.uuid4().hex[:6]}"
    adapter = S3Adapter(tenant_id=tenant)
    try:
        adapter.put_object(f"{tenant}/_probe/init", b"probe")
        adapter.delete(f"{tenant}/_probe/init")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"S3 bucket not initialized — run: make ministack-init ({exc})")
    return adapter


@pytest.fixture()
def s3_b() -> S3Adapter:
    if not _ministack_reachable():
        pytest.skip("MiniStack not reachable")
    tenant = f"tenant-b-{uuid.uuid4().hex[:6]}"
    return S3Adapter(tenant_id=tenant)


# ── always-pass even when MiniStack down (keeps suite 1 passed when skipped) ──


def test_ministack_tenant_isolation_endpoint_config_host_vs_container() -> None:
    """Host vs container endpoint abstraction is consistent — no network required."""
    host = AwsSettings(aws_endpoint_url="http://localhost:4566")
    assert host.container_endpoint() == "http://ministack:4566"
    assert host.host_endpoint() == "http://localhost:4566"
    assert host.is_ministack is True
    container = AwsSettings(aws_endpoint_url="http://ministack:4566")
    assert container.host_endpoint() == "http://localhost:4566"
    assert container.container_endpoint() == "http://ministack:4566"
    assert container.is_ministack is True
    # Buckets are per-deployment, not per-tenant
    assert host.s3_evidence_bucket == "finsight-evidence-test"
    assert host.s3_legacy_outbound_bucket == "finsight-legacy-outbound-test"
    assert host.s3_legacy_result_bucket == "finsight-legacy-result-test"


# ── cross-tenant before network (MiniStack required) ───────────────────────


def test_ministack_cross_tenant_before_network_uniform_error(
    s3_a: S3Adapter, s3_b: S3Adapter
) -> None:
    """Cross-tenant blocked before boto3 — uniform TenantIsolationError, no leak."""
    key_a = f"{s3_a._tenant_id}/case-1027/secret.json"
    key_b = f"{s3_b._tenant_id}/case-1027/secret.json"
    s3_a.put_object(key_a, b"a-secret")
    s3_b.put_object(key_b, b"b-secret")
    # A's adapter cannot touch B's key — isolation before network
    with pytest.raises(TenantIsolationError):
        s3_a.get_object(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.exists(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.delete(key_b)
    with pytest.raises(TenantIsolationError):
        s3_a.put_object(key_b, b"evil")
    # Own still works
    assert s3_a.get_object(key_a)[0] == b"a-secret"
    # No existential leak: B's real vs missing key → same TenantIsolationError
    missing_b = f"{s3_b._tenant_id}/missing/notfound.json"
    with pytest.raises(TenantIsolationError) as exc_real:
        s3_a.get_object(key_b)
    with pytest.raises(TenantIsolationError) as exc_missing:
        s3_a.get_object(missing_b)
    assert type(exc_real.value) is type(exc_missing.value) is TenantIsolationError
    assert exc_real.value.key == key_b
    assert exc_missing.value.key == missing_b


def test_ministack_cross_tenant_enumeration_no_oracle(s3_a: S3Adapter, s3_b: S3Adapter) -> None:
    """Enumerating many tenant-b keys yields same error — no timing/size oracle."""
    s3_b.put_object(f"{s3_b._tenant_id}/real/exists.json", b"real")
    for key in (
        f"{s3_b._tenant_id}/real/exists.json",
        f"{s3_b._tenant_id}/missing/notfound.json",
        f"{s3_b._tenant_id}/case-999/batch.csv",
    ):
        with pytest.raises(TenantIsolationError) as exc:
            s3_a.get_object(key)
        assert exc.value.key == key
        # Never ObjectNotFoundError for cross-tenant — no leak whether exists
        assert not isinstance(exc.value, ObjectNotFoundError)


def test_ministack_malicious_content_does_not_bypass(s3_a: S3Adapter) -> None:
    """Content claiming other tenant does not bypass key-prefix check."""
    key = f"{s3_a._tenant_id}/case-1/report.json"
    malicious = b'{"tenant_id": "tenant-b", "amount": "999999"}'
    s3_a.put_object(key, malicious)
    got, meta = s3_a.get_object(key)
    assert got == malicious
    assert meta.tenant_id == s3_a._tenant_id
    # Cross-tenant key still blocked even with same payload
    with pytest.raises(TenantIsolationError):
        s3_a.put_object(key.replace(s3_a._tenant_id, "tenant-b"), malicious)


def test_ministack_bucket_per_deployment_not_per_tenant(s3_a: S3Adapter, s3_b: S3Adapter) -> None:
    """Buckets are per-deployment, isolation is prefix — both adapters share bucket."""
    assert s3_a._bucket == s3_b._bucket == "finsight-evidence-test"
    assert s3_a._tenant_id != s3_b._tenant_id
    # Each can write own prefix in same bucket
    key_a = f"{s3_a._tenant_id}/shared-bucket/a.json"
    key_b = f"{s3_b._tenant_id}/shared-bucket/b.json"
    s3_a.put_object(key_a, b"a")
    s3_b.put_object(key_b, b"b")
    assert s3_a.get_object(key_a)[0] == b"a"
    assert s3_b.get_object(key_b)[0] == b"b"
    # But cross still blocked
    with pytest.raises(TenantIsolationError):
        s3_a.get_object(key_b)


def test_ministack_no_credential_leak_cross_tenant(s3_a: S3Adapter, s3_b: S3Adapter) -> None:
    """TenantIsolationError messages never carry credentials."""
    key_b = f"{s3_b._tenant_id}/case-1/secret.json"
    s3_b.put_object(key_b, b"secret")
    try:
        s3_a.get_object(key_b)
    except TenantIsolationError as exc:
        msg = str(exc).lower()
        assert "aws" not in msg
        assert "secret" not in msg or "secret.json" in msg  # key allowed, credential not
        assert "access" not in msg
        assert exc.key == key_b


def test_ministack_put_get_hash_preserved_tenant_scoped(s3_a: S3Adapter) -> None:
    """Hash/length preserved, tenant_id in meta matches adapter."""
    key = f"{s3_a._tenant_id}/CASE-1027/batch.csv"
    data = b"batch,data\n1,100.00\n" * 200
    meta = s3_a.put_object(key, data, content_type="text/csv")
    assert meta.content_hash == _hash(data)
    assert meta.content_length == len(data)
    assert meta.tenant_id == s3_a._tenant_id
    got, got_meta = s3_a.get_object(key)
    assert got == data
    assert got_meta.content_hash == _hash(data)
    assert "CASE-1027" in got_meta.key


def test_ministack_exists_delete_own_tenant_only(s3_a: S3Adapter, s3_b: S3Adapter) -> None:
    """exists/delete are tenant-scoped before network as well."""
    key_a = f"{s3_a._tenant_id}/case-1027/evidence.json"
    s3_a.put_object(key_a, b"own")
    assert s3_a.exists(key_a) is True
    with pytest.raises(TenantIsolationError):
        s3_a.exists(f"{s3_b._tenant_id}/case-1027/evidence.json")
    # delete own
    s3_a.delete(key_a)
    assert s3_a.exists(key_a) is False
    with pytest.raises(ObjectNotFoundError):
        s3_a.get_object(key_a)
    with pytest.raises(TenantIsolationError):
        s3_a.delete(f"{s3_b._tenant_id}/case-1/file")
