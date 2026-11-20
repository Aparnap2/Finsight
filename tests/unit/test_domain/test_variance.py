"""Tests for the analytics Variance model (``finance.domain.variance``).

Money is ``decimal.Decimal`` on this surface; the favorable/adverse
classification invariant is the behaviour under test. The former
``business.ontology.variance`` half of this file was removed with the
``business/`` package.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.variance import Variance as EngineVariance
from finance.domain.variance import VarianceDirection

# =============================================================================
# finance.domain.variance.Variance — analytics model
# =============================================================================


class TestEngineVarianceConstruction:
    """Construction invariants of the engine Variance model."""

    def test_valid_variance_constructs(self) -> None:
        """A fully specified variance constructs."""
        v = EngineVariance(
            id="var-001",
            account_id="acc-1000",
            account_name="Consulting Revenue",
            actual_amount=Decimal("120000.00"),
            budget_amount=Decimal("100000.00"),
            variance_amount=Decimal("20000.00"),
            variance_pct=Decimal("20.00"),
            direction=VarianceDirection.FAVORABLE,
            period_id="2026-07",
        )
        assert v.id == "var-001"
        assert v.direction == VarianceDirection.FAVORABLE

    def test_defaults_are_sane(self) -> None:
        """Optional fields default to safe values."""
        v = EngineVariance(
            id="var-002",
            account_id="acc-1000",
            account_name="Consulting Revenue",
            actual_amount=Decimal("100.00"),
            budget_amount=Decimal("100.00"),
            variance_amount=Decimal("0.00"),
            variance_pct=Decimal("0.00"),
            direction=VarianceDirection.FAVORABLE,
            period_id="2026-07",
        )
        assert v.department_id is None
        assert v.is_material is False
        assert v.materiality_tier is None
        assert v.drivers == []

    def test_float_amounts_rejected(self) -> None:
        """Float monetary values are rejected by the engine model."""
        with pytest.raises(ValidationError, match="Float values are not allowed"):
            EngineVariance(
                id="var-003",
                account_id="acc-1000",
                account_name="Consulting Revenue",
                actual_amount=120000.00,
                budget_amount=Decimal("100000.00"),
                variance_amount=Decimal("20000.00"),
                variance_pct=Decimal("20.00"),
                direction=VarianceDirection.FAVORABLE,
                period_id="2026-07",
            )

    def test_string_amounts_accepted(self) -> None:
        """String amounts are coerced to Decimal at the boundary."""
        v = EngineVariance(
            id="var-004",
            account_id="acc-1000",
            account_name="Consulting Revenue",
            actual_amount="120000.00",
            budget_amount="100000.00",
            variance_amount="20000.00",
            variance_pct="20.00",
            direction=VarianceDirection.FAVORABLE,
            period_id="2026-07",
        )
        assert isinstance(v.actual_amount, Decimal)

    def test_missing_id_rejected(self) -> None:
        """A variance identifier is required."""
        with pytest.raises(ValidationError):
            EngineVariance(
                account_id="acc-1000",  # type: ignore[call-arg]
                account_name="Consulting Revenue",
                actual_amount=Decimal("100.00"),
                budget_amount=Decimal("100.00"),
                variance_amount=Decimal("0.00"),
                variance_pct=Decimal("0.00"),
                direction=VarianceDirection.FAVORABLE,
                period_id="2026-07",
            )

    def test_invalid_direction_rejected(self) -> None:
        """An unknown direction string is rejected."""
        with pytest.raises(ValidationError):
            EngineVariance(
                id="var-005",
                account_id="acc-1000",
                account_name="Consulting Revenue",
                actual_amount=Decimal("100.00"),
                budget_amount=Decimal("100.00"),
                variance_amount=Decimal("0.00"),
                variance_pct=Decimal("0.00"),
                direction="sideways",
                period_id="2026-07",
            )

    def test_direction_enum_values(self) -> None:
        """The enum exposes the canonical string values."""
        assert VarianceDirection.FAVORABLE.value == "favorable"
        assert VarianceDirection.ADVERSE.value == "adverse"

    def test_str_direction_round_trip(self) -> None:
        """StrEnum values are usable as serialized strings."""
        assert str(VarianceDirection.FAVORABLE) == "favorable"


class TestEngineVarianceValidation:
    """Semantic validation of engine Variance values."""

    def test_zero_budget_variance_constructs(self) -> None:
        """A variance with zero budget is representable (division guarded upstream)."""
        v = EngineVariance(
            id="var-010",
            account_id="acc-1000",
            account_name="Consulting Revenue",
            actual_amount=Decimal("100.00"),
            budget_amount=Decimal("0.00"),
            variance_amount=Decimal("100.00"),
            variance_pct=Decimal("0.00"),
            direction=VarianceDirection.FAVORABLE,
            period_id="2026-07",
        )
        assert v.budget_amount == Decimal("0.0000")

    def test_negative_variance_amount_constructs(self) -> None:
        """Negative variance amounts are valid (adverse outcomes)."""
        v = EngineVariance(
            id="var-011",
            account_id="acc-2000",
            account_name="COGS",
            actual_amount=Decimal("90000.00"),
            budget_amount=Decimal("100000.00"),
            variance_amount=Decimal("-10000.00"),
            variance_pct=Decimal("-10.00"),
            direction=VarianceDirection.ADVERSE,
            period_id="2026-07",
        )
        assert v.variance_amount == Decimal("-10000.0000")

    def test_large_amounts_preserve_precision(self) -> None:
        """Large monetary values do not lose precision."""
        v = EngineVariance(
            id="var-012",
            account_id="acc-1000",
            account_name="Consulting Revenue",
            actual_amount=Decimal("999999999999.99"),
            budget_amount=Decimal("1.00"),
            variance_amount=Decimal("999999999998.99"),
            variance_pct=Decimal("99999999999899.00"),
            direction=VarianceDirection.FAVORABLE,
            period_id="2026-07",
        )
        assert v.variance_amount == Decimal("999999999998.9900")
