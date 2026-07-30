"""Variance analysis ontology models.

Represents the difference between actual financial results and budgeted
or forecasted amounts, with favorable/unfavorable classification and
summary analysis.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from business.canonical_types import FiscalPeriod, Money, Percentage


def _is_revenue_account(account_type: str | None) -> bool:
    """Determine whether an account type is revenue-generating.

    Revenue accounts are favorable when actual > budget (more revenue
    is good). Expense accounts are favorable when actual < budget
    (less spending is good).

    Args:
        account_type: "revenue", "expense", or None.

    Returns:
        True if the account type is revenue-generating.
    """
    return account_type == "revenue"


class Variance(BaseModel):
    """A variance between actual results and budget/forecast.

    Represents the difference between two monetary values for a given
    account and period. The variance is classified as favorable or
    unfavorable based on the account type.

    For revenue accounts:
        Actual > Budget → Favorable (more revenue)
        Actual < Budget → Unfavorable (less revenue)

    For expense accounts:
        Actual < Budget → Favorable (less spending)
        Actual > Budget → Unfavorable (more spending)

    Usage:
        variance = Variance(
            account_name="Consulting Revenue",
            actual=Money(Decimal("120000.00"), CurrencyCode("USD")),
            budget=Money(Decimal("100000.00"), CurrencyCode("USD")),
            period=FiscalPeriod(2026, 7, "month"),
            account_type="revenue",
        )
        variance.is_favorable   # True
        variance.amount         # Money(20000.00, USD)
        variance.percentage     # Percentage(0.20) → "20.00%"
    """

    model_config = ConfigDict(frozen=True)

    account_name: str = ""
    account_number: str = ""
    actual: Money
    budget: Money
    prior_actual: Money | None = None
    prior_budget: Money | None = None
    period: FiscalPeriod
    account_type: str | None = None  # "revenue" or "expense" or None

    @property
    def amount(self) -> Money:
        """The variance amount: Actual - Budget."""
        return self.actual - self.budget

    @property
    def percentage(self) -> Percentage | None:
        """Variance as a percentage of the budget amount.

        Returns None if budget is zero (division by zero).
        """
        if self.budget.amount == Decimal("0"):
            return None
        abs_budget = abs(self.budget.amount)
        ratio = abs(self.amount.amount) / abs_budget
        return Percentage(value=ratio)

    @property
    def is_favorable(self) -> bool:
        """Whether this variance is financially favorable.

        For revenue: actual > budget is favorable.
        For expenses: actual < budget is favorable.
        For unspecified types: assumes revenue classification.
        """
        is_revenue = _is_revenue_account(self.account_type)
        if is_revenue:
            return self.actual > self.budget
        # Expense or unknown: actual < budget is favorable
        return self.actual < self.budget

    @property
    def direction(self) -> str:
        """Human-readable direction: 'favorable' or 'unfavorable'."""
        return "favorable" if self.is_favorable else "unfavorable"

    def __str__(self) -> str:
        return (
            f"Variance({self.account_name}: "
            f"Actual={self.actual}, Budget={self.budget}, "
            f"Var={self.amount}, {self.direction})"
        )


class VarianceAnalysis(BaseModel):
    """A collection of variances with summary statistics.

    Provides aggregated views of multiple variances, including totals,
    favorable/unfavorable counts, and materiality filtering.

    Usage:
        analysis = VarianceAnalysis(
            label="Q3 2026 Revenue Variance Analysis",
            period=FiscalPeriod(2026, 7, "month"),
            variances=[v1, v2, v3],
        )
    """

    label: str = ""
    period: FiscalPeriod
    variances: list[Variance] = []

    @property
    def total_actual(self) -> Money | None:
        """Sum of all actual amounts across variances."""
        if not self.variances:
            return None
        total = self.variances[0].actual
        for v in self.variances[1:]:
            total = total + v.actual
        return total

    @property
    def total_budget(self) -> Money | None:
        """Sum of all budget amounts across variances."""
        if not self.variances:
            return None
        total = self.variances[0].budget
        for v in self.variances[1:]:
            total = total + v.budget
        return total

    @property
    def total_variance(self) -> Money | None:
        """Sum of all variance amounts across variances."""
        if not self.variances:
            return None
        total = self.variances[0].amount
        for v in self.variances[1:]:
            total = total + v.amount
        return total

    @property
    def favorable_count(self) -> int:
        """Number of favorable variances."""
        return sum(1 for v in self.variances if v.is_favorable)

    @property
    def unfavorable_count(self) -> int:
        """Number of unfavorable variances."""
        return sum(1 for v in self.variances if not v.is_favorable)

    @property
    def net_direction(self) -> str:
        """Overall direction based on total variance.

        Returns 'favorable', 'unfavorable', or 'neutral'.
        """
        if self.total_variance is None:
            return "neutral"
        if self.total_variance.amount > Decimal("0"):
            return "favorable"
        if self.total_variance.amount < Decimal("0"):
            return "unfavorable"
        return "neutral"

    def variances_above_threshold(
        self,
        amount_threshold: Money | None = None,
        pct_threshold: Percentage | None = None,
    ) -> list[Variance]:
        """Filter variances exceeding materiality thresholds.

        Args:
            amount_threshold: Minimum absolute variance amount.
            pct_threshold: Minimum absolute variance percentage.

        Returns:
            Variances meeting or exceeding all provided thresholds.
        """
        result = list(self.variances)
        if amount_threshold is not None:
            result = [
                v for v in result
                if abs(v.amount) >= amount_threshold
            ]
        if pct_threshold is not None:
            result = [
                v for v in result
                if v.percentage is not None
                and v.percentage >= pct_threshold
            ]
        return result

    def __str__(self) -> str:
        return (
            f"VarianceAnalysis({self.label}, {self.period}, "
            f"{len(self.variances)} variances, "
            f"{self.favorable_count} favorable, "
            f"{self.unfavorable_count} unfavorable)"
        )
