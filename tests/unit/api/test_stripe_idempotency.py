"""Unit tests: Stripe ingest dedup + idempotency-conflict (P2.2, in-memory).

Transport rule pinned here for the future DB-backed implementation:

* Same event delivered twice (same ``idempotency_key`` + same payload hash)
  persists one row and returns one identical result (deduped replay).
* Same key with a different payload hash is an ``IDEMPOTENCY_CONFLICT``:
  an audit entry is recorded and the stored row/result is never mutated.
* Distinct keys persist distinct rows.

The store below is in-memory so this file stays a fast unit suite; the
DB-backed uniqueness + restart-green proof lives in
``tests/integration/test_stripe_idempotency_restart.py``. No DB, no LLM,
no network. Money uses ``Decimal("...")`` only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest


class IdempotencyConflictError(ValueError):
    """Raised when a key is reused with a different payload hash."""

    def __init__(self, key: str, stored_hash: str, incoming_hash: str) -> None:
        """Record the conflicting key and both payload hashes."""
        self.key = key
        self.stored_hash = stored_hash
        self.incoming_hash = incoming_hash
        super().__init__(f"IDEMPOTENCY_CONFLICT for key {key}.")


def payload_hash(payload: dict[str, Any]) -> str:
    """Hash a canonical JSON rendering of the payload (sha256 hex)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class IngestRecord:
    """One persisted transport row: key, hash, tenant, and result."""

    idempotency_key: str
    payload_hash: str
    tenant_id: str
    result: dict[str, str]


@dataclass
class MemoryTransport:
    """In-memory transport with DB-like unique-key semantics."""

    rows: dict[str, IngestRecord] = field(default_factory=dict)
    audit: list[dict[str, str]] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        """Number of persisted transport rows."""
        return len(self.rows)

    def ingest(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        payload: dict[str, Any],
        compute: Callable[[], dict[str, str]],
    ) -> tuple[dict[str, str], bool]:
        """Persist-or-dedup one delivery.

        Args:
            idempotency_key: Transport dedup key (unique per event).
            tenant_id: Owning tenant scope (non-empty).
            payload: Raw delivery payload (hashed for conflict detection).
            compute: Builds the result only on first insert.

        Returns:
            ``(result, deduped)`` where ``deduped`` is True on replay.

        Raises:
            IdempotencyConflictError: Key reused with a different payload hash;
                an audit entry is appended and nothing is mutated.
            ValueError: Empty key or tenant.
        """
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string.")
        if not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string.")
        incoming = payload_hash(payload)
        existing = self.rows.get(idempotency_key)
        if existing is None:
            result = compute()
            self.rows[idempotency_key] = IngestRecord(
                idempotency_key=idempotency_key,
                payload_hash=incoming,
                tenant_id=tenant_id,
                result=result,
            )
            return result, False
        if existing.payload_hash != incoming:
            self.audit.append(
                {
                    "code": "IDEMPOTENCY_CONFLICT",
                    "idempotency_key": idempotency_key,
                    "stored_hash": existing.payload_hash,
                    "incoming_hash": incoming,
                    "tenant_id": existing.tenant_id,
                }
            )
            raise IdempotencyConflictError(idempotency_key, existing.payload_hash, incoming)
        return existing.result, True


def _charge_payload(*, amount: str = "50000.00") -> dict[str, Any]:
    """Build a deterministic charge payload with Decimal-string money."""
    assert Decimal(amount) >= Decimal("0")
    return {
        "payment_id": "pi-flagship-charge",
        "gross": amount,
        "fee": "0.00",
        "refund": "0.00",
        "currency": "USD",
    }


def _result_for(payload: dict[str, Any]) -> dict[str, str]:
    """Compute a deterministic stored result from Decimal money only."""
    gross = Decimal(payload["gross"])
    fee = Decimal(payload["fee"])
    refund = Decimal(payload["refund"])
    net = gross - fee - refund
    return {"gross": str(gross), "net": str(net), "outcome": "MATCHED"}


class TestDuplicateDeliveryDeduped:
    """The same event twice yields one row and one identical result."""

    def test_first_delivery_persists_one_row(self) -> None:
        """Arrange a fresh transport; Act ingest; Assert one row, not deduped."""
        transport = MemoryTransport()
        result, deduped = transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=_charge_payload(),
            compute=lambda: _result_for(_charge_payload()),
        )
        assert deduped is False
        assert transport.row_count == 1
        assert result["net"] == "50000.00"

    def test_same_event_twice_returns_same_result_without_new_row(self) -> None:
        """Replaying identical bytes is a deduped no-op."""
        transport = MemoryTransport()
        payload = _charge_payload()
        first, _ = transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=payload,
            compute=lambda: _result_for(payload),
        )
        calls = 0

        def _must_not_run() -> dict[str, str]:
            nonlocal calls
            calls += 1
            return {"gross": "0", "net": "0", "outcome": "RECOMPUTED"}

        second, deduped = transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=dict(payload),
            compute=_must_not_run,
        )
        assert deduped is True
        assert second == first
        assert transport.row_count == 1
        assert calls == 0

    def test_distinct_keys_persist_distinct_rows(self) -> None:
        """Charge and refund keys coexist as two rows."""
        transport = MemoryTransport()
        transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=_charge_payload(),
            compute=lambda: _result_for(_charge_payload()),
        )
        transport.ingest(
            idempotency_key="stripe-flagship-001-refund",
            tenant_id="tenant-acme",
            payload=_charge_payload(amount="35000.00"),
            compute=lambda: _result_for(_charge_payload(amount="35000.00")),
        )
        assert transport.row_count == 2


class TestSameKeyDifferentPayloadConflict:
    """Key reuse with different bytes is a conflict: audit, no mutation."""

    def test_conflict_raises_and_audits_without_mutation(self) -> None:
        """Arrange a stored row; Act conflicting ingest; Assert conflict + intact."""
        transport = MemoryTransport()
        original = _charge_payload()
        stored, _ = transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=original,
            compute=lambda: _result_for(original),
        )
        tampered = _charge_payload(amount="49999.00")
        with pytest.raises(IdempotencyConflictError, match="IDEMPOTENCY_CONFLICT"):
            transport.ingest(
                idempotency_key="stripe-flagship-001",
                tenant_id="tenant-acme",
                payload=tampered,
                compute=lambda: _result_for(tampered),
            )
        assert transport.row_count == 1
        assert transport.rows["stripe-flagship-001"].result == stored
        assert transport.rows["stripe-flagship-001"].payload_hash == payload_hash(original)
        assert len(transport.audit) == 1
        entry = transport.audit[0]
        assert entry["code"] == "IDEMPOTENCY_CONFLICT"
        assert entry["idempotency_key"] == "stripe-flagship-001"
        assert entry["stored_hash"] != entry["incoming_hash"]

    def test_conflict_audit_preserves_original_result_on_retry(self) -> None:
        """After a conflict, a faithful replay still returns the original."""
        transport = MemoryTransport()
        original = _charge_payload()
        stored, _ = transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=original,
            compute=lambda: _result_for(original),
        )
        with pytest.raises(IdempotencyConflictError):
            transport.ingest(
                idempotency_key="stripe-flagship-001",
                tenant_id="tenant-acme",
                payload=_charge_payload(amount="1.00"),
                compute=lambda: _result_for(_charge_payload(amount="1.00")),
            )
        replayed, deduped = transport.ingest(
            idempotency_key="stripe-flagship-001",
            tenant_id="tenant-acme",
            payload=dict(original),
            compute=lambda: {"gross": "0", "net": "0", "outcome": "RECOMPUTED"},
        )
        assert deduped is True
        assert replayed == stored
        assert transport.row_count == 1

    def test_empty_key_and_tenant_rejected(self) -> None:
        """Blank keys/tenants never reach the store."""
        transport = MemoryTransport()
        with pytest.raises(ValueError, match="idempotency_key"):
            transport.ingest(
                idempotency_key="  ",
                tenant_id="tenant-acme",
                payload=_charge_payload(),
                compute=lambda: _result_for(_charge_payload()),
            )
        with pytest.raises(ValueError, match="tenant_id"):
            transport.ingest(
                idempotency_key="stripe-flagship-001",
                tenant_id="",
                payload=_charge_payload(),
                compute=lambda: _result_for(_charge_payload()),
            )
        assert transport.row_count == 0
        assert transport.audit == []
