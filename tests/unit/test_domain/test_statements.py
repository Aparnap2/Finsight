"""Tests for the financial statement ontology models.

Covers the three primary statements (``BalanceSheet``, ``IncomeStatement``,
``CashFlowStatement``) and their building blocks (``LineItem``,
``StatementSection``) from ``business/ontology/statements.py``.

Key invariants exercised:

* ``LineItem`` labels and ``StatementSection`` names are required and
  non-empty (whitespace-only rejected, surrounding whitespace stripped).
* ``LineItem.total`` aggregates sub-items and raises
  ``CurrencyMismatchError`` on mixed currencies.
* ``BalanceSheet.is_balanced`` enforces Assets = Liabilities + Equity.
* ``IncomeStatement`` computes gross profit, operating income, and net
  income with correct ``None`` propagation.
* ``CashFlowStatement`` reconciles ending cash from beginning cash plus
  the net change across operating/investing/financing activities.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from business.canonical_types import (
    CurrencyCode,
    CurrencyMismatchError,
    EntityId,
    FiscalPeriod,
    Money,
)
from business.ontology.statements import (
    BalanceSheet,
    CashFlowStatement,
    IncomeStatement,
    LineItem,
    StatementSection,
)


def _money(amount: str, currency: str = "USD") -> Money:
    """Build a Money value object."""
    return Money(amount=Decimal(amount), currency=CurrencyCode(code=currency))


def _item(label: str, amount: str | None = None) -> LineItem:
    """Build a leaf line item."""
    return LineItem(
        label=label,
        amount=_money(amount) if amount is not None else None,
    )


def _entity(entity_id: str = "US-CORP") -> EntityId:
    """Build an entity identifier."""
    return EntityId(id=entity_id)


def _period() -> FiscalPeriod:
    """Build a monthly fiscal period for June 2026."""
    return FiscalPeriod(year=2026, period=6, type="month")


# =============================================================================
# LineItem
# =============================================================================


class TestLineItem:
    """Line item construction and aggregation."""

    def test_leaf_item_returns_its_amount(self) -> None:
        """A leaf item's total is its direct amount."""
        item = _item("Cash", "1000.00")
        assert item.total == _money("1000.00")

    def test_leaf_item_without_amount_returns_none(self) -> None:
        """A leaf item with no amount has no total."""
        item = _item("Memo")
        assert item.total is None

    def test_aggregated_item_sums_sub_items(self) -> None:
        """An item with sub-items totals the sum of sub-item totals."""
        item = LineItem(
            label="Total Revenue",
            sub_items=[_item("Product", "3000.00"), _item("Service", "2000.00")],
        )
        assert item.total == _money("5000.00")

    def test_aggregated_item_ignores_none_sub_items(self) -> None:
        """Sub-items without amounts are skipped in the total."""
        item = LineItem(
            label="Total Revenue",
            sub_items=[_item("Product", "3000.00"), _item("Memo")],
        )
        assert item.total == _money("3000.00")

    def test_aggregated_item_with_all_none_returns_none(self) -> None:
        """If every sub-item has no amount, the total is None."""
        item = LineItem(label="Total", sub_items=[_item("A"), _item("B")])
        assert item.total is None

    def test_nested_aggregation(self) -> None:
        """Sub-items can themselves aggregate sub-items."""
        item = LineItem(
            label="Total",
            sub_items=[
                LineItem(label="Group", sub_items=[_item("A", "100.00"), _item("B", "50.00")]),
                _item("C", "25.00"),
            ],
        )
        assert item.total == _money("175.00")

    def test_mixed_currency_sub_items_raise(self) -> None:
        """Mixed-currency sub-items raise CurrencyMismatchError."""
        item = LineItem(
            label="Total",
            sub_items=[
                _item("USD", "100.00"),
                LineItem(label="EUR", amount=_money("50.00", currency="EUR")),
            ],
        )
        with pytest.raises(CurrencyMismatchError):
            _ = item.total

    def test_label_required(self) -> None:
        """A line item requires a label."""
        with pytest.raises(ValidationError):
            LineItem(amount=_money("100.00"))  # type: ignore[call-arg]

    def test_empty_label_rejected(self) -> None:
        """An empty label is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            LineItem(label="", amount=_money("100.00"))

    def test_whitespace_label_rejected(self) -> None:
        """A whitespace-only label is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            LineItem(label="   ", amount=_money("100.00"))

    def test_label_is_stripped(self) -> None:
        """Surrounding whitespace is stripped from the label."""
        item = LineItem(label="  Cash  ", amount=_money("100.00"))
        assert item.label == "Cash"

    def test_float_amount_rejected(self) -> None:
        """A float amount is structurally rejected."""
        with pytest.raises(ValidationError):
            LineItem(label="Cash", amount=1000.0)

    def test_is_frozen(self) -> None:
        """Line items are immutable."""
        item = _item("Cash", "100.00")
        with pytest.raises(ValidationError):
            item.label = "Changed"  # type: ignore[misc]

    def test_str_renders_label_and_amount(self) -> None:
        """__str__ renders the label and amount (4-decimal quantization)."""
        assert str(_item("Cash", "100.00")) == "Cash: 100.0000 USD"

    def test_str_renders_dash_without_amount(self) -> None:
        """__str__ renders a dash when there is no amount."""
        assert str(_item("Memo")) == "Memo: -"


# =============================================================================
# StatementSection
# =============================================================================


class TestStatementSection:
    """Statement section construction and aggregation."""

    def test_total_sums_items(self) -> None:
        """A section's total sums its item totals."""
        section = StatementSection(
            name="Assets", items=[_item("Cash", "100.00"), _item("AR", "50.00")]
        )
        assert section.total == _money("150.00")

    def test_empty_section_total_is_none(self) -> None:
        """An empty section has no total."""
        section = StatementSection(name="Assets")
        assert section.total is None

    def test_section_skips_none_items(self) -> None:
        """Items without amounts are skipped in the section total."""
        section = StatementSection(
            name="Assets", items=[_item("Cash", "100.00"), _item("Memo")]
        )
        assert section.total == _money("100.00")

    def test_name_required(self) -> None:
        """A section requires a name."""
        with pytest.raises(ValidationError):
            StatementSection(items=[_item("Cash", "100.00")])  # type: ignore[call-arg]

    def test_empty_name_rejected(self) -> None:
        """An empty section name is rejected."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            StatementSection(name="", items=[_item("Cash", "100.00")])

    def test_name_is_stripped(self) -> None:
        """Surrounding whitespace is stripped from the section name."""
        section = StatementSection(name="  Assets  ")
        assert section.name == "Assets"

    def test_is_frozen(self) -> None:
        """Sections are immutable."""
        section = StatementSection(name="Assets")
        with pytest.raises(ValidationError):
            section.name = "Liabilities"  # type: ignore[misc]


# =============================================================================
# BalanceSheet
# =============================================================================


class TestBalanceSheet:
    """Balance sheet construction and the accounting equation."""

    def _balanced(self) -> BalanceSheet:
        """A balance sheet where assets equal liabilities plus equity."""
        return BalanceSheet(
            entity=_entity(),
            as_of_date=date(2026, 6, 30),
            currency=CurrencyCode(code="USD"),
            assets=StatementSection(name="Assets", items=[_item("Cash", "1000.00")]),
            liabilities=StatementSection(
                name="Liabilities", items=[_item("AP", "400.00")]
            ),
            equity=StatementSection(name="Equity", items=[_item("RE", "600.00")]),
        )

    def test_balanced_sheet_is_balanced(self) -> None:
        """Assets equal liabilities plus equity."""
        assert self._balanced().is_balanced is True

    def test_unbalanced_sheet_is_not_balanced(self) -> None:
        """Assets not equal to liabilities plus equity is unbalanced."""
        bs = BalanceSheet(
            entity=_entity(),
            as_of_date=date(2026, 6, 30),
            currency=CurrencyCode(code="USD"),
            assets=StatementSection(name="Assets", items=[_item("Cash", "1000.00")]),
            liabilities=StatementSection(
                name="Liabilities", items=[_item("AP", "500.00")]
            ),
            equity=StatementSection(name="Equity", items=[_item("RE", "600.00")]),
        )
        assert bs.is_balanced is False

    def test_total_assets_property(self) -> None:
        """total_assets reflects the assets section total."""
        assert self._balanced().total_assets == _money("1000.00")

    def test_total_liabilities_property(self) -> None:
        """total_liabilities reflects the liabilities section total."""
        assert self._balanced().total_liabilities == _money("400.00")

    def test_total_equity_property(self) -> None:
        """total_equity reflects the equity section total."""
        assert self._balanced().total_equity == _money("600.00")

    def test_unavailable_totals_are_balanced(self) -> None:
        """If a section total is unavailable, is_balanced returns True."""
        bs = BalanceSheet(
            entity=_entity(),
            as_of_date=date(2026, 6, 30),
            currency=CurrencyCode(code="USD"),
            assets=StatementSection(name="Assets", items=[_item("Cash", "1000.00")]),
            liabilities=StatementSection(name="Liabilities"),
            equity=StatementSection(name="Equity", items=[_item("RE", "600.00")]),
        )
        assert bs.is_balanced is True

    def test_entity_required(self) -> None:
        """A balance sheet requires an entity."""
        with pytest.raises(ValidationError):
            BalanceSheet(  # type: ignore[call-arg]
                as_of_date=date(2026, 6, 30),
                currency=CurrencyCode(code="USD"),
                assets=StatementSection(name="Assets"),
                liabilities=StatementSection(name="Liabilities"),
                equity=StatementSection(name="Equity"),
            )

    def test_is_frozen(self) -> None:
        """Balance sheets are immutable."""
        bs = self._balanced()
        with pytest.raises(ValidationError):
            bs.as_of_date = date(2026, 7, 31)  # type: ignore[misc]

    def test_str_renders_entity_and_date(self) -> None:
        """__str__ renders the entity and as-of date."""
        assert str(self._balanced()) == "Balance Sheet: US-CORP as of 2026-06-30 (USD)"


# =============================================================================
# IncomeStatement
# =============================================================================


class TestIncomeStatement:
    """Income statement profit metrics."""

    def _statement(self) -> IncomeStatement:
        """A statement with revenue 1000, COGS 400, OpEx 200, other 50."""
        return IncomeStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            revenue=StatementSection(name="Revenue", items=[_item("Sales", "1000.00")]),
            cogs=StatementSection(name="COGS", items=[_item("COGS", "400.00")]),
            operating_expenses=StatementSection(
                name="OpEx", items=[_item("SG&A", "200.00")]
            ),
            other_income_expenses=StatementSection(
                name="Other", items=[_item("Interest", "50.00")]
            ),
        )

    def test_gross_profit(self) -> None:
        """Gross profit = revenue - COGS."""
        assert self._statement().gross_profit == _money("600.00")

    def test_operating_income(self) -> None:
        """Operating income = gross profit - OpEx."""
        assert self._statement().operating_income == _money("400.00")

    def test_net_income_with_other(self) -> None:
        """Net income includes other income/expense."""
        assert self._statement().net_income == _money("450.00")

    def test_net_income_without_other(self) -> None:
        """Net income equals operating income when other is empty."""
        stmt = IncomeStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            revenue=StatementSection(name="Revenue", items=[_item("Sales", "1000.00")]),
            cogs=StatementSection(name="COGS", items=[_item("COGS", "400.00")]),
            operating_expenses=StatementSection(
                name="OpEx", items=[_item("SG&A", "200.00")]
            ),
        )
        assert stmt.net_income == _money("400.00")

    def test_gross_profit_none_when_revenue_missing(self) -> None:
        """Gross profit is None when revenue is unavailable."""
        stmt = IncomeStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            revenue=StatementSection(name="Revenue"),
            cogs=StatementSection(name="COGS", items=[_item("COGS", "400.00")]),
            operating_expenses=StatementSection(name="OpEx"),
        )
        assert stmt.gross_profit is None

    def test_operating_income_none_when_cogs_missing(self) -> None:
        """Operating income is None when gross profit is unavailable."""
        stmt = IncomeStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            revenue=StatementSection(name="Revenue", items=[_item("Sales", "1000.00")]),
            cogs=StatementSection(name="COGS"),
            operating_expenses=StatementSection(name="OpEx"),
        )
        assert stmt.operating_income is None

    def test_net_income_none_when_operating_income_missing(self) -> None:
        """Net income is None when operating income is unavailable."""
        stmt = IncomeStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            revenue=StatementSection(name="Revenue"),
            cogs=StatementSection(name="COGS"),
            operating_expenses=StatementSection(name="OpEx"),
        )
        assert stmt.net_income is None

    def test_requires_period(self) -> None:
        """An income statement requires a fiscal period."""
        with pytest.raises(ValidationError):
            IncomeStatement(  # type: ignore[call-arg]
                currency=CurrencyCode(code="USD"),
                revenue=StatementSection(name="Revenue"),
                cogs=StatementSection(name="COGS"),
                operating_expenses=StatementSection(name="OpEx"),
            )

    def test_str_renders_period(self) -> None:
        """__str__ renders the entity and period."""
        assert str(self._statement()) == "Income Statement: US-CORP for 2026-06 (USD)"


# =============================================================================
# CashFlowStatement
# =============================================================================


class TestCashFlowStatement:
    """Cash flow statement reconciliation."""

    def _statement(self) -> CashFlowStatement:
        """A statement with operating 100, investing -30, financing -20."""
        return CashFlowStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            operating=StatementSection(name="Operating", items=[_item("Ops", "100.00")]),
            investing=StatementSection(name="Investing", items=[_item("CapEx", "-30.00")]),
            financing=StatementSection(name="Financing", items=[_item("Debt", "-20.00")]),
            beginning_cash=_money("50.00"),
        )

    def test_net_cash_operating(self) -> None:
        """Net cash from operating activities."""
        assert self._statement().net_cash_operating == _money("100.00")

    def test_net_cash_investing(self) -> None:
        """Net cash from investing activities."""
        assert self._statement().net_cash_investing == _money("-30.00")

    def test_net_cash_financing(self) -> None:
        """Net cash from financing activities."""
        assert self._statement().net_cash_financing == _money("-20.00")

    def test_net_change_in_cash(self) -> None:
        """Net change in cash sums all activities."""
        assert self._statement().net_change_in_cash == _money("50.00")

    def test_computed_ending_cash(self) -> None:
        """Ending cash = beginning cash + net change."""
        assert self._statement().computed_ending_cash == _money("100.00")

    def test_net_change_none_when_all_activities_empty(self) -> None:
        """Net change is None when every activity has no total."""
        stmt = CashFlowStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            operating=StatementSection(name="Operating"),
            investing=StatementSection(name="Investing"),
            financing=StatementSection(name="Financing"),
        )
        assert stmt.net_change_in_cash is None

    def test_computed_ending_cash_none_without_beginning(self) -> None:
        """Ending cash is None when beginning cash is unavailable."""
        stmt = CashFlowStatement(
            entity=_entity(),
            period=_period(),
            currency=CurrencyCode(code="USD"),
            operating=StatementSection(name="Operating", items=[_item("Ops", "100.00")]),
            investing=StatementSection(name="Investing"),
            financing=StatementSection(name="Financing"),
        )
        assert stmt.computed_ending_cash is None

    def test_ending_cash_field_is_optional(self) -> None:
        """ending_cash is an optional field defaulting to None."""
        stmt = self._statement()
        assert stmt.ending_cash is None

    def test_str_frozen(self) -> None:
        """__str__ renders the entity and period."""
        assert str(self._statement()) == "Cash Flow Statement: US-CORP for 2026-06 (USD)"