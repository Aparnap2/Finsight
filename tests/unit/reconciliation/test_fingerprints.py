"""Stable sha256 fingerprints over canonical payment representations.

Identical normalized legs always hash identically (determinism / replay
stability); any content change (amount, tenant, currency, identity)
changes the digest (sensitivity); record construction order does not
matter while pair direction does (processor intent vs ledger observation
are directional).
"""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.fingerprints import (
    canonical_payment,
    fingerprint_pair,
    fingerprint_payment,
)
from finance.reconciliation.models import PaymentRecord, PaymentStatus

_HEX64 = re.compile(r"[0-9a-f]{64}")
_TENANT = "tenant-acme"
_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _leg(
    *,
    payment_id: str = "pay-001",
    gross: Decimal = Decimal("50000.00"),
    fee: Decimal = Decimal("0.00"),
    refund: Decimal = Decimal("15000.00"),
    net: Decimal = Decimal("35000.00"),
    tenant_id: str = _TENANT,
    currency: str = "USD",
    key: str = "key-001",
    occurred_at: datetime = _AT,
) -> PaymentRecord:
    """Build one deterministic leg with Decimal-only money."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id="evt-001",
        idempotency_key=key,
        gross=gross,
        fee=fee,
        refund=refund,
        net=net,
        currency=currency,
        status=PaymentStatus.SETTLED,
        occurred_at=occurred_at,
        tenant_id=tenant_id,
    )


class TestDeterminism:
    """Same content always yields the same digest."""

    def test_same_record_same_fingerprint(self) -> None:
        """Two equal legs hash identically."""
        first = _leg()
        second = _leg()
        assert fingerprint_payment(first) == fingerprint_payment(second)

    def test_pair_replay_stable(self) -> None:
        """Re-fingerprinting the same pair replays the same digest."""
        expected = _leg(payment_id="proc-001")
        observed = _leg(payment_id="ledger-001", key="key-002")
        first = fingerprint_pair(expected, observed)
        second = fingerprint_pair(expected, observed)
        assert first == second
        assert _HEX64.fullmatch(first) is not None

    def test_canonical_form_stable(self) -> None:
        """Canonical rendering is stable across calls."""
        record = _leg()
        assert canonical_payment(record) == canonical_payment(record)

    def test_construction_order_independent(self) -> None:
        """Kwarg order does not affect the digest (field order is fixed)."""
        kwargs_a = {
            "payment_id": "pay-001",
            "provider": "stripe",
            "provider_event_id": "evt-001",
            "idempotency_key": "key-001",
            "gross": Decimal("50000.00"),
            "fee": Decimal("0.00"),
            "refund": Decimal("15000.00"),
            "net": Decimal("35000.00"),
            "currency": "USD",
            "status": PaymentStatus.SETTLED,
            "occurred_at": _AT,
            "tenant_id": _TENANT,
        }
        kwargs_b = {
            "tenant_id": _TENANT,
            "occurred_at": _AT,
            "status": PaymentStatus.SETTLED,
            "currency": "USD",
            "net": Decimal("35000.00"),
            "refund": Decimal("15000.00"),
            "fee": Decimal("0.00"),
            "gross": Decimal("50000.00"),
            "idempotency_key": "key-001",
            "provider_event_id": "evt-001",
            "provider": "stripe",
            "payment_id": "pay-001",
        }
        first = PaymentRecord(**kwargs_a)  # type: ignore[arg-type]
        second = PaymentRecord(**kwargs_b)  # type: ignore[arg-type]
        assert fingerprint_payment(first) == fingerprint_payment(second)


class TestSensitivity:
    """Any content change changes the digest."""

    def test_amount_sensitivity(self) -> None:
        """A one-cent net change changes the fingerprint."""
        base = _leg()
        drifted = _leg(
            gross=Decimal("50000.01"),
            net=Decimal("35000.01"),
            payment_id="pay-002",
            key="key-002",
        )
        assert fingerprint_payment(base) != fingerprint_payment(drifted)

    def test_fee_sensitivity(self) -> None:
        """A fee-only change changes the fingerprint."""
        base = _leg(
            gross=Decimal("100.00"),
            fee=Decimal("2.50"),
            refund=Decimal("0.00"),
            net=Decimal("97.50"),
        )
        drifted = _leg(
            gross=Decimal("100.00"),
            fee=Decimal("2.51"),
            refund=Decimal("0.00"),
            net=Decimal("97.49"),
        )
        assert fingerprint_payment(base) != fingerprint_payment(drifted)

    def test_tenant_sensitivity(self) -> None:
        """The same amounts under another tenant hash differently."""
        base = _leg(tenant_id="tenant-acme")
        other = _leg(tenant_id="tenant-globex")
        assert fingerprint_payment(base) != fingerprint_payment(other)

    def test_currency_sensitivity(self) -> None:
        """USD vs EUR legs hash differently."""
        usd = _leg(currency="USD")
        eur = _leg(currency="EUR")
        assert fingerprint_payment(usd) != fingerprint_payment(eur)

    def test_identity_sensitivity(self) -> None:
        """A different payment_id changes the fingerprint."""
        first = _leg(payment_id="pay-001")
        second = _leg(payment_id="pay-002")
        assert fingerprint_payment(first) != fingerprint_payment(second)

    def test_timestamp_sensitivity(self) -> None:
        """A different instant changes the fingerprint."""
        first = _leg(occurred_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
        second = _leg(occurred_at=datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC))
        assert fingerprint_payment(first) != fingerprint_payment(second)

    def test_pair_amount_sensitivity(self) -> None:
        """Changing either pair leg changes the pair digest."""
        expected = _leg(payment_id="proc-001")
        observed = _leg(payment_id="ledger-001", key="key-002")
        drifted = _leg(
            payment_id="ledger-001",
            key="key-002",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("50000.00"),
        )
        assert fingerprint_pair(expected, observed) != fingerprint_pair(
            expected, drifted
        )


class TestPairDirection:
    """Pair order is significant: expected/observed are directional."""

    def test_pair_order_sensitive(self) -> None:
        """fingerprint_pair(a, b) differs from fingerprint_pair(b, a)."""
        first = _leg(payment_id="proc-001")
        second = _leg(payment_id="ledger-001", key="key-002")
        assert fingerprint_pair(first, second) != fingerprint_pair(second, first)

    def test_pair_self_consistent(self) -> None:
        """Pairing a leg with itself is stable and well-formed."""
        record = _leg()
        digest = fingerprint_pair(record, record)
        assert digest == fingerprint_pair(record, record)
        assert _HEX64.fullmatch(digest) is not None


class TestDigestShape:
    """Digests are lowercase sha256 hex."""

    def test_payment_digest_is_hex64(self) -> None:
        """Single-leg digests are 64 lowercase hex chars."""
        digest = fingerprint_payment(_leg())
        assert len(digest) == 64
        assert _HEX64.fullmatch(digest) is not None
        assert digest == digest.lower()

    def test_non_record_rejected(self) -> None:
        """Fingerprinting a non-record raises InvariantViolation."""
        with pytest.raises(InvariantViolation):
            fingerprint_payment("not-a-record")  # type: ignore[arg-type]
        with pytest.raises(InvariantViolation):
            canonical_payment(None)  # type: ignore[arg-type]
