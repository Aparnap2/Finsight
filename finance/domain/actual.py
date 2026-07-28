"""Actual domain models.

Actuals represent realised financial results — the real transactions that
occurred during a fiscal period.  They are sourced from the general ledger
(GL) and form the basis for variance analysis against budgets.
"""

from datetime import datetime

from pydantic import BaseModel

from finance.domain._types import MoneyDecimal


class ActualLine(BaseModel):
    """A single actual (realised) amount for a specific account and period.

    Actual lines represent the real financial results posted to a specific
    account, department, and cost centre combination during a period.
    """

    id: str
    """Unique actual line identifier."""

    account_id: str
    """The account this actual belongs to."""

    department_id: str | None = None
    """Optional department attribution."""

    cost_center_id: str | None = None
    """Optional cost centre attribution."""

    amount: MoneyDecimal
    """The realised monetary amount."""

    period_id: str
    """The fiscal period this actual was posted to."""

    transaction_count: int = 0
    """Number of underlying transactions aggregated into this line."""

    source: str = "gl"
    """Source system (e.g. ``\"gl\"``, ``\"manual\"``, ``\"adjustment\"``)."""


class Actual(BaseModel):
    """Actual financial results for a company, fiscal year, and period.

    An ``Actual`` aggregates all realised amounts (from the GL or manual
    entries) for a given period.  Actuals are the primary comparison point
    for budget vs. actual variance analysis.
    """

    id: str
    """Unique actuals batch identifier."""

    company_id: str
    """The company these actuals belong to."""

    fiscal_year: int
    """The fiscal year these actuals relate to."""

    lines: list[ActualLine]
    """All actual line items for this batch."""

    period_id: str
    """The fiscal period these actuals were posted to."""

    loaded_at: datetime
    """Timestamp when this actuals batch was loaded into the system."""
