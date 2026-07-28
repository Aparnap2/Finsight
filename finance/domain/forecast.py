"""Forecast domain models.

Forecasts represent projected financial outcomes for future periods.
Multiple scenarios (base, optimistic, pessimistic) allow sensitivity
analysis and what-if planning.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class ForecastScenario(StrEnum):
    """Identifies which forecast scenario a projection belongs to."""

    BASE = "base"
    """The most-likely, central forecast scenario."""

    OPTIMISTIC = "optimistic"
    """An upside scenario with favourable assumptions."""

    PESSIMISTIC = "pessimistic"
    """A downside scenario with conservative or adverse assumptions."""


class ForecastLine(BaseModel):
    """A single forecast projection for a specific account and period.

    Forecast lines represent predicted amounts at the finest granularity —
    one account × department × cost centre × period × scenario combination.
    """

    id: str
    """Unique forecast line identifier."""

    account_id: str
    """The account this forecast line belongs to."""

    department_id: str | None = None
    """Optional department attribution."""

    cost_center_id: str | None = None
    """Optional cost centre attribution."""

    amount: MoneyDecimal
    """The projected monetary amount."""

    period_id: str
    """The fiscal period this forecast targets."""

    scenario: ForecastScenario = ForecastScenario.BASE
    """Which scenario this forecast line belongs to."""


class Forecast(BaseModel):
    """A complete forecast scenario for a company and fiscal year.

    A forecast aggregates all projected amounts across accounts, departments,
    cost centres, and periods for a single scenario (base / optimistic /
    pessimistic).
    """

    id: str
    """Unique forecast identifier."""

    company_id: str
    """The company this forecast belongs to."""

    fiscal_year: int
    """The fiscal year this forecast covers."""

    scenario: ForecastScenario
    """Which scenario this forecast represents."""

    lines: list[ForecastLine]
    """All forecast line items."""

    created_at: datetime
    """Timestamp when the forecast was created."""

    updated_at: datetime
    """Timestamp when the forecast was last updated."""
