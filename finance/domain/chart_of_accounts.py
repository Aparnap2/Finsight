"""Chart of Accounts domain models.

The **Chart of Accounts (COA)** defines the structured hierarchy of financial
accounts used to classify all transactions.  It is the foundational taxonomy
upon which budgeting, forecasting, and variance analysis are built.
"""

from enum import StrEnum

from pydantic import BaseModel


class AccountType(StrEnum):
    """Standard classification of a financial account."""

    REVENUE = "revenue"
    """Income from primary business activities."""

    COGS = "cogs"
    """Cost of Goods Sold — direct costs of producing goods/services."""

    OPEX = "opex"
    """Operating Expenses — indirect costs of running the business."""

    OTHER_INCOME = "other_income"
    """Non-operating income and expenses (interest, FX, one-time items)."""

    ASSET = "asset"
    """Balance sheet asset accounts."""

    LIABILITY = "liability"
    """Balance sheet liability accounts."""

    EQUITY = "equity"
    """Balance sheet equity accounts."""


class Account(BaseModel):
    """A single account in the chart of accounts.

    Accounts follow a 4-digit numeric code convention organised by range
    (e.g. 4xxx = Revenue, 5xxx = COGS).  They form a hierarchical tree
    via the ``parent_code`` field.
    """

    id: str
    """Unique account identifier."""

    code: str
    """Account code (e.g. ``\"4010\"`` for Consulting Revenue)."""

    name: str
    """Human-readable account name (e.g. ``\"Consulting Revenue\"``)."""

    type: AccountType
    """The account's classification."""

    parent_code: str | None = None
    """Parent account code for hierarchical roll-ups (e.g. ``\"4000\"``)."""

    is_active: bool = True
    """Whether this account is active. Deactivated accounts are excluded from budgets/forecasts."""

    currency: str | None = None
    """Optional currency override. If ``None``, uses the company's base currency."""


class ChartOfAccounts(BaseModel):
    """A company's full chart of accounts.

    Defines the complete set of financial accounts used to classify all
    transactions, budgets, and forecasts for a company.
    """

    id: str
    """Unique COA identifier."""

    company_id: str
    """The company this chart belongs to."""

    accounts: list[Account]
    """All accounts in the chart.  Account codes must be unique within a chart."""

    version: int = 1
    """Version number incremented on structural changes."""
