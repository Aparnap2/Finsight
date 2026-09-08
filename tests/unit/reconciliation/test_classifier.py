"""Break classification into the 3 versioned P0 exception types.

Covers the closed 3-code vocabulary, the flagship refund-lag shape,
fee-only drift, duplicate re-ingest, largest-component resolution for
mixed breaks (refund > fee > gross tie-break), cross-currency misuse,
and the no-break guard.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.reconciliation.classifier import classify
from finance.reconciliation.errors import CurrencyMismatch, InvariantViolation
from finance.reconciliation.models import ExceptionCode, PaymentRecord, PaymentStatus

_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _leg(
    *,
    payment_id: str,
    gross: Decimal,
    fee: Decimal,
    refund: Decimal,
    net: Decimal,
    currency: str = "USD",
    key: str = "key-cls",
    tenant_id: str = "tenant-acme",
) -> PaymentRecord:
    """Build one deterministic leg with Decimal-only money."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key=key,
        gross=gross,
        fee=fee,
        refund=refund,
        net=net,
        currency=currency,
        status=PaymentStatus.SETTLED,
        occurred_at=_AT,
        tenant_id=tenant_id,
    )


class TestThreeTypesOnly:
    """The P1 vocabulary is closed at exactly three I-codes."""

    def test_vocabulary_is_closed(self) -> None:
        """Exactly the three frozen codes exist, all I-prefixed."""
        assert set(ExceptionCode) == {
            ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
            ExceptionCode.FEE_MISMATCH,
            ExceptionCode.DUPLICATE_LEDGER_ENTRY,
        }
        assert ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value == "I-REFUND-LAG"
        assert ExceptionCode.FEE_MISMATCH.value == "I-FEE-DRIFT"
        assert ExceptionCode.DUPLICATE_LEDGER_ENTRY.value == "I-DUPLICATE"

    def test_refund_only_is_accounting_lag(self) -> None:
        """Gross agrees, refund lags -> PARTIAL_REFUND_ACCOUNTING_LAG."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("15000.00"),
            net=Decimal("35000.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("50000.00"),
        )
        assert classify(expected, observed) is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG

    def test_fee_only_is_fee_mismatch(self) -> None:
        """Gross and refund agree, fee drifts -> FEE_MISMATCH."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("2.50"),
            refund=Decimal("0.00"),
            net=Decimal("97.50"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("100.00"),
            fee=Decimal("3.00"),
            refund=Decimal("0.00"),
            net=Decimal("97.00"),
        )
        assert classify(expected, observed) is ExceptionCode.FEE_MISMATCH

    def test_duplicate_flag_wins(self) -> None:
        """The dedup flag forces DUPLICATE_LEDGER_ENTRY regardless of shape."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("15000.00"),
            net=Decimal("35000.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("50000.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("50000.00"),
        )
        assert (
            classify(expected, observed, duplicate=True)
            is ExceptionCode.DUPLICATE_LEDGER_ENTRY
        )


class TestMixedBreakLargestComponent:
    """Mixed breaks resolve to the largest absolute contributing component."""

    def test_refund_dominates_fee(self) -> None:
        """|refund 10| > |fee 1| resolves to accounting lag."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("2.00"),
            refund=Decimal("0.00"),
            net=Decimal("98.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("100.00"),
            fee=Decimal("3.00"),
            refund=Decimal("10.00"),
            net=Decimal("87.00"),
        )
        assert classify(expected, observed) is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG

    def test_fee_dominates_refund(self) -> None:
        """|fee 10| > |refund 1| resolves to fee mismatch."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("2.00"),
            refund=Decimal("0.00"),
            net=Decimal("98.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("100.00"),
            fee=Decimal("12.00"),
            refund=Decimal("1.00"),
            net=Decimal("87.00"),
        )
        assert classify(expected, observed) is ExceptionCode.FEE_MISMATCH

    def test_tie_breaks_to_refund_then_fee(self) -> None:
        """Equal refund/fee magnitudes prefer refund lag (documented order)."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("2.00"),
            refund=Decimal("0.00"),
            net=Decimal("98.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("100.00"),
            fee=Decimal("4.00"),
            refund=Decimal("2.00"),
            net=Decimal("94.00"),
        )
        assert classify(expected, observed) is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG

    def test_gross_only_maps_to_accounting_lag(self) -> None:
        """A gross-only drift still yields the refund-lag fallback code."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("100.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("110.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("110.00"),
        )
        assert classify(expected, observed) is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG


class TestClassifierGuards:
    """Misuse is rejected loudly, never silently misclassified."""

    def test_cross_currency_raises(self) -> None:
        """Classifying USD vs EUR raises CurrencyMismatch."""
        usd = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("100.00"),
            currency="USD",
        )
        eur = _leg(
            payment_id="ledger",
            gross=Decimal("100.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("100.00"),
            currency="EUR",
        )
        with pytest.raises(CurrencyMismatch, match="currencies do not match"):
            classify(usd, eur)

    def test_identical_legs_raise_no_break(self) -> None:
        """Legs with no component difference cannot be classified."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("2.00"),
            refund=Decimal("0.00"),
            net=Decimal("98.00"),
        )
        twin = _leg(
            payment_id="ledger",
            gross=Decimal("100.00"),
            fee=Decimal("2.00"),
            refund=Decimal("0.00"),
            net=Decimal("98.00"),
        )
        with pytest.raises(InvariantViolation, match="component difference"):
            classify(expected, twin)

    def test_non_bool_duplicate_rejected(self) -> None:
        """A non-bool duplicate flag is rejected."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("100.00"),
        )
        observed = _leg(
            payment_id="ledger",
            gross=Decimal("110.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("110.00"),
        )
        with pytest.raises(InvariantViolation, match="duplicate must be a bool"):
            classify(expected, observed, duplicate="yes")  # type: ignore[arg-type]

    def test_non_record_rejected(self) -> None:
        """Non-record inputs are rejected."""
        expected = _leg(
            payment_id="proc",
            gross=Decimal("100.00"),
            fee=Decimal("0.00"),
            refund=Decimal("0.00"),
            net=Decimal("100.00"),
        )
        with pytest.raises(InvariantViolation):
            classify(expected, "not-a-record")  # type: ignore[arg-type]
