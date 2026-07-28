"""Budget domain models.

Budgets represent planned financial targets for a fiscal year.  Multiple
versions are supported: original (baseline), revised (mid-year updates),
and adjusted (post-analysis corrections).
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class BudgetVersion(StrEnum):
    """Identifies the stage of a budget in its lifecycle."""

    ORIGINAL = "original"
    """The initial baseline budget approved at the start of the fiscal year."""

    REVISED = "revised"
    """A formally updated version reflecting approved changes during the year."""

    ADJUSTED = "adjusted"
    """An automated or manual adjustment after variance analysis."""


class BudgetLine(BaseModel):
    """A single budget line item for a specific account, department, and period.

    Budget lines represent planned amounts at the finest granularity —
    one account × department × cost centre × period combination.
    """

    id: str
    """Unique budget line identifier."""

    account_id: str
    """The account this budget line belongs to."""

    department_id: str | None = None
    """Optional department attribution."""

    cost_center_id: str | None = None
    """Optional cost centre attribution."""

    amount: MoneyDecimal
    """Planned budget amount (monetary)."""

    period_id: str
    """The fiscal period this line is budgeted for."""

    version: BudgetVersion = BudgetVersion.ORIGINAL
    """Which budget version this line belongs to."""


class Budget(BaseModel):
    """A complete budget version for a company and fiscal year.

    A budget aggregates all planned amounts across accounts, departments,
    cost centres, and periods for a single version of the budget cycle.
    """

    id: str
    """Unique budget identifier."""

    company_id: str
    """The company this budget belongs to."""

    fiscal_year: int
    """The fiscal year this budget covers."""

    version: BudgetVersion
    """Which stage of the budget lifecycle this represents."""

    lines: list[BudgetLine]
    """All line items in this budget."""

    created_at: datetime
    """Timestamp when the budget was created."""

    updated_at: datetime
    """Timestamp when the budget was last updated."""
