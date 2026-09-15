"""Tests for the General Ledger / Journal Entry domain models.

The ledger ontology (`business/ontology/ledger.py`) implements double-entry
bookkeeping: every ``JournalLine`` is exactly one side (debit XOR credit),
every ``JournalEntry`` must balance (total debits == total credits), and a
``GeneralLedger`` aggregates balanced entries for an entity and fiscal year.

All monetary values are ``decimal.Decimal`` via the ``Money`` value object.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from business.canonical_types import CurrencyCode, GLAccountNumber, Money
from business.ontology.ledger import GeneralLedger, JournalEntry, JournalLine


def _money(amount: str) -> Money:
    """Build a USD Money value object."""
    return Money(amount=Decimal(amount), currency=CurrencyCode(code="USD"))


def _debit(account: str, amount: str) -> JournalLine:
    """Build a debit journal line."""
    return JournalLine(account=GLAccountNumber(number=account), debit=_money(amount))


def _credit(account: str, amount: str) -> JournalLine:
    """Build a credit journal line."""
    return JournalLine(account=GLAccountNumber(number=account), credit=_money(amount))


def _balanced_entry(entry_id: str = "JE-001") -> JournalEntry:
    """Build a balanced two-line journal entry."""
    return JournalEntry(
        entry_id=entry_id,
        entry_date=date(2026, 7, 15),
        description="Record revenue",
        source="Sales System",
        lines=[
            _debit("1010", "1000.00"),
            _credit("4010", "1000.00"),
        ],
    )


# =============================================================================
# JournalLine
# =============================================================================


class TestJournalLine:
    """Single-side journal line invariants."""

    def test_debit_line_constructs(self) -> None:
        """A debit line constructs."""
        line = _debit("1010", "100.00")
        assert line.side == "debit"
        assert line.amount == _money("100.00")

    def test_credit_line_constructs(self) -> None:
        """A credit line constructs."""
        line = _credit("4010", "100.00")
        assert line.side == "credit"
        assert line.amount == _money("100.00")

    def test_default_description_empty(self) -> None:
        """A line description defaults to an empty string."""
        assert _debit("1010", "100.00").description == ""

    def test_both_debit_and_credit_rejected(self) -> None:
        """A line cannot be both debit and credit simultaneously."""
        with pytest.raises(ValueError, match="cannot have both"):
            JournalLine(
                account=GLAccountNumber(number="1010"),
                debit=_money("100.00"),
                credit=_money("100.00"),
            )

    def test_neither_debit_nor_credit_rejected(self) -> None:
        """A line must have exactly one side."""
        with pytest.raises(ValueError, match="either a debit or credit"):
            JournalLine(account=GLAccountNumber(number="1010"))

    def test_frozen_line(self) -> None:
        """Journal lines are immutable."""
        line = _debit("1010", "100.00")
        with pytest.raises(ValidationError):
            line.description = "changed"  # type: ignore[misc]

    def test_str_representation(self) -> None:
        """The string shows the account and side."""
        text = str(_debit("1010", "100.00"))
        assert "1010" in text
        assert "Dr" in text


# =============================================================================
# JournalEntry
# =============================================================================


class TestJournalEntry:
    """Double-entry balancing invariants."""

    def test_balanced_entry_constructs(self) -> None:
        """A balanced two-line entry constructs."""
        entry = _balanced_entry()
        assert entry.entry_id == "JE-001"
        assert entry.entry_date == date(2026, 7, 15)
        assert len(entry.lines) == 2

    def test_multi_line_balanced_entry(self) -> None:
        """An entry with multiple debits and credits balances."""
        entry = JournalEntry(
            entry_id="JE-002",
            entry_date=date(2026, 7, 15),
            description="Split payment",
            lines=[
                _debit("1010", "500.00"),
                _debit("1020", "500.00"),
                _credit("4010", "1000.00"),
            ],
        )
        assert len(entry.lines) == 3

    def test_unbalanced_entry_rejected(self) -> None:
        """An entry whose debits do not equal credits is rejected."""
        with pytest.raises(ValueError, match="not balanced"):
            JournalEntry(
                entry_id="JE-003",
                entry_date=date(2026, 7, 15),
                description="Unbalanced",
                lines=[
                    _debit("1010", "1000.00"),
                    _credit("4010", "900.00"),
                ],
            )

    def test_single_line_rejected(self) -> None:
        """A single-line entry violates double-entry bookkeeping."""
        with pytest.raises(ValueError, match="at least two lines"):
            JournalEntry(
                entry_id="JE-004",
                entry_date=date(2026, 7, 15),
                description="Single line",
                lines=[_debit("1010", "100.00")],
            )

    def test_empty_lines_rejected(self) -> None:
        """An entry with no lines is rejected."""
        with pytest.raises(ValueError, match="at least one line"):
            JournalEntry(
                entry_id="JE-005",
                entry_date=date(2026, 7, 15),
                description="Empty",
                lines=[],
            )

    def test_all_debits_rejected(self) -> None:
        """An entry with only debit lines is rejected (no credits)."""
        with pytest.raises(ValueError, match="both debit and credit"):
            JournalEntry(
                entry_id="JE-006",
                entry_date=date(2026, 7, 15),
                description="All debits",
                lines=[
                    _debit("1010", "100.00"),
                    _debit("1020", "100.00"),
                ],
            )

    def test_all_credits_rejected(self) -> None:
        """An entry with only credit lines is rejected (no debits)."""
        with pytest.raises(ValueError, match="both debit and credit"):
            JournalEntry(
                entry_id="JE-007",
                entry_date=date(2026, 7, 15),
                description="All credits",
                lines=[
                    _credit("4010", "100.00"),
                    _credit("4020", "100.00"),
                ],
            )

    def test_mixed_currency_rejected(self) -> None:
        """Lines in different currencies are rejected."""
        eur = Money(amount=Decimal("100.00"), currency=CurrencyCode(code="EUR"))
        with pytest.raises(ValueError, match="same currency"):
            JournalEntry(
                entry_id="JE-008",
                entry_date=date(2026, 7, 15),
                description="Mixed currency",
                lines=[
                    _debit("1010", "100.00"),
                    JournalLine(account=GLAccountNumber(number="4010"), credit=eur),
                ],
            )

    def test_empty_entry_id_rejected(self) -> None:
        """An empty entry id is rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            JournalEntry(
                entry_id="",
                entry_date=date(2026, 7, 15),
                description="No id",
                lines=[
                    _debit("1010", "100.00"),
                    _credit("4010", "100.00"),
                ],
            )

    def test_frozen_entry(self) -> None:
        """Journal entries are immutable."""
        entry = _balanced_entry()
        with pytest.raises(ValidationError):
            entry.description = "changed"  # type: ignore[misc]

    def test_str_representation(self) -> None:
        """The string summarizes the entry."""
        text = str(_balanced_entry())
        assert "JE-001" in text
        assert "2 lines" in text


# =============================================================================
# GeneralLedger
# =============================================================================


class TestGeneralLedger:
    """General ledger aggregation invariants."""

    def test_valid_ledger_constructs(self) -> None:
        """A ledger with entries constructs."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[_balanced_entry()],
        )
        assert ledger.entity_id == "US-CORP"
        assert ledger.fiscal_year == 2026
        assert ledger.entry_count == 1

    def test_empty_ledger_is_balanced(self) -> None:
        """An empty ledger is vacuously balanced."""
        ledger = GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=[])
        assert ledger.is_balanced is True

    def test_balanced_ledger_is_balanced(self) -> None:
        """A ledger of balanced entries is balanced."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[_balanced_entry(), _balanced_entry("JE-002")],
        )
        assert ledger.is_balanced is True

    def test_empty_entity_id_rejected(self) -> None:
        """An empty entity id is rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            GeneralLedger(entity_id="", fiscal_year=2026, entries=[])

    def test_fiscal_year_out_of_range_rejected(self) -> None:
        """A fiscal year outside 1900-2100 is rejected."""
        with pytest.raises(ValueError, match="out of range"):
            GeneralLedger(entity_id="US-CORP", fiscal_year=1899, entries=[])

    def test_fiscal_year_upper_bound_rejected(self) -> None:
        """A fiscal year above 2100 is rejected."""
        with pytest.raises(ValueError, match="out of range"):
            GeneralLedger(entity_id="US-CORP", fiscal_year=2101, entries=[])

    def test_fiscal_year_boundary_accepted(self) -> None:
        """Fiscal years at the inclusive bounds are accepted."""
        assert GeneralLedger(entity_id="US-CORP", fiscal_year=1900, entries=[]).fiscal_year == 1900
        assert GeneralLedger(entity_id="US-CORP", fiscal_year=2100, entries=[]).fiscal_year == 2100

    def test_entries_for_account(self) -> None:
        """entries_for_account returns lines referencing a GL account."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[_balanced_entry()],
        )
        lines = ledger.entries_for_account(GLAccountNumber(number="1010"))
        assert len(lines) == 1
        assert lines[0].side == "debit"

    def test_entries_for_unknown_account_empty(self) -> None:
        """entries_for_account returns an empty list for unknown accounts."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[_balanced_entry()],
        )
        assert ledger.entries_for_account(GLAccountNumber(number="9999")) == []

    def test_frozen_ledger(self) -> None:
        """General ledgers are immutable."""
        ledger = GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=[])
        with pytest.raises(ValidationError):
            ledger.entity_id = "UK-CORP"  # type: ignore[misc]

    def test_str_representation(self) -> None:
        """The ledger string summarizes entity and entry count."""
        text = str(GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=[]))
        assert "US-CORP" in text
        assert "FY2026" in text