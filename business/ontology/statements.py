"""Financial statement ontology models.

Represents the three primary financial statements produced by the
FP&A platform: Balance Sheet, Income Statement, and Cash Flow Statement.
Each statement is composed of sections containing line items with
monetary amounts.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator

from business.canonical_types import CurrencyCode, EntityId, Money


class LineItem(BaseModel):
    """A single line item within a financial statement section.

    Line items can be aggregated (having sub-items) or leaf-level entries.
    For example, "Total Revenue" might have sub-items "Product Revenue"
    and "Service Revenue".

    Usage:
        item = LineItem(
            label="Gross Revenue",
            amount=Money(Decimal("5000000.00"), CurrencyCode("USD")),
        )
    """

    model_config = ConfigDict(frozen=True)

    label: str
    amount: Money | None = None
    sub_items: list[LineItem] = []

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Line item label cannot be empty")
        return v.strip()

    @property
    def total(self) -> Money | None:
        """Compute the total amount, aggregating sub-items if present.

        If the line item has sub-items, the total is the sum of all
        sub-item totals. If it has a direct amount, that is returned.
        If neither is present, returns None.

        Raises:
            ValueError: If sub-items have mixed currencies.
        """
        if not self.sub_items:
            return self.amount
        total: Money | None = None
        for item in self.sub_items:
            item_total = item.total
            if item_total is None:
                continue
            total = (
                item_total if total is None else total + item_total
            )  # CurrencyMismatchError if mixed
        return total

    def __str__(self) -> str:
        amt = f"{self.amount}" if self.amount else "-"
        return f"{self.label}: {amt}"


class StatementSection(BaseModel):
    """A section of a financial statement.

    Sections group related line items under a heading. For example,
    the Balance Sheet Assets section contains Cash, AR, Inventory, etc.

    Usage:
        assets = StatementSection(
            name="Current Assets",
            items=[LineItem(label="Cash", amount=cash)],
        )
    """

    model_config = ConfigDict(frozen=True)

    name: str
    items: list[LineItem] = []

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Section name cannot be empty")
        return v.strip()

    @property
    def total(self) -> Money | None:
        """Aggregate total of all items in this section."""
        if not self.items:
            return None
        total: Money | None = None
        for item in self.items:
            item_total = item.total
            if item_total is None:
                continue
            total = item_total if total is None else total + item_total
        return total

    def __str__(self) -> str:
        return f"{self.name}: {self.total} ({len(self.items)} items)"


class BalanceSheet(BaseModel):
    """A balance sheet statement for a specific entity and date.

    The balance sheet presents the financial position of an entity at a
    specific point in time, showing assets, liabilities, and equity.

    The fundamental accounting equation must hold:
        Total Assets = Total Liabilities + Total Equity

    Usage:
        bs = BalanceSheet(
            entity=EntityId("US-CORP"),
            as_of_date=date(2026, 6, 30),
            currency=CurrencyCode("USD"),
            assets=StatementSection(name="Assets", items=[...]),
            liabilities=StatementSection(name="Liabilities", items=[...]),
            equity=StatementSection(name="Equity", items=[...]),
        )
    """

    model_config = ConfigDict(frozen=True)

    entity: EntityId
    as_of_date: date
    currency: CurrencyCode
    assets: StatementSection
    liabilities: StatementSection
    equity: StatementSection

    @property
    def total_assets(self) -> Money | None:
        """Total assets from the assets section."""
        return self.assets.total

    @property
    def total_liabilities(self) -> Money | None:
        """Total liabilities from the liabilities section."""
        return self.liabilities.total

    @property
    def total_equity(self) -> Money | None:
        """Total equity from the equity section."""
        return self.equity.total

    @property
    def is_balanced(self) -> bool:
        """Check whether assets equal liabilities plus equity.

        Returns True if the accounting equation holds, or if any section
        total is unavailable.
        """
        if self.total_assets is None or self.total_liabilities is None:
            return True  # Cannot verify balance
        if self.total_equity is not None:
            liabilities_equity = self.total_liabilities + self.total_equity
        else:
            liabilities_equity = self.total_liabilities
        return (
            self.total_assets.currency == liabilities_equity.currency
            and self.total_assets.amount == liabilities_equity.amount
        )

    def __str__(self) -> str:
        return (
            f"Balance Sheet: {self.entity} as of {self.as_of_date} "
            f"({self.currency})"
        )


class IncomeStatement(BaseModel):
    """An income statement (P&L) for a specific entity and period.

    The income statement presents revenues, expenses, and resulting
    profit or loss over a fiscal period.

    Usage:
        is = IncomeStatement(
            entity=EntityId("US-CORP"),
            period=FiscalPeriod(2026, 6, "month"),
            currency=CurrencyCode("USD"),
            revenue=StatementSection(name="Revenue", items=[...]),
            cogs=StatementSection(name="COGS", items=[...]),
            operating_expenses=StatementSection(name="OpEx", items=[...]),
            other_income_expenses=StatementSection(name="Other", items=[...]),
        )
    """

    model_config = ConfigDict(frozen=True)

    entity: EntityId
    period: FiscalPeriod  # Imported below; resolved via model_rebuild
    currency: CurrencyCode
    revenue: StatementSection
    cogs: StatementSection
    operating_expenses: StatementSection
    other_income_expenses: StatementSection = StatementSection(name="Other Income/Expense")

    @property
    def gross_profit(self) -> Money | None:
        """Gross Profit = Revenue - COGS."""
        if self.revenue.total is None or self.cogs.total is None:
            return None
        return self.revenue.total - self.cogs.total

    @property
    def operating_income(self) -> Money | None:
        """Operating Income (EBIT) = Gross Profit - Operating Expenses."""
        if self.gross_profit is None or self.operating_expenses.total is None:
            return None
        return self.gross_profit - self.operating_expenses.total

    @property
    def net_income(self) -> Money | None:
        """Net Income = Operating Income +/- Other Income/Expense."""
        if self.operating_income is None:
            return None
        if (
            self.other_income_expenses.items
            and self.other_income_expenses.total is not None
        ):
            return self.operating_income + self.other_income_expenses.total
        return self.operating_income

    def __str__(self) -> str:
        return (
            f"Income Statement: {self.entity} for {self.period} "
            f"({self.currency})"
        )


class CashFlowStatement(BaseModel):
    """A cash flow statement for a specific entity and period.

    The cash flow statement shows cash inflows and outflows across
    operating, investing, and financing activities.

    Usage:
        cf = CashFlowStatement(
            entity=EntityId("US-CORP"),
            period=FiscalPeriod(2026, 6, "month"),
            currency=CurrencyCode("USD"),
            operating=StatementSection(name="Operating", items=[...]),
            investing=StatementSection(name="Investing", items=[...]),
            financing=StatementSection(name="Financing", items=[...]),
        )
    """

    model_config = ConfigDict(frozen=True)

    entity: EntityId
    period: FiscalPeriod  # Imported below; resolved via model_rebuild
    currency: CurrencyCode
    operating: StatementSection
    investing: StatementSection
    financing: StatementSection
    beginning_cash: Money | None = None
    ending_cash: Money | None = None

    @property
    def net_cash_operating(self) -> Money | None:
        """Net cash from operating activities."""
        return self.operating.total

    @property
    def net_cash_investing(self) -> Money | None:
        """Net cash from investing activities."""
        return self.investing.total

    @property
    def net_cash_financing(self) -> Money | None:
        """Net cash from financing activities."""
        return self.financing.total

    @property
    def net_change_in_cash(self) -> Money | None:
        """Total change in cash across all activities."""
        totals = [self.net_cash_operating, self.net_cash_investing, self.net_cash_financing]
        valid = [t for t in totals if t is not None]
        if not valid:
            return None
        result = valid[0]
        for t in valid[1:]:
            result = result + t
        return result

    @property
    def computed_ending_cash(self) -> Money | None:
        """Reconcile ending cash: beginning_cash + net_change_in_cash."""
        if self.beginning_cash is None or self.net_change_in_cash is None:
            return None
        return self.beginning_cash + self.net_change_in_cash

    def __str__(self) -> str:
        return (
            f"Cash Flow Statement: {self.entity} for {self.period} "
            f"({self.currency})"
        )


# Resolve forward references
from business.canonical_types import FiscalPeriod  # noqa: E402, F811

IncomeStatement.model_rebuild()
CashFlowStatement.model_rebuild()
