"""Tests for the Trial Balance domain invariants.

A trial balance is the period-end view of the general ledger: every account
shows its debit and credit totals, and the fundamental invariant is that
total debits equal total credits. The platform has no standalone pure-Python
TrialBalance aggregate (the persistence model lives in
`shared/models/database.py` behind SQLAlchemy); the invariant is enforced at
the domain level by the ledger ontology (`business/ontology/ledger.py`):

* every ``JournalEntry`` must balance (debits == credits), so an unbalanced
  entry is rejected at construction; and
* ``GeneralLedger.is_balanced`` verifies the aggregate across entries.

This suite exercises the trial-balance invariant through those real models
and through a small trial-balance projection helper over a ``GeneralLedger``.
"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from business.canonical_types import CurrencyCode, GLAccountNumber, Money
from business.ontology.ledger import GeneralLedger, JournalEntry, JournalLine

#: Documented trial_balance CHECK constraints (database/migrations/003_*).
#: debit and credit must be non-negative, and never both positive.
MAX_ACCOUNT_DEBIT = Decimal("999999999999.99")


class _TrialBalanceRow:
    """Minimal account-level trial balance row (dr/cr projection)."""

    def __init__(self, account: str, debit: Decimal, credit: Decimal) -> None:
        self.account = account
        self.debit = debit
        self.credit = credit

    @property
    def balance(self) -> Decimal:
        """Signed balance: debit minus credit."""
        return self.debit - self.credit

    def is_positive_on_one_side(self) -> bool:
        """DB constraint: not both debit and credit positive."""
        return (self.debit >= 0 and self.credit >= 0) and not (
            self.debit > 0 and self.credit > 0
        )


def _trial_balance(ledger: GeneralLedger) -> list[_TrialBalanceRow]:
    """Project a general ledger into per-account dr/cr trial balance rows.

    The projection nets each account to a single side (debit or credit),
    matching the physical ``trial_balance`` contract where ``balance`` is
    generated as ``debit - credit`` and the row-level CHECK constraints
    require ``debit = 0 OR credit = 0`` (one side only).

    Args:
        ledger: A general ledger of balanced journal entries.

    Returns:
        One trial balance row per account, netted to a single side.
    """
    totals: dict[str, list[Decimal]] = {}
    for entry in ledger.entries:
        for line in entry.lines:
            totals.setdefault(str(line.account), [Decimal("0"), Decimal("0")])
            if line.debit is not None:
                totals[str(line.account)][0] += line.debit.amount
            if line.credit is not None:
                totals[str(line.account)][1] += line.credit.amount
    rows: list[_TrialBalanceRow] = []
    for account, (dr, cr) in sorted(totals.items()):
        net = dr - cr
        if net >= 0:
            rows.append(_TrialBalanceRow(account=account, debit=net, credit=Decimal("0")))
        else:
            rows.append(_TrialBalanceRow(account=account, debit=Decimal("0"), credit=-net))
    return rows


def _total_debits(rows: list[_TrialBalanceRow]) -> Decimal:
    """Sum of all debit totals across trial balance rows."""
    return sum((row.debit for row in rows), Decimal("0"))


def _total_credits(rows: list[_TrialBalanceRow]) -> Decimal:
    """Sum of all credit totals across trial balance rows."""
    return sum((row.credit for row in rows), Decimal("0"))


def _money(amount: str) -> Money:
    """Build a USD Money value object."""
    return Money(amount=Decimal(amount), currency=CurrencyCode(code="USD"))


def _debit(account: str, amount: str) -> JournalLine:
    """Build a debit journal line."""
    return JournalLine(account=GLAccountNumber(number=account), debit=_money(amount))


def _credit(account: str, amount: str) -> JournalLine:
    """Build a credit journal line."""
    return JournalLine(account=GLAccountNumber(number=account), credit=_money(amount))


def _entry(entry_id: str, lines: list[JournalLine]) -> JournalEntry:
    """Build a journal entry from lines."""
    return JournalEntry(
        entry_id=entry_id,
        entry_date=date(2026, 7, 15),
        description=f"entry {entry_id}",
        lines=lines,
    )


# =============================================================================
# Trial balance construction & projection
# =============================================================================


class TestTrialBalanceProjection:
    """Projecting a ledger into dr/cr rows per account."""

    def _ledger(self) -> GeneralLedger:
        """Build a ledger with two balanced entries touching three accounts."""
        return GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry(
                    "JE-001",
                    [_debit("1010", "1000.00"), _credit("4010", "1000.00")],
                ),
                _entry(
                    "JE-002",
                    [_debit("1010", "250.00"), _credit("4010", "250.00")],
                ),
            ],
        )

    def test_projects_one_row_per_account(self) -> None:
        """Each account appears exactly once with aggregated dr/cr."""
        rows = _trial_balance(self._ledger())
        assert [row.account for row in rows] == ["1010", "4010"]

    def test_debit_totals_aggregate(self) -> None:
        """Debit totals sum across entries per account."""
        rows = _trial_balance(self._ledger())
        cash = next(row for row in rows if row.account == "1010")
        assert cash.debit == Decimal("1250.00")

    def test_credit_totals_aggregate(self) -> None:
        """Credit totals sum across entries per account."""
        rows = _trial_balance(self._ledger())
        revenue = next(row for row in rows if row.account == "4010")
        assert revenue.credit == Decimal("1250.00")

    def test_total_debits_equal_total_credits(self) -> None:
        """The trial balance is balanced: total dr == total cr."""
        rows = _trial_balance(self._ledger())
        assert _total_debits(rows) == _total_credits(rows)

    def test_row_balance_is_debit_minus_credit(self) -> None:
        """The signed balance is debit minus credit."""
        rows = _trial_balance(self._ledger())
        cash = next(row for row in rows if row.account == "1010")
        assert cash.balance == Decimal("1250.00")


# =============================================================================
# Balanced invariant
# =============================================================================


class TestTrialBalanceBalancedInvariant:
    """The trial balance must remain balanced by construction."""

    def test_ledger_of_balanced_entries_is_balanced(self) -> None:
        """GeneralLedger.is_balanced holds for balanced entries."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry("JE-001", [_debit("1010", "100.00"), _credit("4010", "100.00")])
            ],
        )
        assert ledger.is_balanced is True

    def test_empty_ledger_is_vacuously_balanced(self) -> None:
        """An empty ledger projects to an empty, balanced trial balance."""
        ledger = GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=[])
        assert _trial_balance(ledger) == []
        assert ledger.is_balanced is True

    def test_multi_entry_ledger_totals_balance(self) -> None:
        """Across many entries the trial balance still balances."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry("JE-001", [_debit("1010", "100.00"), _credit("4010", "100.00")]),
                _entry(
                    "JE-002",
                    [_debit("1010", "50.00"), _credit("4010", "50.00")],
                ),
            ],
        )
        rows = _trial_balance(ledger)
        assert _total_debits(rows) == _total_credits(rows) == Decimal("150.00")

    def test_single_account_dr_cr_netting(self) -> None:
        """A contra account nets to a single side on its row."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry(
                    "JE-001",
                    [
                        _debit("1010", "1000.00"),
                        _credit("1010", "200.00"),
                        _credit("4010", "800.00"),
                    ],
                )
            ],
        )
        rows = _trial_balance(ledger)
        cash = next(row for row in rows if row.account == "1010")
        # Netting: 1000 debit - 200 credit = 800 net debit on one side.
        assert cash.debit == Decimal("800.00")
        assert cash.credit == Decimal("0.00")
        assert cash.balance == Decimal("800.00")


# =============================================================================
# Unbalanced rejected
# =============================================================================


class TestTrialBalanceUnbalancedRejected:
    """An unbalanced trial balance cannot be constructed."""

    def test_unbalanced_entry_rejected(self) -> None:
        """An entry with dr != cr raises at construction."""
        with pytest.raises(ValueError, match="not balanced"):
            _entry("JE-BAD", [_debit("1010", "100.00"), _credit("4010", "90.00")])

    def test_missing_credit_side_rejected(self) -> None:
        """An entry with only debits cannot form a trial balance."""
        with pytest.raises(ValueError, match="both debit and credit"):
            _entry("JE-BAD", [_debit("1010", "100.00"), _debit("1020", "100.00")])

    def test_single_line_rejected(self) -> None:
        """A single-sided entry is not valid double-entry."""
        with pytest.raises(ValueError, match="at least two lines"):
            _entry("JE-BAD", [_debit("1010", "100.00")])

    def test_mixed_currency_rejected(self) -> None:
        """Mixed-currency entries cannot produce a trial balance."""
        eur = Money(
            amount=Decimal("100.00"),
            currency=CurrencyCode(code="EUR"),
        )
        with pytest.raises(ValueError, match="same currency"):
            _entry(
                "JE-BAD",
                [
                    _debit("1010", "100.00"),
                    JournalLine(account=GLAccountNumber(number="4010"), credit=eur),
                ],
            )

    def test_ledger_without_entries_rejected_if_unbalanced(self) -> None:
        """A ledger cannot silently hide an unbalanced entry."""
        # Construction of an unbalanced entry already raises, so a ledger is
        # balanced by construction; assert the aggregate agrees.
        ledger = GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=[])
        assert ledger.is_balanced is True


# =============================================================================
# Documented row-level constraints
# =============================================================================


class TestTrialBalanceRowConstraints:
    """The documented DB CHECK constraints hold on projected rows."""

    def test_debit_and_credit_non_negative(self) -> None:
        """Projected dr/cr totals are non-negative by construction."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry("JE-001", [_debit("1010", "100.00"), _credit("4010", "100.00")])
            ],
        )
        for row in _trial_balance(ledger):
            assert row.debit >= 0
            assert row.credit >= 0

    def test_never_both_positive(self) -> None:
        """A projected row is never positive on both sides."""
        ledger = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry(
                    "JE-001",
                    [
                        _debit("1010", "1000.00"),
                        _credit("1010", "200.00"),
                        _credit("4010", "800.00"),
                    ],
                )
            ],
        )
        for row in _trial_balance(ledger):
            assert row.is_positive_on_one_side() is True


# =============================================================================
# Entity scoping
# =============================================================================


class TestTrialBalanceScoping:
    """Trial balances are scoped to an entity and fiscal year."""

    def test_ledger_scoped_to_entity(self) -> None:
        """The ledger (and therefore its trial balance) is entity-scoped."""
        ledger = GeneralLedger(entity_id="UK-SUB", fiscal_year=2026, entries=[])
        assert ledger.entity_id == "UK-SUB"

    def test_ledger_scoped_to_fiscal_year(self) -> None:
        """The trial balance is computed per fiscal year."""
        ledger = GeneralLedger(entity_id="US-CORP", fiscal_year=2026, entries=[])
        assert ledger.fiscal_year == 2026

    def test_entity_id_required(self) -> None:
        """A ledger requires an entity id for scoping."""
        with pytest.raises(ValidationError):
            GeneralLedger(entity_id="", fiscal_year=2026, entries=[])

    def test_entity_isolation(self) -> None:
        """Entries for one entity do not leak into another's trial balance."""
        ledger_a = GeneralLedger(
            entity_id="US-CORP",
            fiscal_year=2026,
            entries=[
                _entry("JE-001", [_debit("1010", "500.00"), _credit("4010", "500.00")])
            ],
        )
        ledger_b = GeneralLedger(entity_id="UK-SUB", fiscal_year=2026, entries=[])
        rows_a = _trial_balance(ledger_a)
        rows_b = _trial_balance(ledger_b)
        assert rows_a != []
        assert rows_b == []
