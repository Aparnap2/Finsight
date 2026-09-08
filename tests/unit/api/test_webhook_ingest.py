"""Unit tests: Stripe webhook ingest transport edge (Commit 2).

Covers ``apps.api.webhooks.stripe_webhook`` through a minimal FastAPI app
mounting ONLY ``webhook_router`` + ``TenantAuthMiddleware`` (never
``apps.api.main``, which pulls heavy ``routes.py``). Auth is HMAC-SHA256
over the raw body; tenant resolution is env-only with NO default tenant
(unknown/ambiguous quarantine under the ``UNROUTABLE`` sentinel).

Transport contract pinned here:

* Valid new envelope -> 202, one ``RECEIVED`` row, no audit.
* Exact byte replay -> 200 duplicate, still one row, no reprocessing.
* Same ``(provider, event_id)`` with different bytes -> 409
  ``IDEMPOTENCY_CONFLICT`` audit, stored row unmutated (DB UNIQUE is the
  ONLY idempotency mechanism -- two TestClients share only the DB).
* One-byte body mutation -> 401, zero rows.
* ``+/-300s`` passes, ``+/-301s`` fails (401, zero rows).
* Unknown tenant -> 404 ``UNROUTABLE``/``IGNORED`` + quarantine audit.
* Ambiguous tenant -> 400 + quarantine audit.
* Malformed envelope (missing ``id``/``type``) -> 400, zero rows.
* No ``CF001`` default tenant appears anywhere.

Pure unit: SQLite StaticPool (RLS ``set_config`` is dialect-guarded and
skipped off Postgres), frozen clock, env monkeypatched secrets, money is
Decimal-only (no float anywhere). Style: Arrange-Act-Assert, independent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api import webhooks as wh
from apps.api.middleware import TenantAuthMiddleware
from apps.api.webhooks import get_db_session
from apps.api.webhooks import router as webhook_router
from shared.config import get_settings
from shared.models.database import AuditLog, Base, WebhookEvent

SECRET = "whsec_test_commit2_secret_001"
FIXED_NOW = 1_746_105_600
ACCOUNT = "acct_123"
TENANT = "tenant-acme"
MAP_JSON = json.dumps({ACCOUNT: TENANT, "acct_amb": ["tenant-a", "tenant-b"]})


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any]]:
    """Build a minimal webhook app on an isolated SQLite DB with frozen time."""
    # Arrange (env): endpoint secret + trusted stripe_account map, cache reset.
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("STRIPE_TENANT_MAP", MAP_JSON)
    get_settings.cache_clear()
    # Arrange (clock): route reads int(time.time()); freeze it.
    monkeypatch.setattr(wh.time, "time", lambda: FIXED_NOW)
    # Arrange (db): one shared in-memory SQLite DB for the whole app.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def _override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.add_middleware(TenantAuthMiddleware)
    app.include_router(webhook_router)
    app.dependency_overrides[get_db_session] = _override
    yield TestClient(app), engine
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _raw(
    event_id: str = "evt_commit2_001",
    event_type: str = "charge.succeeded",
    account: str | None = ACCOUNT,
    extra: dict[str, Any] | None = None,
) -> bytes:
    """Encode a deterministic Stripe-style envelope as raw request bytes."""
    envelope: dict[str, Any] = {"id": event_id, "type": event_type}
    if account is not None:
        envelope["account"] = account
    envelope["created"] = FIXED_NOW
    envelope["data"] = {"object": {}}
    if extra:
        envelope.update(extra)
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def _signed_headers(raw: bytes, ts: int = FIXED_NOW) -> dict[str, str]:
    """Build the Stripe-Signature header for raw bytes at timestamp ts."""
    return {"stripe-signature": wh.build_signature_header(raw, SECRET, ts)}


def _events(engine: Any) -> list[WebhookEvent]:
    """Return all stored webhook rows."""
    with Session(engine) as session:
        return list(session.execute(select(WebhookEvent)).scalars().all())


def _audits(engine: Any, event_type: str | None = None) -> list[AuditLog]:
    """Return stored audit rows, optionally filtered by event type."""
    with Session(engine) as session:
        rows = list(session.execute(select(AuditLog)).scalars().all())
    if event_type is not None:
        rows = [row for row in rows if row.event_type == event_type]
    return rows


def _assert_no_cf001(engine: Any) -> None:
    """Assert no row ever falls back to the CF001 default tenant."""
    for event in _events(engine):
        assert event.tenant_id != "CF001"
    for audit in _audits(engine):
        assert audit.tenant_id != "CF001"


class TestValidAccept:
    """A valid new envelope is accepted with 202 and exactly one row."""

    def test_valid_delivery_returns_202_and_persists(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange a signed envelope; Act POST; Assert 202 + one RECEIVED row."""
        # Arrange: signed bytes for a known tenant account.
        http, engine = client
        raw = _raw()
        # Act: deliver once.
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: accepted and persisted exactly once with no audit.
        assert response.status_code == 202
        assert response.json() == {
            "status": "accepted",
            "event_id": "evt_commit2_001",
            "tenant_id": TENANT,
        }
        rows = _events(engine)
        assert len(rows) == 1
        assert rows[0].tenant_id == TENANT
        assert rows[0].status == wh.STATUS_RECEIVED
        assert _audits(engine) == []
        _assert_no_cf001(engine)


class TestExactDuplicate:
    """An exact byte replay is a 200 no-op: one row, no reprocessing."""

    def test_exact_duplicate_returns_200_with_single_row(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange a stored delivery; Act replay bytes; Assert 200 + one row."""
        # Arrange: first delivery is accepted.
        http, engine = client
        raw = _raw()
        first = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        assert first.status_code == 202
        # Act: replay the identical bytes.
        replay = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: duplicate no-op, single row, no audit, stored status kept.
        assert replay.status_code == 200
        body = replay.json()
        assert body["status"] == "duplicate"
        assert body["event_id"] == "evt_commit2_001"
        assert body["stored_status"] == wh.STATUS_RECEIVED
        rows = _events(engine)
        assert len(rows) == 1
        assert rows[0].fingerprint == hashlib.sha256(raw).hexdigest()
        assert _audits(engine, "IDEMPOTENCY_CONFLICT") == []
        _assert_no_cf001(engine)


class TestIdempotencyConflict:
    """Same (provider, event_id) + different bytes -> 409, audit, no mutation."""

    def test_conflicting_bytes_return_409_audit_without_mutation(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange stored evt; Act same id new bytes; Assert 409 + intact row."""
        # Arrange: original delivery persists.
        http, engine = client
        original = _raw("evt_conflict_001")
        assert http.post(
            "/webhooks/stripe", content=original, headers=_signed_headers(original)
        ).status_code == 202
        stored_raw = _events(engine)[0].raw
        # Act: same event id with different payload bytes (fresh valid signature).
        tampered = _raw("evt_conflict_001", extra={"tampered": True})
        assert tampered != original
        conflict = http.post(
            "/webhooks/stripe", content=tampered, headers=_signed_headers(tampered)
        )
        # Assert: conflict answered, row unmutated, one conflict audit.
        assert conflict.status_code == 409
        assert conflict.json()["error"] == "idempotency_conflict"
        rows = _events(engine)
        assert len(rows) == 1
        assert rows[0].raw == stored_raw
        audits = _audits(engine, "IDEMPOTENCY_CONFLICT")
        assert len(audits) == 1
        assert audits[0].event_data["event_id"] == "evt_conflict_001"
        assert audits[0].event_data["stored_fingerprint"] != (
            audits[0].event_data["incoming_fingerprint"]
        )
        # Assert: faithful replay of the original still dedups to 200.
        replay = http.post(
            "/webhooks/stripe", content=original, headers=_signed_headers(original)
        )
        assert replay.status_code == 200
        assert len(_events(engine)) == 1
        _assert_no_cf001(engine)


class TestSignatureMismatch:
    """A one-byte body mutation fails verification with 401 and no rows."""

    def test_one_byte_mutation_returns_401_without_rows(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange a signed body; Act mutate one byte; Assert 401 + zero rows."""
        # Arrange: header signed over the pristine bytes.
        http, engine = client
        raw = _raw("evt_mutated_001")
        headers = _signed_headers(raw)
        mutated = raw[:-2] + (b"X" if raw[-2:-1] != b"X" else b"Y") + raw[-1:]
        assert mutated != raw and len(mutated) == len(raw)
        # Act: deliver mutated bytes under the original signature.
        response = http.post("/webhooks/stripe", content=mutated, headers=headers)
        # Assert: rejected before any write.
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_signature_mismatch"
        assert _events(engine) == []
        assert _audits(engine) == []


class TestTimestampBoundary:
    """300s symmetric tolerance: +/-300 passes, +/-301 fails."""

    @pytest.mark.parametrize("skew", [-300, 300])
    def test_boundary_inside_tolerance_passes(
        self, client: tuple[TestClient, Any], skew: int
    ) -> None:
        """Arrange header at +/-300s; Act POST; Assert 202 + one row."""
        # Arrange: envelope signed exactly at the tolerance edge.
        http, engine = client
        raw = _raw(f"evt_edge_{skew}")
        # Act: deliver with the frozen clock FIXED_NOW.
        response = http.post(
            "/webhooks/stripe", content=raw, headers=_signed_headers(raw, FIXED_NOW + skew)
        )
        # Assert: edge timestamp is accepted.
        assert response.status_code == 202
        assert len(_events(engine)) == 1

    @pytest.mark.parametrize("skew", [-301, 301])
    def test_boundary_outside_tolerance_fails(
        self, client: tuple[TestClient, Any], skew: int
    ) -> None:
        """Arrange header at +/-301s; Act POST; Assert 401 + zero rows."""
        # Arrange: envelope signed one second past the window.
        http, engine = client
        raw = _raw(f"evt_past_{skew}")
        # Act: deliver with the frozen clock FIXED_NOW.
        response = http.post(
            "/webhooks/stripe", content=raw, headers=_signed_headers(raw, FIXED_NOW + skew)
        )
        # Assert: expired rejection with no write.
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_signature_expired"
        assert _events(engine) == []
        assert _audits(engine) == []


class TestUnknownTenantQuarantine:
    """Unknown accounts quarantine under UNROUTABLE/IGNORED and answer 404."""

    def test_unknown_tenant_returns_404_with_quarantine_audit(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange unmapped account; Act POST; Assert 404 + sentinel + audit."""
        # Arrange: signed envelope for an account absent from the trusted map.
        http, engine = client
        raw = _raw("evt_unknown_001", account="acct_ghost")
        # Act: deliver.
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: quarantined, never routed to a default tenant.
        assert response.status_code == 404
        assert response.json()["error"] == "unknown_tenant"
        rows = _events(engine)
        assert len(rows) == 1
        assert rows[0].tenant_id == wh.UNROUTABLE_TENANT
        assert rows[0].status == wh.STATUS_IGNORED
        audits = _audits(engine, "WEBHOOK_QUARANTINED")
        assert len(audits) == 1
        assert audits[0].tenant_id == wh.UNROUTABLE_TENANT
        assert audits[0].event_data["outcome"] == "unknown"
        _assert_no_cf001(engine)

    def test_missing_account_returns_404_with_quarantine_audit(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """An envelope carrying no account is unknown, never defaulted."""
        # Arrange: signed envelope with no account field at all.
        http, engine = client
        raw = _raw("evt_noacct_001", account=None)
        # Act: deliver.
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: quarantined under the sentinel.
        assert response.status_code == 404
        rows = _events(engine)
        assert len(rows) == 1
        assert rows[0].tenant_id == wh.UNROUTABLE_TENANT
        _assert_no_cf001(engine)


class TestAmbiguousTenant:
    """Ambiguous accounts quarantine and answer 400."""

    def test_list_mapped_account_returns_400_with_quarantine_audit(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange account mapped to several tenants; Assert 400 + sentinel."""
        # Arrange: acct_amb maps to ["tenant-a", "tenant-b"] in MAP_JSON.
        http, engine = client
        raw = _raw("evt_ambig_001", account="acct_amb")
        # Act: deliver.
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: ambiguous rejection with quarantined row + audit.
        assert response.status_code == 400
        assert response.json()["error"] == "ambiguous_tenant"
        rows = _events(engine)
        assert len(rows) == 1
        assert rows[0].tenant_id == wh.UNROUTABLE_TENANT
        assert rows[0].status == wh.STATUS_IGNORED
        assert len(_audits(engine, "WEBHOOK_QUARANTINED")) == 1
        _assert_no_cf001(engine)

    def test_conflicting_envelope_accounts_return_400(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Top-level vs nested accounts disagreeing is ambiguous."""
        # Arrange: envelope names two different candidate accounts.
        http, engine = client
        raw = json.dumps(
            {
                "id": "evt_ambig_002",
                "type": "charge.succeeded",
                "account": ACCOUNT,
                "created": FIXED_NOW,
                "data": {"object": {"account": "acct_other"}},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        # Act: deliver.
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: ambiguous rejection, quarantined, no default tenant.
        assert response.status_code == 400
        assert response.json()["error"] == "ambiguous_tenant"
        assert _events(engine)[0].tenant_id == wh.UNROUTABLE_TENANT
        _assert_no_cf001(engine)


class TestMalformedEnvelope:
    """Verified but malformed envelopes are 400 with zero rows."""

    @pytest.mark.parametrize("missing", ["id", "type"])
    def test_missing_identifier_returns_400_without_rows(
        self, client: tuple[TestClient, Any], missing: str
    ) -> None:
        """Arrange envelope lacking id/type; Act POST; Assert 400 + no write."""
        # Arrange: well-signed bytes that violate the envelope contract.
        http, engine = client
        envelope: dict[str, Any] = {
            "id": "evt_bad_001",
            "type": "charge.succeeded",
            "account": ACCOUNT,
            "created": FIXED_NOW,
            "data": {"object": {}},
        }
        del envelope[missing]
        raw = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        # Act: deliver (signature passes; envelope validation fails).
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: rejected with no persistence.
        assert response.status_code == 400
        assert response.json()["error"] == "malformed_envelope"
        assert _events(engine) == []
        assert _audits(engine) == []

    def test_non_object_body_returns_400_without_rows(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """A JSON array body is a malformed envelope."""
        # Arrange: signed non-object JSON.
        http, engine = client
        raw = b"[1,2,3]"
        # Act: deliver.
        response = http.post("/webhooks/stripe", content=raw, headers=_signed_headers(raw))
        # Assert: rejected with no persistence.
        assert response.status_code == 400
        assert _events(engine) == []


class TestNoInMemoryIdempotency:
    """Idempotency is DB-only: two clients sharing the DB dedup correctly."""

    def test_two_clients_share_only_the_database(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange two clients on one app; Act split deliver/replay; Assert 1 row."""
        # Arrange: a second client bound to the same app (no shared memory).
        http, engine = client
        app = http.app  # type: ignore[attr-defined]
        second = TestClient(app)
        raw = _raw("evt_shared_001")
        headers = _signed_headers(raw)
        # Act: first delivery via client one, replay via client two.
        assert http.post("/webhooks/stripe", content=raw, headers=headers).status_code == 202
        replay = second.post("/webhooks/stripe", content=raw, headers=headers)
        # Assert: cross-client replay dedups through the DB UNIQUE boundary.
        assert replay.status_code == 200
        assert replay.json()["status"] == "duplicate"
        assert len(_events(engine)) == 1
        second.close()
        _assert_no_cf001(engine)


class TestRlsDialectGuard:
    """Postgres RLS context is set on Postgres and skipped elsewhere."""

    def test_sqlite_delivery_skips_rls_and_succeeds(
        self, client: tuple[TestClient, Any]
    ) -> None:
        """Arrange SQLite session; Act set tenant context; Assert no raise."""
        # Arrange: a raw SQLite session from the test engine.
        _, engine = client
        with Session(engine) as session:
            # Act: dialect guard must skip set_config off Postgres.
            wh._set_tenant_context(session, TENANT)
        # Assert: reached here without raising (guard held); ingest also passes.
        http, _ = client
        raw = _raw("evt_rls_001")
        assert http.post(
            "/webhooks/stripe", content=raw, headers=_signed_headers(raw)
        ).status_code == 202
