"""Tests for the Variance domain models.

Covers both the analytics `finance.domain.variance` model (money-as-Decimal,
used by the engine) and the ontology `business.ontology.variance` model
(money-as-Money value object, used by canonical / golden-dataset layers).
Both encode the favorable/adverse classification invariant.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from business.canonical_types import CurrencyCode, FiscalPeriod, Money, Percentage
from business.ontology.variance import Variance as OntologyVariance
from business.ontology.variance import VarianceAnalysis
from finance.domain.variance import Variance as EngineVariance
from finance.domain.variance import VarianceDirection


def _money(amount: str, currency: str = "USD") -> Money:
    """Build a canonical Money value object."""
    return Money(amount=Decimal(amount), currency=CurrencyCode(code=currency))


def _fiscal_period() -> FiscalPeriod:
    """Build a July 2026 monthly fiscal period."""
    return FiscalPeriod(year=2026, period=7, type="month")


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


# =============================================================================
# business.ontology.variance.Variance — canonical model
# =============================================================================


class TestOntologyVarianceClassification:
    """Favorable / unfavorable classification invariants."""

    def test_revenue_actual_above_budget_is_favorable(self) -> None:
        """Revenue above budget is favorable."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert v.is_favorable is True
        assert v.direction == "favorable"

    def test_revenue_actual_below_budget_is_unfavorable(self) -> None:
        """Revenue below budget is unfavorable."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("80000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert v.is_favorable is False
        assert v.direction == "unfavorable"

    def test_expense_actual_below_budget_is_favorable(self) -> None:
        """Expense below budget is favorable (cost saving)."""
        v = OntologyVariance(
            account_name="COGS",
            actual=_money("80000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="expense",
        )
        assert v.is_favorable is True

    def test_expense_actual_above_budget_is_unfavorable(self) -> None:
        """Expense above budget is unfavorable (overspend)."""
        v = OntologyVariance(
            account_name="COGS",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="expense",
        )
        assert v.is_favorable is False

    def test_unspecified_type_follows_expense_rule(self) -> None:
        """Unknown account type classifies as expense (actual < budget favorable).

        Note: the source docstring for ``is_favorable`` claims unspecified types
        assume revenue classification, but the implementation treats them as
        expense. This test locks in the implemented behavior.
        """
        v = OntologyVariance(
            account_name="Misc",
            actual=_money("80000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type=None,
        )
        assert v.is_favorable is True

    def test_unspecified_type_with_surplus_is_not_favorable(self) -> None:
        """An unspecified type with actual > budget is not favorable (expense rule)."""
        v = OntologyVariance(
            account_name="Misc",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type=None,
        )
        assert v.is_favorable is False

    def test_equal_amounts_are_unfavorable_for_revenue(self) -> None:
        """Actual equal to budget is not favorable (strict comparison)."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("100000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert v.is_favorable is False

    def test_amount_property_is_actual_minus_budget(self) -> None:
        """The amount property computes actual - budget."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert v.amount == _money("20000.00")

    def test_amount_can_be_negative(self) -> None:
        """A negative variance amount is representable."""
        v = OntologyVariance(
            account_name="COGS",
            actual=_money("90000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="expense",
        )
        assert v.amount == _money("-10000.00")

    def test_percentage_of_budget(self) -> None:
        """The percentage property is the ratio to budget."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert v.percentage is not None
        assert v.percentage == Percentage(value=Decimal("0.2"))

    def test_percentage_none_when_budget_zero(self) -> None:
        """The percentage is None when the budget is zero (no division)."""
        v = OntologyVariance(
            account_name="New Product",
            actual=_money("5000.00"),
            budget=_money("0.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert v.percentage is None

    def test_mixed_currency_raises(self) -> None:
        """Actual and budget in different currencies are rejected at compute time."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("120000.00", currency="EUR"),
            budget=_money("100000.00", currency="USD"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        with pytest.raises(Exception, match="currencies do not match"):
            _ = v.amount

    def test_frozen_model(self) -> None:
        """The ontology variance is immutable."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        with pytest.raises(ValidationError):
            v.account_name = "Changed"  # type: ignore[misc]

    def test_str_representation(self) -> None:
        """The string representation includes the classification."""
        v = OntologyVariance(
            account_name="Consulting Revenue",
            actual=_money("120000.00"),
            budget=_money("100000.00"),
            period=_fiscal_period(),
            account_type="revenue",
        )
        assert "favorable" in str(v)
        assert "Consulting Revenue" in str(v)

    def test_missing_period_rejected(self) -> None:
        """The fiscal period is required."""
        with pytest.raises(ValidationError):
            OntologyVariance(
                account_name="Consulting Revenue",
                actual=_money("120000.00"),
                budget=_money("100000.00"),
                account_type="revenue",
            )  # type: ignore[call-arg]


# =============================================================================
# business.ontology.variance.VarianceAnalysis — aggregates
# =============================================================================


class TestVarianceAnalysis:
    """Aggregation invariants over collections of variances."""

    def _three_variances(self) -> list[OntologyVariance]:
        """Build a revenue / expense / revenue set with known outcomes."""
        return [
            OntologyVariance(
                account_name="Consulting Revenue",
                actual=_money("120000.00"),
                budget=_money("100000.00"),
                period=_fiscal_period(),
                account_type="revenue",
            ),
            OntologyVariance(
                account_name="COGS",
                actual=_money("80000.00"),
                budget=_money("100000.00"),
                period=_fiscal_period(),
                account_type="expense",
            ),
            OntologyVariance(
                account_name="Cloud Costs",
                actual=_money("130000.00"),
                budget=_money("100000.00"),
                period=_fiscal_period(),
                account_type="expense",
            ),
        ]

    def test_empty_analysis_totals_are_none(self) -> None:
        """An empty analysis yields None totals and neutral direction."""
        analysis = VarianceAnalysis(label="empty", period=_fiscal_period(), variances=[])
        assert analysis.total_actual is None
        assert analysis.total_budget is None
        assert analysis.total_variance is None
        assert analysis.net_direction == "neutral"

    def test_total_actual_sums(self) -> None:
        """total_actual is the sum of all actual amounts."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        assert analysis.total_actual == _money("330000.00")

    def test_total_budget_sums(self) -> None:
        """total_budget is the sum of all budget amounts."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        assert analysis.total_budget == _money("300000.00")

    def test_total_variance_sums(self) -> None:
        """total_variance is the sum of all variance amounts."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        assert analysis.total_variance == _money("30000.00")

    def test_favorable_and_unfavorable_counts(self) -> None:
        """Favorable and unfavorable counts classify each variance."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        assert analysis.favorable_count == 2  # revenue + COGS
        assert analysis.unfavorable_count == 1  # cloud costs

    def test_net_direction_favorable(self) -> None:
        """Positive total variance is favorable."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        assert analysis.net_direction == "favorable"

    def test_net_direction_neutral_when_zero(self) -> None:
        """A zero total variance is neutral."""
        analysis = VarianceAnalysis(
            label="Q3",
            period=_fiscal_period(),
            variances=[
                OntologyVariance(
                    account_name="Revenue",
                    actual=_money("100000.00"),
                    budget=_money("100000.00"),
                    period=_fiscal_period(),
                    account_type="revenue",
                )
            ],
        )
        assert analysis.net_direction == "neutral"

    def test_net_direction_is_amount_sign_based(self) -> None:
        """A positive total variance reports favorable (sign-based, not favorability).

        Note: ``net_direction`` reflects the sign of the summed variance amount,
        ignoring account type — an expense overspend (+amount) therefore reports
        ``favorable``. This locks in the implemented semantics.
        """
        analysis = VarianceAnalysis(
            label="Q3",
            period=_fiscal_period(),
            variances=[
                OntologyVariance(
                    account_name="COGS",
                    actual=_money("120000.00"),
                    budget=_money("100000.00"),
                    period=_fiscal_period(),
                    account_type="expense",
                )
            ],
        )
        assert analysis.net_direction == "favorable"

    def test_amount_threshold_filter(self) -> None:
        """variances_above_threshold filters by absolute amount."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        big = analysis.variances_above_threshold(amount_threshold=_money("25000.00"))
        assert [v.account_name for v in big] == ["Cloud Costs"]

    def test_pct_threshold_filter(self) -> None:
        """variances_above_threshold filters by percentage threshold."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        # All three variances are 20% or 30%; a 25% threshold keeps only Cloud Costs.
        big = analysis.variances_above_threshold(
            pct_threshold=Percentage(value=Decimal("0.25"))
        )
        assert [v.account_name for v in big] == ["Cloud Costs"]

    def test_no_threshold_returns_all(self) -> None:
        """Calling with no thresholds returns every variance."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        assert len(analysis.variances_above_threshold()) == 3

    def test_str_representation(self) -> None:
        """The analysis string summarizes counts."""
        analysis = VarianceAnalysis(
            label="Q3", period=_fiscal_period(), variances=self._three_variances()
        )
        text = str(analysis)
        assert "Q3" in text
        assert "3 variances" in text
        assert "2 favorable" in text
