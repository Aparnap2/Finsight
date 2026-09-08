"""Stripe adapter edge tests: fee tri-state, refund fold, and money guards.

Covers ``finance/stripe/adapter.py`` without touching the adapter itself:
charge-only fee knowledge (KNOWN / explicit-zero KNOWN / missing UNKNOWN),
partial and full refund net derivation, malformed envelopes, duplicate vs
conflicting refund replay, cross-tenant isolation, over-gross and currency
guards, float/bool money rejection, refund-leg NOT_APPLICABLE fee, and
out-of-order refund convergence.

Style: Arrange-Act-Assert per test, ``Decimal("...")`` literals only on the
happy path (floats/bools appear solely as rejection probes).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from finance.reconciliation.errors import (
    CurrencyMismatch,
    FloatMoneyError,
    InvariantViolation,
)
from finance.reconciliation.models import PaymentStatus
from finance.stripe.adapter import (
    FeeState,
    apply_refund_event,
    fee_knowledge_of,
    payment_from_charge,
    stripe_to_normalized,
    stripe_to_record,
)

TENANT_A = "tenant-acme"
TENANT_B = "tenant-globex"
CHARGE_CREATED = 1750000000
REFUND_CREATED = 1750000100


def _charge_event(
    *,
    event_id: str = "evt_charge_1",
    charge_id: str = "ch_1",
    amount_minor: int = 10000,
    currency: str = "usd",
    fee_minor: int | None = 250,
    created: int = CHARGE_CREATED,
) -> dict[str, Any]:
    """Build a charge.succeeded envelope; fee_minor None omits the fee key."""
    obj: dict[str, Any] = {
        "id": charge_id,
        "amount": amount_minor,
        "currency": currency,
        "created": created,
    }
    if fee_minor is not None:
        obj["application_fee_amount"] = fee_minor
    return {
        "id": event_id,
        "type": "charge.succeeded",
        "created": created,
        "data": {"object": obj},
    }


def _refund_event(
    *,
    event_id: str = "evt_refund_1",
    refund_id: str = "re_1",
    charge_id: str = "ch_1",
    amount_minor: int = 2500,
    charge_amount_minor: int = 10000,
    currency: str = "usd",
    created: int = REFUND_CREATED,
) -> dict[str, Any]:
    """Build a refund.created envelope linked to a bare charge id."""
    obj: dict[str, Any] = {
        "id": refund_id,
        "amount": amount_minor,
        "currency": currency,
        "charge": charge_id,
        "charge_amount_minor": charge_amount_minor,
        "created": created,
    }
    return {
        "id": event_id,
        "type": "refund.created",
        "created": created,
        "data": {"object": obj},
    }


class TestChargeFeeTriState:
    """Charge-only legs report KNOWN, explicit-zero KNOWN, or UNKNOWN fee."""

    def test_charge_with_known_fee_emits_known_and_net(self) -> None:
        """Arrange KNOWN fee; Act normalize; Assert fee, net, and status."""
        # Arrange.
        event = _charge_event(fee_minor=250)
        # Act.
        normalized = stripe_to_normalized(event, tenant_id=TENANT_A)
        # Assert.
        assert normalized.fee.state is FeeState.KNOWN
        assert normalized.fee.amount == Decimal("2.50")
        assert normalized.record.fee == Decimal("2.50")
        assert normalized.record.gross == Decimal("100.00")
        assert normalized.record.net == Decimal("97.50")
        assert normalized.record.status is PaymentStatus.CAPTURED
        assert normalized.refund is None

    def test_charge_with_explicit_zero_fee_is_known_zero(self) -> None:
        """Arrange fee key 0; Act normalize; Assert KNOWN with amount 0."""
        # Arrange.
        event = _charge_event(fee_minor=0)
        # Act.
        normalized = stripe_to_normalized(event, tenant_id=TENANT_A)
        knowledge = fee_knowledge_of(event)
        # Assert.
        assert normalized.fee.state is FeeState.KNOWN
        assert normalized.fee.amount == Decimal("0")
        assert knowledge.state is FeeState.KNOWN
        assert knowledge.amount == Decimal("0")
        assert normalized.record.fee == Decimal("0")
        assert normalized.record.net == Decimal("100.00")

    def test_charge_with_missing_fee_is_unknown_with_zero_placeholder(self) -> None:
        """Arrange absent fee; Act normalize; Assert UNKNOWN, placeholder 0."""
        # Arrange.
        event = _charge_event(fee_minor=None)
        # Act.
        normalized = stripe_to_normalized(event, tenant_id=TENANT_A)
        knowledge = fee_knowledge_of(event)
        # Assert.
        assert normalized.fee.state is FeeState.UNKNOWN
        assert normalized.fee.amount is None
        assert knowledge.state is FeeState.UNKNOWN
        assert knowledge.amount is None
        assert normalized.record.fee == Decimal("0")
        assert normalized.record.net == Decimal("100.00")

    def test_explicit_zero_fee_distinct_from_unknown_fee(self) -> None:
        """Both records carry Decimal 0 yet fee states differ (no coercion)."""
        # Arrange.
        zero_event = _charge_event(event_id="evt_zero", fee_minor=0)
        missing_event = _charge_event(event_id="evt_missing", fee_minor=None)
        # Act.
        zero_fee = fee_knowledge_of(zero_event)
        missing_fee = fee_knowledge_of(missing_event)
        zero_record = stripe_to_record(zero_event, tenant_id=TENANT_A)
        missing_record = stripe_to_record(missing_event, tenant_id=TENANT_A)
        # Assert.
        assert zero_fee.state is FeeState.KNOWN
        assert missing_fee.state is FeeState.UNKNOWN
        assert zero_fee != missing_fee
        assert zero_record.fee == Decimal("0")
        assert missing_record.fee == Decimal("0")


class TestRefundFold:
    """Refund deltas fold into the canonical net with lifecycle status."""

    def test_partial_refund_derives_net_and_status(self) -> None:
        """Arrange charge + 25.00 refund; Act fold; Assert net 72.50 partial."""
        # Arrange.
        payment = payment_from_charge(_charge_event(), tenant_id=TENANT_A)
        # Act.
        folded = apply_refund_event(payment, _refund_event(amount_minor=2500))
        record = folded.to_record()
        # Assert.
        assert folded.total_refunded() == Decimal("25.00")
        assert folded.net_amount() == Decimal("72.50")
        assert folded.derived_status() is PaymentStatus.PARTIALLY_REFUNDED
        assert record.net == Decimal("72.50")
        assert record.status is PaymentStatus.PARTIALLY_REFUNDED

    def test_full_refund_marks_refunded_with_zero_net(self) -> None:
        """Arrange zero-fee charge + full refund; Act fold; Assert REFUNDED."""
        # Arrange.
        payment = payment_from_charge(_charge_event(fee_minor=0), tenant_id=TENANT_A)
        # Act.
        folded = apply_refund_event(payment, _refund_event(amount_minor=10000))
        record = folded.to_record()
        # Assert.
        assert folded.total_refunded() == Decimal("100.00")
        assert folded.net_amount() == Decimal("0.00")
        assert folded.derived_status() is PaymentStatus.REFUNDED
        assert record.status is PaymentStatus.REFUNDED

    def test_refund_leg_carries_not_applicable_fee(self) -> None:
        """Arrange refund leg; Act normalize; Assert NOT_APPLICABLE fee."""
        # Arrange.
        event = _refund_event()
        # Act.
        normalized = stripe_to_normalized(event, tenant_id=TENANT_A)
        knowledge = fee_knowledge_of(event)
        # Assert.
        assert normalized.fee.state is FeeState.NOT_APPLICABLE
        assert normalized.fee.amount is None
        assert knowledge.state is FeeState.NOT_APPLICABLE
        assert normalized.refund is not None
        assert normalized.refund.identity == ("stripe", "re_1")


class TestMalformedEnvelope:
    """Missing envelope parts and unsupported types are malformed."""

    def test_missing_event_id_rejected(self) -> None:
        """Arrange envelope without id; Act normalize; Assert rejected."""
        # Arrange.
        event = _charge_event()
        del event["id"]
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="Field 'id'"):
            stripe_to_record(event, tenant_id=TENANT_A)

    def test_missing_event_type_rejected(self) -> None:
        """Arrange envelope without type; Act normalize; Assert rejected."""
        # Arrange.
        event = _charge_event()
        del event["type"]
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="Field 'type'"):
            stripe_to_record(event, tenant_id=TENANT_A)

    def test_missing_data_object_rejected(self) -> None:
        """Arrange envelope without data.object; Act; Assert rejected."""
        # Arrange.
        event: dict[str, Any] = {
            "id": "evt_broken",
            "type": "charge.succeeded",
            "created": CHARGE_CREATED,
            "data": {},
        }
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="data.object"):
            stripe_to_record(event, tenant_id=TENANT_A)

    def test_unsupported_event_type_rejected(self) -> None:
        """Arrange allow-list miss; Act normalize; Assert rejected."""
        # Arrange.
        event = _charge_event()
        event["type"] = "charge.failed"
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="Unsupported Stripe"):
            stripe_to_record(event, tenant_id=TENANT_A)


class TestReplayAndIsolation:
    """Replay is idempotent; conflicts, tenants, and order converge."""

    def test_duplicate_refund_replay_leaves_net_unchanged(self) -> None:
        """Arrange one refund; Act apply twice; Assert same net, no double."""
        # Arrange.
        payment = payment_from_charge(_charge_event(), tenant_id=TENANT_A)
        event = _refund_event()
        # Act.
        once = apply_refund_event(payment, event)
        twice = apply_refund_event(once, event)
        # Assert.
        assert twice.total_refunded() == Decimal("25.00")
        assert twice.net_amount() == once.net_amount()
        assert twice.to_record().net == Decimal("72.50")

    def test_conflicting_refund_replay_rejected(self) -> None:
        """Arrange same id, new amount; Act replay; Assert rejected."""
        # Arrange.
        payment = payment_from_charge(_charge_event(), tenant_id=TENANT_A)
        folded = apply_refund_event(payment, _refund_event(amount_minor=2500))
        conflict = _refund_event(event_id="evt_refund_2", refund_id="re_1", amount_minor=3000)
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="Conflicting replay"):
            apply_refund_event(folded, conflict)

    def test_same_payment_id_across_tenants_is_isolated(self) -> None:
        """Arrange shared charge id; Act scope per tenant; Assert isolation."""
        # Arrange.
        event = _charge_event()
        # Act.
        payment_a = payment_from_charge(event, tenant_id=TENANT_A)
        payment_b = payment_from_charge(event, tenant_id=TENANT_B)
        refund_a = stripe_to_normalized(_refund_event(), tenant_id=TENANT_A)
        # Assert.
        assert payment_a.canonical_key() != payment_b.canonical_key()
        assert refund_a.refund is not None
        with pytest.raises(InvariantViolation, match="tenant"):
            payment_b.apply_refund(refund_a.refund)

    def test_out_of_order_refunds_converge(self) -> None:
        """Arrange two refunds; Act fold in both orders; Assert same fold."""
        # Arrange.
        refund_a = _refund_event(
            event_id="evt_refund_a",
            refund_id="re_a",
            amount_minor=2500,
            created=REFUND_CREATED,
        )
        refund_b = _refund_event(
            event_id="evt_refund_b",
            refund_id="re_b",
            amount_minor=4000,
            created=REFUND_CREATED + 60,
        )
        # Act.
        first_ab = apply_refund_event(
            payment_from_charge(_charge_event(fee_minor=0), tenant_id=TENANT_A),
            refund_a,
        )
        order_ab = apply_refund_event(first_ab, refund_b)
        first_ba = apply_refund_event(
            payment_from_charge(_charge_event(fee_minor=0), tenant_id=TENANT_A),
            refund_b,
        )
        order_ba = apply_refund_event(first_ba, refund_a)
        # Assert.
        assert order_ab.total_refunded() == Decimal("65.00")
        assert order_ba.total_refunded() == Decimal("65.00")
        assert order_ab.net_amount() == order_ba.net_amount() == Decimal("35.00")
        assert order_ab.canonical_idempotency_key() == (order_ba.canonical_idempotency_key())
        assert order_ab.to_record().net == order_ba.to_record().net


class TestRefundGuards:
    """Over-gross deltas and cross-currency merges are rejected."""

    def test_single_refund_above_gross_rejected(self) -> None:
        """Arrange delta > gross; Act normalize; Assert rejected."""
        # Arrange.
        event = _refund_event(amount_minor=10001, charge_amount_minor=10000)
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="exceeds charge gross"):
            stripe_to_normalized(event, tenant_id=TENANT_A)

    def test_cumulative_refunds_above_gross_rejected(self) -> None:
        """Arrange two deltas summing past gross; Act fold; Assert rejected."""
        # Arrange.
        payment = payment_from_charge(_charge_event(fee_minor=0), tenant_id=TENANT_A)
        folded = apply_refund_event(payment, _refund_event(amount_minor=6000))
        overflow = _refund_event(event_id="evt_refund_2", refund_id="re_2", amount_minor=5000)
        # Act / Assert.
        with pytest.raises(InvariantViolation, match="Cumulative refunds"):
            apply_refund_event(folded, overflow)

    def test_refund_currency_mismatch_rejected(self) -> None:
        """Arrange USD charge + EUR refund; Act fold; Assert mismatch."""
        # Arrange.
        payment = payment_from_charge(_charge_event(), tenant_id=TENANT_A)
        eur_refund = _refund_event(event_id="evt_refund_eur", refund_id="re_eur", currency="eur")
        # Act / Assert.
        with pytest.raises(CurrencyMismatch, match="currencies do not match"):
            apply_refund_event(payment, eur_refund)


class TestMoneyGuards:
    """Float/bool money never enters the adapter; Decimal-only boundary."""

    def test_float_amount_rejected(self) -> None:
        """Arrange float charge amount; Act normalize; Assert rejected."""
        # Arrange.
        event = _charge_event()
        event["data"]["object"]["amount"] = 100.0
        # Act / Assert.
        with pytest.raises(FloatMoneyError):
            stripe_to_record(event, tenant_id=TENANT_A)

    def test_bool_fee_rejected(self) -> None:
        """Arrange bool fee probe; Act normalize; Assert rejected."""
        # Arrange.
        event = _charge_event()
        event["data"]["object"]["application_fee_amount"] = True
        # Act / Assert.
        with pytest.raises(FloatMoneyError):
            stripe_to_record(event, tenant_id=TENANT_A)

    def test_float_refund_delta_rejected(self) -> None:
        """Arrange float refund delta; Act normalize; Assert rejected."""
        # Arrange.
        event = _refund_event()
        event["data"]["object"]["amount"] = 25.5
        # Act / Assert.
        with pytest.raises(FloatMoneyError):
            stripe_to_normalized(event, tenant_id=TENANT_A)
