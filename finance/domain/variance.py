"""Variance domain model.

Variances represent the difference between actual and budget amounts.
They are the core analytical unit in FP&A — each variance is classified as
favourable or adverse, assessed for materiality, and analysed for root
causes.
"""

from enum import StrEnum

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class VarianceDirection(StrEnum):
    """Whether a variance is favourable or adverse."""

    FAVORABLE = "favorable"
    """Actual is better than budget (e.g. higher revenue or lower costs)."""

    ADVERSE = "adverse"
    """Actual is worse than budget (e.g. lower revenue or higher costs)."""


class Variance(BaseModel):
    """The difference between actual and budget amounts for an account.

    Variances are the fundamental analytical unit.  Each variance compares
    actual performance against the budget, is classified by direction,
    assessed for materiality, and linked to root-cause drivers.
    """

    id: str
    """Unique variance identifier."""

    account_id: str
    """The account this variance relates to."""

    account_name: str
    """Denormalised account name for display."""

    department_id: str | None = None
    """Optional department attribution."""

    actual_amount: MoneyDecimal
    """The realised amount."""

    budget_amount: MoneyDecimal
    """The planned / budgeted amount."""

    variance_amount: MoneyDecimal
    """The difference (actual - budget)."""

    variance_pct: MoneyDecimal
    """The percentage difference ((actual - budget) / |budget| * 100)."""

    direction: VarianceDirection
    """Whether this variance is favourable or adverse."""

    period_id: str
    """The fiscal period this variance was calculated for."""

    is_material: bool = False
    """Whether this variance exceeds materiality thresholds."""

    materiality_tier: str | None = None
    """Materiality classification (``\"critical\"``, ``\"high\"``, ``\"medium\"``, ``\"low\"``)."""

    drivers: list[str] = []
    """Identifiers of operational / macro drivers that explain this variance."""
