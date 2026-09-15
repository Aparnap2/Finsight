"""Money guards for the P1 pure reconciliation core (I1: Decimal-only money).

Every monetary field is ``Decimal``-only. ``float``/``bool`` are rejected
with :class:`FloatMoneyError`, non-finite ``Decimal`` (NaN/Infinity) is
rejected with :class:`InvariantViolation`, and the net invariant
``net == gross - fee - refund`` holds in exact ``Decimal`` arithmetic.

Style follows ``tests/unit/test_domain/test_money.py``: class-grouped
invariants, Arrange-Act-Assert, ``Decimal`` literals only on the happy
path (floats appear solely as rejection probes).
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.reconciliation.errors import (
    CurrencyMismatch,
    FloatMoneyError,
    InvariantViolation,
)
from finance.reconciliation.models import PaymentRecord, PaymentStatus
from finance.reconciliation.normalizer import normalize


def _record(
    *,
    gross: object = Decimal("100.00"),
    fee: object = Decimal("2.50"),
    refund: object = Decimal("0.00"),
    net: object = Decimal("97.50"),
    currency: str = "USD",
    payment_id: str = "pay-001",
    tenant_id: str = "tenant-acme",
    idempotency_key: str = "key-001",
) -> PaymentRecord:
    """Build a valid payment leg, overriding any field."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id="evt-001",
        idempotency_key=idempotency_key,
        gross=gross,  # type: ignore[arg-type]
        fee=fee,  # type: ignore[arg-type]
        refund=refund,  # type: ignore[arg-type]
        net=net,  # type: ignore[arg-type]
        currency=currency,
        status=PaymentStatus.SETTLED,
        occurred_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        tenant_id=tenant_id,
    )


class TestDecimalAccepted:
    """Decimal money is the only accepted happy-path representation."""

    def test_decimal_amounts_construct(self) -> None:
        """Arrange valid Decimals; Act construct; Assert fields preserved."""
        record = _record()
        assert isinstance(record.gross, Decimal)
        assert isinstance(record.fee, Decimal)
        assert isinstance(record.refund, Decimal)
        assert isinstance(record.net, Decimal)
        assert record.net == Decimal("97.50")

    def test_spec_example_normalizes_with_decimal_precision(self) -> None:
        """Spec scenario gross 100.00 / fee 2.50 / net 97.50 is preserved."""
        raw = {
            "payment_id": "pay-spec",
            "provider": "stripe",
            "provider_event_id": "evt-spec",
            "idempotency_key": "key-spec",
            "gross": Decimal("100.00"),
            "fee": Decimal("2.50"),
            "refund": Decimal("0.00"),
            "net": Decimal("97.50"),
            "currency": "USD",
            "status": "SETTLED",
            "occurred_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
            "tenant_id": "tenant-acme",
        }
        record = normalize(raw)
        assert record.gross == Decimal("100.00")
        assert record.fee == Decimal("2.50")
        assert record.net == Decimal("97.50")
        assert record.occurred_at.tzinfo is not None

    def test_normalizer_accepts_lossless_int_and_str(self) -> None:
        """Ints and numeric strings convert exactly via the normalizer."""
        raw = {
            "payment_id": "pay-int",
            "provider": "stripe",
            "provider_event_id": "evt-int",
            "idempotency_key": "key-int",
            "gross": 100,
            "fee": "2.50",
            "refund": 0,
            "currency": "USD",
            "status": "SETTLED",
            "occurred_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
            "tenant_id": "tenant-acme",
        }
        record = normalize(raw)
        assert record.gross == Decimal("100")
        assert record.fee == Decimal("2.50")
        assert record.net == Decimal("97.50")

    def test_zero_amounts_construct(self) -> None:
        """Zero gross/fee/refund/net is a valid leg (voided/placeholder)."""
        record = _record(
            gross=Decimal("0.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("0.00"),
        )
        assert record.net == Decimal("0.00")

    def test_negative_net_satisfying_invariant_constructs(self) -> None:
        """A negative net is valid when the equation holds (over-refund)."""
        record = _record(
            gross=Decimal("10.00"),
            fee=Decimal("2.00"),
            refund=Decimal("10.00"),
            net=Decimal("-2.00"),
        )
        assert record.net == Decimal("-2.00")
        assert record.net == record.gross - record.fee - record.refund


class TestFloatBoolRejected:
    """Float/bool money is rejected at every trust boundary."""

    def test_float_gross_rejected_with_float_money_error(self) -> None:
        """A float gross raises FloatMoneyError and creates no record."""
        with pytest.raises(FloatMoneyError):
            _record(
                gross=1.5,  # type: ignore[arg-type]
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("1.50"),
            )

    def test_float_fee_rejected(self) -> None:
        """A float fee raises FloatMoneyError."""
        with pytest.raises(FloatMoneyError):
            _record(fee=2.5)  # type: ignore[arg-type]

    def test_float_refund_rejected(self) -> None:
        """A float refund raises FloatMoneyError."""
        with pytest.raises(FloatMoneyError):
            _record(refund=0.5)  # type: ignore[arg-type]

    def test_float_net_rejected(self) -> None:
        """A float net raises FloatMoneyError."""
        with pytest.raises(FloatMoneyError, match="must be Decimal"):
            _record(net=97.5)  # type: ignore[arg-type]

    def test_float_nan_rejected(self) -> None:
        """A float NaN raises FloatMoneyError (never reaches NaN check)."""
        with pytest.raises(FloatMoneyError):
            _record(
                gross=float("nan"),  # type: ignore[arg-type]
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("0.00"),
            )

    def test_bool_money_rejected(self) -> None:
        """Bools are ints in disguise and MUST be rejected as money."""
        with pytest.raises(FloatMoneyError):
            _record(
                gross=True,  # type: ignore[arg-type]
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("1.00"),
            )

    def test_normalizer_rejects_float_and_bool(self) -> None:
        """The normalizer boundary rejects float/bool before construction."""
        base = {
            "payment_id": "pay-f",
            "provider": "stripe",
            "provider_event_id": "evt-f",
            "idempotency_key": "key-f",
            "currency": "USD",
            "status": "SETTLED",
            "occurred_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
            "tenant_id": "tenant-acme",
        }
        with pytest.raises(FloatMoneyError):
            normalize({**base, "gross": 100.0, "fee": Decimal("0")})
        with pytest.raises(FloatMoneyError):
            normalize({**base, "gross": Decimal("10"), "fee": True})

    def test_float_money_error_is_type_error(self) -> None:
        """FloatMoneyError is also catchable as TypeError."""
        with pytest.raises(TypeError):
            _record(net=1.0)  # type: ignore[arg-type]


class TestNonFiniteDecimalRejected:
    """NaN/Infinity Decimals are rejected as non-finite."""

    def test_nan_gross_rejected(self) -> None:
        """Decimal NaN gross raises InvariantViolation."""
        with pytest.raises(InvariantViolation, match="finite"):
            _record(
                gross=Decimal("NaN"),
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("0.00"),
            )

    def test_infinity_net_rejected(self) -> None:
        """Decimal Infinity net raises InvariantViolation."""
        with pytest.raises(InvariantViolation, match="finite"):
            _record(net=Decimal("Infinity"))

    def test_negative_infinity_rejected(self) -> None:
        """Decimal -Infinity fee raises InvariantViolation."""
        with pytest.raises(InvariantViolation):
            _record(fee=Decimal("-Infinity"))

    def test_normalizer_rejects_nan_string(self) -> None:
        """The string 'NaN' parses to non-finite and is rejected."""
        with pytest.raises(InvariantViolation, match="finite"):
            normalize(
                {
                    "payment_id": "pay-nan",
                    "provider": "stripe",
                    "provider_event_id": "evt-nan",
                    "idempotency_key": "key-nan",
                    "gross": "NaN",
                    "currency": "USD",
                    "status": "SETTLED",
                    "occurred_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                    "tenant_id": "tenant-acme",
                }
            )


class TestNetInvariant:
    """net == gross - fee - refund in exact Decimal arithmetic."""

    def test_net_equation_holds(self) -> None:
        """A consistent leg preserves the equation exactly."""
        record = _record(
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("15000.00"),
            net=Decimal("35000.00"),
        )
        assert record.net == record.gross - record.fee - record.refund

    def test_off_by_one_cent_rejected(self) -> None:
        """A one-cent drift violates the invariant and is rejected."""
        with pytest.raises(InvariantViolation, match="net invariant violated"):
            _record(
                gross=Decimal("100.00"),
                fee=Decimal("2.50"),
                refund=Decimal("0.00"),
                net=Decimal("97.51"),
            )

    def test_normalizer_derives_net_when_absent(self) -> None:
        """Absent net is derived deterministically as gross-fee-refund."""
        record = normalize(
            {
                "payment_id": "pay-derive",
                "provider": "stripe",
                "provider_event_id": "evt-derive",
                "idempotency_key": "key-derive",
                "gross": Decimal("100.00"),
                "fee": Decimal("2.50"),
                "refund": Decimal("5.00"),
                "currency": "USD",
                "status": "SETTLED",
                "occurred_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                "tenant_id": "tenant-acme",
            }
        )
        assert record.net == Decimal("92.50")

    def test_normalizer_explicit_bad_net_rejected(self) -> None:
        """An explicit net that breaks the equation is rejected."""
        with pytest.raises(InvariantViolation, match="net invariant violated"):
            normalize(
                {
                    "payment_id": "pay-bad",
                    "provider": "stripe",
                    "provider_event_id": "evt-bad",
                    "idempotency_key": "key-bad",
                    "gross": Decimal("100.00"),
                    "fee": Decimal("2.50"),
                    "refund": Decimal("0.00"),
                    "net": Decimal("0.00"),
                    "currency": "USD",
                    "status": "SETTLED",
                    "occurred_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                    "tenant_id": "tenant-acme",
                }
            )


class TestCurrencyAndIdentityGuards:
    """Currency mismatch and identity rules guard every comparison."""

    def test_cross_currency_reconcile_raises(self) -> None:
        """Reconciling USD against EUR raises CurrencyMismatch."""
        from finance.reconciliation.reconciler import reconcile
        from finance.reconciliation.tolerances import ReconciliationTolerance

        usd = _record(currency="USD")
        eur = _record(currency="EUR", payment_id="pay-eur")
        with pytest.raises(CurrencyMismatch, match="currencies do not match"):
            reconcile(usd, eur, ReconciliationTolerance())

    def test_cross_currency_classify_raises(self) -> None:
        """Classifying across currencies raises CurrencyMismatch."""
        from finance.reconciliation.classifier import classify

        usd = _record(currency="USD")
        eur = _record(currency="EUR", payment_id="pay-eur")
        with pytest.raises(CurrencyMismatch):
            classify(usd, eur)

    def test_empty_idempotency_key_rejected(self) -> None:
        """An empty idempotency_key violates the non-empty-string rule."""
        with pytest.raises(InvariantViolation, match="idempotency_key"):
            _record(idempotency_key="   ")

    def test_empty_tenant_rejected(self) -> None:
        """An empty tenant_id is rejected at the validation boundary."""
        with pytest.raises(InvariantViolation, match="tenant_id"):
            _record(tenant_id="")

    def test_lowercase_currency_rejected_by_model(self) -> None:
        """The model requires canonical uppercase ISO 4217 (use normalizer)."""
        with pytest.raises(InvariantViolation, match="ISO 4217"):
            _record(currency="usd")

    def test_naive_datetime_rejected(self) -> None:
        """A tz-naive occurred_at is rejected (tz-aware required)."""
        with pytest.raises(InvariantViolation, match="tz-aware"):
            PaymentRecord(
                payment_id="pay-naive",
                provider="stripe",
                provider_event_id="evt-naive",
                idempotency_key="key-naive",
                gross=Decimal("10.00"),
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("10.00"),
                currency="USD",
                status=PaymentStatus.SETTLED,
                occurred_at=datetime(2026, 5, 1, 12, 0, 0),
                tenant_id="tenant-acme",
            )

    def test_unknown_status_rejected(self) -> None:
        """An unknown status string is rejected."""
        with pytest.raises(InvariantViolation, match="Unknown payment status"):
            PaymentRecord(
                payment_id="pay-st",
                provider="stripe",
                provider_event_id="evt-st",
                idempotency_key="key-st",
                gross=Decimal("10.00"),
                fee=Decimal("0.00"),
                refund=Decimal("0.00"),
                net=Decimal("10.00"),
                currency="USD",
                status="BOGUS",  # type: ignore[arg-type]
                occurred_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                tenant_id="tenant-acme",
            )
