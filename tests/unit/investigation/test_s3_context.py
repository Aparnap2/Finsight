"""P5-02 S3 boundary — FakeS3 evidence via context builder, MiniStack reuse."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.investigation.context import build_context
from agents.investigation.request import InvestigationRequest
from finance.object_store.fake import FakeS3


def _req(**overrides):
    base = dict(
        exception_id="case-1027",
        exception_type="I-REFUND-LAG",
        tenant_id="tenant-a",
        actor="user-001",
        evidence_ids=("ev-s3-001",),
        context_window="ok",
        capability_allowlist=("get_stripe_payment",),
        round_budget=3,
    )
    base.update(overrides)
    return InvestigationRequest(**base)


def test_s3_evidence_via_fake_s3_builds_context():
    fake = FakeS3(tenant_id="tenant-a")
    key = "tenant-a/case-1027/evidence.json"
    data = b'{"amount": "35000.00"}'
    meta = fake.put_object(key, data, content_type="application/json")
    # Evidence store is server-side retrieval of S3 object, not LLM-provided key
    store = {
        "ev-s3-001": {
            "tenant_id": "tenant-a",
            "case_id": "case-1027",
            "source_type": "s3",
            "source_id": key,
            "content": data.decode(),
            "content_hash": meta.content_hash,
            "retrieved_at": datetime.now(UTC),
            "provenance": f"s3:{key}",
        }
    }
    req = _req()
    ctx = build_context(req, store)
    assert ctx.evidence[0].source_type == "s3"
    assert ctx.evidence[0].content_hash == meta.content_hash
    assert ctx.tenant_id == "tenant-a"


def test_s3_cross_tenant_via_fake_s3_rejected():
    fake_b = FakeS3(tenant_id="tenant-b")
    key_b = "tenant-b/case-999/evil.json"
    fake_b.put_object(key_b, b"evil")
    # Attempt to build context for tenant-a with tenant-b's S3 object
    store = {
        "ev-s3-001": {
            "tenant_id": "tenant-b",
            "case_id": "case-1027",
            "source_type": "s3",
            "source_id": key_b,
            "content": "evil",
            "retrieved_at": datetime.now(UTC),
            "provenance": f"s3:{key_b}",
        }
    }
    req = _req()
    with pytest.raises(ValueError, match="tenant mismatch"):
        build_context(req, store)
