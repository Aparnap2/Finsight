"""Tenant-injected tolerances: absolute, percent, zero-default, boundaries.

Tolerances are never hardcoded: the caller injects a
``ReconciliationTolerance`` per tenant at call time. The zero-default
means exact matching; ``absolute`` is a money slack and ``percent`` is a
fraction of the leg net. Boundary differences are inclusive
(``TOLERANCE_MATCHED``); anything just over breaks to ``EXCEPTION``.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.reconciliation.errors import FloatMoneyError, ToleranceError
from finance.reconciliation.models import (
    MaterialityVerdict,
    PaymentRecord,
    PaymentStatus,
    ReconciliationOutcome,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance


def _leg(
    *,
    payment_id: str,
    net: Decimal,
    key: str = "key-tol",
    tenant_id: str = "tenant-acme",
) -> PaymentRecord:
    """Build a leg whose net equals the given amount (gross-backed)."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key=key,
        gross=net,
        fee=Decimal("0.00"),
        refund=Decimal("0.00"),
        net=net,
        currency="USD",
        status=PaymentStatus.SETTLED,
        occurred_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        tenant_id=tenant_id,
    )


class TestZeroDefault:
    """Zero-default tolerance means exact matching unless slack is injected."""

    def test_defaults_are_zero(self) -> None:
        """A bare tolerance carries no slack."""
        tolerance = ReconciliationTolerance()
        assert tolerance.absolute == Decimal("0")
        assert tolerance.percent == Decimal("0")
        assert tolerance.apply(Decimal("1000.00")) == Decimal("0")

    def test_zero_default_rejects_one_cent_drift(self) -> None:
        """A one-cent drift exceeds the zero window and breaks."""
        expected = _leg(payment_id="exp", net=Decimal("100.00"))
        observed = _leg(payment_id="obs", net=Decimal("100.01"))
        result = reconcile(expected, observed, ReconciliationTolerance())
        assert result.outcome is ReconciliationOutcome.EXCEPTION
        assert result.materiality is MaterialityVerdict.MATERIAL

    def test_zero_default_accepts_exact(self) -> None:
        """Identical nets close as MATCHED under the zero-default."""
        expected = _leg(payment_id="exp", net=Decimal("100.00"))
        observed = _leg(payment_id="obs", net=Decimal("100.00"))
        result = reconcile(expected, observed, ReconciliationTolerance())
        assert result.outcome is ReconciliationOutcome.MATCHED
        assert result.materiality is MaterialityVerdict.IMMATERIAL


class TestAbsoluteTolerance:
    """Absolute slack honors boundary-inclusive matching."""

    def test_boundary_equality_is_tolerance_matched(self) -> None:
        """abs(diff) == absolute closes as TOLERANCE_MATCHED, no code."""
        expected = _leg(payment_id="exp", net=Decimal("100.00"))
        observed = _leg(payment_id="obs", net=Decimal("105.00"))
        tolerance = ReconciliationTolerance(absolute=Decimal("5.00"))
        result = reconcile(expected, observed, tolerance)
        assert result.outcome is ReconciliationOutcome.TOLERANCE_MATCHED
        assert result.exception_code is None
        assert result.difference == Decimal("5.00")
        assert result.tolerance_applied == Decimal("5.00")
        assert result.materiality is MaterialityVerdict.IMMATERIAL

    def test_just_over_boundary_is_exception(self) -> None:
        """A drift one cent past absolute breaks to EXCEPTION/MATERIAL."""
        expected = _leg(payment_id="exp", net=Decimal("100.00"))
        observed = _leg(payment_id="obs", net=Decimal("105.01"))
        tolerance = ReconciliationTolerance(absolute=Decimal("5.00"))
        result = reconcile(expected, observed, tolerance)
        assert result.outcome is ReconciliationOutcome.EXCEPTION
        assert result.exception_code is not None
        assert result.materiality is MaterialityVerdict.MATERIAL

    def test_negative_difference_boundary(self) -> None:
        """The window is sign-insensitive: -5.00 also tolerance-matches."""
        expected = _leg(payment_id="exp", net=Decimal("100.00"))
        observed = _leg(payment_id="obs", net=Decimal("95.00"))
        tolerance = ReconciliationTolerance(absolute=Decimal("5.00"))
        result = reconcile(expected, observed, tolerance)
        assert result.outcome is ReconciliationOutcome.TOLERANCE_MATCHED
        assert result.difference == Decimal("-5.00")


class TestPercentTolerance:
    """Percent slack scales with the leg net."""

    def test_one_percent_allows_ten_on_thousand(self) -> None:
        """1% of 1000.00 allows a 10.00 drift (boundary inclusive)."""
        expected = _leg(payment_id="exp", net=Decimal("1000.00"))
        observed = _leg(payment_id="obs", net=Decimal("1010.00"))
        tolerance = ReconciliationTolerance(percent=Decimal("0.01"))
        assert tolerance.apply(Decimal("1000.00")) == Decimal("10.00")
        result = reconcile(expected, observed, tolerance)
        assert result.outcome is ReconciliationOutcome.TOLERANCE_MATCHED

    def test_percent_just_over_breaks(self) -> None:
        """10.01 on a 10.00 allowance breaks to EXCEPTION."""
        expected = _leg(payment_id="exp", net=Decimal("1000.00"))
        observed = _leg(payment_id="obs", net=Decimal("1010.01"))
        tolerance = ReconciliationTolerance(percent=Decimal("0.01"))
        result = reconcile(expected, observed, tolerance)
        assert result.outcome is ReconciliationOutcome.EXCEPTION

    def test_percent_scales_with_base(self) -> None:
        """The same 1% allows 1.00 on a 100.00 leg but not 1.01."""
        tolerance = ReconciliationTolerance(percent=Decimal("0.01"))
        assert tolerance.apply(Decimal("100.00")) == Decimal("1.00")
        assert tolerance.allows(Decimal("1.00"), Decimal("100.00")) is True
        assert tolerance.allows(Decimal("1.01"), Decimal("100.00")) is False

    def test_zero_base_still_honors_absolute(self) -> None:
        """A zero net still honors absolute (percent of zero is zero)."""
        tolerance = ReconciliationTolerance(
            absolute=Decimal("2.00"), percent=Decimal("0.01")
        )
        assert tolerance.apply(Decimal("0.00")) == Decimal("2.00")
        assert tolerance.allows(Decimal("2.00"), Decimal("0.00")) is True
        assert tolerance.allows(Decimal("2.01"), Decimal("0.00")) is False

    def test_combined_absolute_plus_percent(self) -> None:
        """Allowance is absolute + abs(percent * base) in Decimal."""
        tolerance = ReconciliationTolerance(
            absolute=Decimal("5.00"), percent=Decimal("0.01")
        )
        assert tolerance.apply(Decimal("1000.00")) == Decimal("15.00")
        assert tolerance.allows(Decimal("15.00"), Decimal("1000.00")) is True
        assert tolerance.allows(Decimal("15.01"), Decimal("1000.00")) is False


class TestTenantInjection:
    """The same legs reconcile differently under different tenant windows."""

    def test_same_break_strict_vs_lenient(self) -> None:
        """Zero tolerance breaks; tenant 5.00 slack tolerance-matches."""
        expected = _leg(payment_id="exp", net=Decimal("35000.00"))
        observed = _leg(payment_id="obs", net=Decimal("35004.00"))
        strict = reconcile(expected, observed, ReconciliationTolerance())
        lenient = reconcile(
            expected, observed, ReconciliationTolerance(absolute=Decimal("5.00"))
        )
        assert strict.outcome is ReconciliationOutcome.EXCEPTION
        assert lenient.outcome is ReconciliationOutcome.TOLERANCE_MATCHED
        assert strict.tolerance_applied == Decimal("0")
        assert lenient.tolerance_applied == Decimal("5.00")

    def test_percent_tenant_config(self) -> None:
        """A percent-based tenant tolerates a proportional drift."""
        expected = _leg(payment_id="exp", net=Decimal("50000.00"))
        observed = _leg(payment_id="obs", net=Decimal("50200.00"))
        half_pct = ReconciliationTolerance(percent=Decimal("0.005"))
        result = reconcile(expected, observed, half_pct)
        assert half_pct.apply(Decimal("50000.00")) == Decimal("250.00")
        assert result.outcome is ReconciliationOutcome.TOLERANCE_MATCHED


class TestToleranceValidation:
    """Bad tolerance config is rejected loudly, never silently clamped."""

    def test_negative_absolute_rejected(self) -> None:
        """A negative absolute bound raises ToleranceError."""
        with pytest.raises(ToleranceError, match="non-negative"):
            ReconciliationTolerance(absolute=Decimal("-1.00"))

    def test_negative_percent_rejected(self) -> None:
        """A negative percent raises ToleranceError."""
        with pytest.raises(ToleranceError, match="non-negative"):
            ReconciliationTolerance(percent=Decimal("-0.01"))

    def test_float_absolute_rejected(self) -> None:
        """A float absolute raises FloatMoneyError."""
        with pytest.raises(FloatMoneyError):
            ReconciliationTolerance(absolute=5.0)  # type: ignore[arg-type]

    def test_bool_percent_rejected(self) -> None:
        """A bool percent raises FloatMoneyError."""
        with pytest.raises(FloatMoneyError):
            ReconciliationTolerance(percent=True)  # type: ignore[arg-type]

    def test_non_decimal_base_rejected(self) -> None:
        """Applying to a non-Decimal base raises ToleranceError."""
        tolerance = ReconciliationTolerance(absolute=Decimal("1.00"))
        with pytest.raises(ToleranceError):
            tolerance.apply("100")  # type: ignore[arg-type]

    def test_float_difference_rejected(self) -> None:
        """Checking a float difference raises FloatMoneyError."""
        tolerance = ReconciliationTolerance(absolute=Decimal("10.00"))
        with pytest.raises(FloatMoneyError):
            tolerance.allows(1.5, Decimal("100.00"))  # type: ignore[arg-type]
