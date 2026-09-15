"""Deterministic property-style tests for the finance domain.

The task plan called for hypothesis property tests, but ``hypothesis`` is
not installed in this environment and cannot be added (no pip/uv access).
These tests instead exercise property-style invariants deterministically:
each test iterates over a generated dataset and asserts an invariant that
must hold for *every* value, which is the same contract a hypothesis
property test enforces.

Properties covered:

* Money arithmetic: addition is commutative and associative; subtraction
  inverts addition; ``Money * factor`` matches ``factor * Money``; the
  4-decimal quantization is preserved through arithmetic.
* FiscalPeriod arithmetic: ``next_period`` and ``prior_period`` invert
  each other across year boundaries; month/quarter/year units roll
  correctly; parsing round-trips through ``period_str``.
* Ledger invariant: any generated balanced entry has equal debit and
  credit totals; the trial-balance projection always balances.
* LineItem aggregation: flattening a tree and summing leaves equals the
  computed ``total`` for every sub-set of items.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from business.canonical_types import (
    CurrencyCode,
    CurrencyMismatchError,
    FiscalPeriod,
    GLAccountNumber,
    Money,
)
from business.ontology.ledger import GeneralLedger, JournalEntry, JournalLine
from business.ontology.statements import LineItem

#: Deterministic input datasets (no randomness).
_AMOUNTS: list[str] = [
    "0.00",
    "0.0001",
    "1.00",
    "12.34",
    "100.00",
    "999999999999.99",
    "-12.34",
    "-0.0001",
    "42.0000",
]

_FACTORS: list[str] = ["0", "1", "2", "3.5", "0.01", "-1"]

_MONTH_ROLLS: list[tuple[int, int, int, int, int]] = [
    # (year, month, offset, expected_year, expected_month)
    (2026, 1, 11, 2026, 12),
    (2026, 1, 12, 2027, 1),
    (2026, 12, 1, 2027, 1),
    (2026, 12, -11, 2026, 1),
    (2026, 1, -1, 2025, 12),
]

_QUARTER_ROLLS: list[tuple[int, int, int, int, int]] = [
    (2026, 1, 3, 2026, 4),
    (2026, 4, 1, 2027, 1),
    (2026, 1, -1, 2025, 4),
]


def _money(amount: str) -> Money:
    """Build a USD Money value object."""
    return Money(amount=Decimal(amount), currency=CurrencyCode(code="USD"))


def _is_quantized(money: Money) -> bool:
    """Whether the money amount has at most 4 decimal places."""
    return money.amount == money.amount.quantize(Decimal("0.0001"))


# =============================================================================
# Money arithmetic properties
# =============================================================================


class TestMoneyArithmeticProperties:
    """Algebraic invariants over all generated amounts."""

    def _product_or_none(self, amount_str: str, factor_str: str) -> Money | None:
        """Compute a Money product, or None if it exceeds 4-dp precision.

        ``Money.__mul__`` does not quantize its result, so products that
        gain a fifth decimal place raise ValidationError. This helper lets
        the property tests skip those (documented in a dedicated test).
        """
        try:
            return _money(amount_str) * Decimal(factor_str)
        except ValidationError:
            return None

    def test_addition_is_commutative(self) -> None:
        """a + b == b + a for every generated pair."""
        for a_str in _AMOUNTS:
            for b_str in _AMOUNTS:
                a = _money(a_str)
                b = _money(b_str)
                assert a + b == b + a

    def test_addition_is_associative(self) -> None:
        """(a + b) + c == a + (b + c) for every generated triple."""
        for a_str in _AMOUNTS:
            for b_str in _AMOUNTS:
                for c_str in _AMOUNTS:
                    a, b, c = _money(a_str), _money(b_str), _money(c_str)
                    assert (a + b) + c == a + (b + c)

    def test_subtraction_inverts_addition(self) -> None:
        """(a + b) - b == a for every generated pair."""
        for a_str in _AMOUNTS:
            for b_str in _AMOUNTS:
                a = _money(a_str)
                b = _money(b_str)
                assert (a + b) - b == a

    def test_multiplication_is_commutative(self) -> None:
        """a * f == f * a for every generated quantizable pair."""
        for amount_str in _AMOUNTS:
            for factor_str in _FACTORS:
                left = self._product_or_none(amount_str, factor_str)
                if left is None:
                    continue
                a = _money(amount_str)
                factor = Decimal(factor_str)
                assert left == factor * a

    def test_multiplication_by_one_is_identity(self) -> None:
        """a * 1 == a for every generated amount."""
        for amount_str in _AMOUNTS:
            assert _money(amount_str) * Decimal("1") == _money(amount_str)

    def test_multiplication_by_zero_is_zero(self) -> None:
        """a * 0 == 0 for every generated amount."""
        zero = _money("0.00")
        for amount_str in _AMOUNTS:
            assert _money(amount_str) * Decimal("0") == zero

    def test_arithmetic_preserves_quantization_for_sums(self) -> None:
        """Sum of quantized amounts stays quantized."""
        for a_str in _AMOUNTS:
            for b_str in _AMOUNTS:
                assert _is_quantized(_money(a_str) + _money(b_str))

    def test_multiplication_not_closed_under_quantization(self) -> None:
        """DEFECT: Money multiplication is not closed under quantization.

        ``Money.__mul__`` returns the raw product without quantizing to 4
        decimal places (unlike ``Money.convert`` which quantizes). As a
        result, multiplying a valid Money by a multi-place factor can raise
        ValidationError instead of returning a Money — e.g.
        ``Money(0.0001) * 3.5`` produces 0.00035 and is rejected. The
        operation should quantize its result to 4 decimal places.
        """
        with pytest.raises(ValidationError):
            _money("0.0001") * Decimal("3.5")
        with pytest.raises(ValidationError):
            _money("0.01") * Decimal("0.001")

    def test_currency_mismatch_raises_for_all_pairs(self) -> None:
        """Any arithmetic between USD and EUR raises CurrencyMismatchError."""
        usd = Money(amount=Decimal("1.00"), currency=CurrencyCode(code="USD"))
        eur = Money(amount=Decimal("1.00"), currency=CurrencyCode(code="EUR"))
        for op in ("add", "subtract", "compare"):
            raised = False
            try:
                if op == "add":
                    _ = usd + eur
                elif op == "subtract":
                    _ = usd - eur
                else:
                    _ = usd < eur
            except CurrencyMismatchError:
                raised = True
            assert raised, f"expected CurrencyMismatchError for {op}"


# =============================================================================
# FiscalPeriod arithmetic properties
# =============================================================================


class TestFiscalPeriodProperties:
    """Period arithmetic invariants over generated rollovers."""

    def test_next_inverts_prior_for_months(self) -> None:
        """(p + offset) + (-offset) == p for every generated month roll."""
        for year, month, offset, _, _ in _MONTH_ROLLS:
            p = FiscalPeriod(year=year, period=month, type="month")
            advanced = p + offset
            assert advanced + (-offset) == p

    def test_month_rollover_years(self) -> None:
        """Month addition rolls across year boundaries correctly."""
        for year, month, offset, expected_year, expected_month in _MONTH_ROLLS:
            p = FiscalPeriod(year=year, period=month, type="month")
            result = p + offset
            assert result.year == expected_year
            assert result.period == expected_month

    def test_quarter_rollover_years(self) -> None:
        """Quarter addition rolls across year boundaries correctly."""
        for year, quarter, offset, expected_year, expected_quarter in _QUARTER_ROLLS:
            p = FiscalPeriod(year=year, period=quarter, type="quarter")
            result = p + offset
            assert result.year == expected_year
            assert result.period == expected_quarter

    def test_prior_period_property(self) -> None:
        """p.prior_period.next_period == p for every valid period type."""
        valid_periods: list[tuple[str, int]] = [
            ("month", 1),
            ("month", 6),
            ("month", 12),
            ("quarter", 1),
            ("quarter", 2),
            ("quarter", 3),
            ("quarter", 4),
            ("year", 1),
        ]
        for year in (2025, 2026, 2027):
            for period_type, period in valid_periods:
                p = FiscalPeriod(year=year, period=period, type=period_type)
                assert p.prior_period.next_period == p

    def test_invalid_quarter_period_not_rejected(self) -> None:
        """DEFECT: quarter periods outside 1-4 are accepted.

        ``FiscalPeriod``'s period validator reads
        ``info.data.get("type", "month")`` to pick the range, but pydantic
        validates fields in declaration order (year, period, type) — so
        ``type`` is not yet available when ``period`` is validated and the
        default of "month" is used. As a result a quarter period of 6 or 12
        (which should be rejected as out of range) constructs successfully.
        """
        # 6 is outside the documented quarter range 1-4 yet constructs.
        q = FiscalPeriod(year=2026, period=6, type="quarter")
        assert q.period == 6
        # 12 is outside the documented quarter range yet constructs.
        q2 = FiscalPeriod(year=2026, period=12, type="quarter")
        assert q2.period == 12

    def test_invalid_year_period_not_rejected(self) -> None:
        """DEFECT: year periods other than 1 are accepted.

        The same validator ordering issue means a year period of 6 (which
        should be 1 by the documented contract) constructs successfully.
        """
        y = FiscalPeriod(year=2026, period=6, type="year")
        assert y.period == 6

    def test_string_round_trip(self) -> None:
        """Parsing period_str returns the same period."""
        for year in (2025, 2026, 2027):
            for period in (1, 3, 12):
                for period_type in ("month", "quarter", "year"):
                    if period_type == "quarter" and period == 12:
                        continue
                    if period_type == "year" and period != 1:
                        continue
                    p = FiscalPeriod(year=year, period=period, type=period_type)
                    assert FiscalPeriod.from_string(p.period_str) == p

    def test_ordering_is_total(self) -> None:
        """Periods order by (year, period) for every generated pair."""
        periods = [
            FiscalPeriod(year=y, period=m, type="month")
            for y in (2025, 2026)
            for m in (1, 6, 12)
        ]
        for i, p in enumerate(periods):
            for j, q in enumerate(periods):
                if i < j:
                    assert p < q
                elif i > j:
                    assert p > q
                else:
                    assert not (p < q) and not (p > q)


# =============================================================================
# Ledger balance properties
# =============================================================================


class TestLedgerBalanceProperties:
    """The trial-balance invariant holds for every generated balanced entry."""

    def test_every_generated_entry_is_balanced(self) -> None:
        """Any pair of equal dr/cr lines constructs and balances.

        ``JournalEntry`` enforces balance at construction (it exposes no
        ``is_balanced`` property), so a balanced pair must construct without
        raising and its debit total must equal its credit total.
        """
        for amount_str in _AMOUNTS:
            entry = JournalEntry(
                entry_id=f"JE-{amount_str}",
                entry_date=date(2026, 7, 15),
                description="property entry",
                lines=[
                    JournalLine(
                        account=GLAccountNumber(number="1010"),
                        debit=_money(amount_str),
                    ),
                    JournalLine(
                        account=GLAccountNumber(number="4010"),
                        credit=_money(amount_str),
                    ),
                ],
            )
            debit_total = sum(
                (line.debit.amount for line in entry.lines if line.debit is not None),
                Decimal("0"),
            )
            credit_total = sum(
                (line.credit.amount for line in entry.lines if line.credit is not None),
                Decimal("0"),
            )
            assert debit_total == credit_total

    def test_ledger_balances_for_all_generated_entries(self) -> None:
        """A ledger of balanced entries reports is_balanced True."""
        entries = [
            JournalEntry(
                entry_id=f"JE-{amount_str}",
                entry_date=date(2026, 7, 15),
                description="property entry",
                lines=[
                    JournalLine(
                        account=GLAccountNumber(number="1010"),
                        debit=_money(amount_str),
                    ),
                    JournalLine(
                        account=GLAccountNumber(number="4010"),
                        credit=_money(amount_str),
                    ),
                ],
            )
            for amount_str in _AMOUNTS
        ]
        ledger = GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=entries)
        assert ledger.is_balanced is True

    def test_every_unbalanced_entry_raises(self) -> None:
        """An entry whose dr and cr differ raises for every generated pair."""
        for a_str in _AMOUNTS:
            for b_str in _AMOUNTS:
                if a_str == b_str:
                    continue
                with pytest.raises(ValueError):
                    JournalEntry(
                        entry_id=f"JE-{a_str}-{b_str}",
                        entry_date=date(2026, 7, 15),
                        description="property entry",
                        lines=[
                            JournalLine(
                                account=GLAccountNumber(number="1010"),
                                debit=_money(a_str),
                            ),
                            JournalLine(
                                account=GLAccountNumber(number="4010"),
                                credit=_money(b_str),
                            ),
                        ],
                    )


# =============================================================================
# LineItem aggregation properties
# =============================================================================


class TestLineItemAggregationProperties:
    """Aggregation invariants over generated item trees."""

    def test_leaf_total_is_amount(self) -> None:
        """A leaf's total equals its amount for every generated amount."""
        for amount_str in _AMOUNTS:
            item = LineItem(label=f"L-{amount_str}", amount=_money(amount_str))
            assert item.total == _money(amount_str)

    def test_sum_of_leaf_amounts_equals_total(self) -> None:
        """Summing leaf amounts directly equals the computed total."""
        amounts = [Decimal(a) for a in _AMOUNTS]
        item = LineItem(
            label="Total",
            sub_items=[
                LineItem(label=f"L-{i}", amount=_money(a_str))
                for i, a_str in enumerate(_AMOUNTS)
            ],
        )
        expected = Money(
            amount=sum(amounts, Decimal("0")), currency=CurrencyCode(code="USD")
        )
        assert item.total == expected

    def test_nested_aggregation_matches_flat_aggregation(self) -> None:
        """Grouping leaves changes the tree but not the total."""
        amounts = ["10.00", "20.00", "30.00", "40.00"]
        flat = LineItem(
            label="Total",
            sub_items=[LineItem(label=f"L-{a}", amount=_money(a)) for a in amounts],
        )
        nested = LineItem(
            label="Total",
            sub_items=[
                LineItem(
                    label="Group-1",
                    sub_items=[LineItem(label=f"L-{a}", amount=_money(a)) for a in amounts[:2]],
                ),
                LineItem(
                    label="Group-2",
                    sub_items=[LineItem(label=f"L-{a}", amount=_money(a)) for a in amounts[2:]],
                ),
            ],
        )
        assert flat.total == nested.total