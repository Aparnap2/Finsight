"""General ledger and journal entry ontology models.

Represents accounting primitives: journal entries with balanced
debit/credit lines, and the general ledger as a collection of entries.
"""

# mypy: disable-error-code="misc,untyped-decorator"

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from business.canonical_types import GLAccountNumber, Money


class JournalLine(BaseModel):
    """A single line item in a journal entry.

    Each line represents either a debit or a credit to a specific
    GL account. A line cannot be both debit and credit simultaneously.

    Usage:
        line = JournalLine(
            account=GLAccountNumber("1010"),
            debit=Money(Decimal("1000.00"), CurrencyCode("USD")),
        )
    """

    model_config = ConfigDict(frozen=True)

    account: GLAccountNumber
    description: str = ""
    debit: Money | None = None
    credit: Money | None = None

    @model_validator(mode="after")
    def _check_single_side(self) -> JournalLine:
        """Ensure the line has exactly one side: debit XOR credit."""
        has_debit = self.debit is not None
        has_credit = self.credit is not None
        if has_debit and has_credit:
            raise ValueError(
                "Journal line cannot have both debit and credit amounts"
            )
        if not has_debit and not has_credit:
            raise ValueError(
                "Journal line must have either a debit or credit amount"
            )
        return self

    @property
    def amount(self) -> Money:
        """The monetary amount of this line (debit or credit)."""
        if self.debit is not None:
            return self.debit
        if self.credit is not None:
            return self.credit
        raise ValueError("Journal line has no amount")

    @property
    def side(self) -> str:
        """The side of this entry: 'debit' or 'credit'."""
        if self.debit is not None:
            return "debit"
        return "credit"

    def __str__(self) -> str:
        amt = self.debit if self.debit is not None else self.credit
        side_str = "Dr" if self.debit is not None else "Cr"
        desc = f" - {self.description}" if self.description else ""
        return f"{self.account}: {side_str} {amt}{desc}"


class JournalEntry(BaseModel):
    """An accounting journal entry with balanced debits and credits.

    Journal entries are the fundamental building blocks of the general
    ledger. Every entry must have at least two lines (double-entry
    bookkeeping) with total debits equal to total credits.

    Usage:
        entry = JournalEntry(
            entry_id="JE-2026-001",
            entry_date=date(2026, 7, 15),
            description="Record revenue for July 2026",
            source="Sales System",
            lines=[
                JournalLine(account=GLAccountNumber("4010"), credit=revenue),
                JournalLine(account=GLAccountNumber("1010"), debit=revenue),
            ],
        )
    """

    model_config = ConfigDict(frozen=True)

    entry_id: str
    entry_date: date
    description: str
    source: str = ""
    lines: list[JournalLine] = []

    @field_validator("entry_id")
    @classmethod
    def _validate_entry_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Journal entry ID cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def _check_balanced(self) -> JournalEntry:
        """Verify that total debits equal total credits."""
        if not self.lines:
            raise ValueError("Journal entry must have at least one line")
        if len(self.lines) < 2:
            raise ValueError(
                "Journal entry must have at least two lines "
                "(double-entry bookkeeping)"
            )
        total_debits: Money | None = None
        total_credits: Money | None = None
        reference_currency: str | None = None

        for line in self.lines:
            line_amount = line.debit if line.debit is not None else line.credit
            if line_amount is None:
                continue
            curr = str(line_amount.currency)
            if reference_currency is None:
                reference_currency = curr
            elif curr != reference_currency:
                raise ValueError(
                    f"Journal entry lines must use the same currency: "
                    f"found {curr} and {reference_currency}"
                )
            if line.debit is not None:
                total_debits = (
                    total_debits + line.debit
                    if total_debits is not None
                    else line.debit
                )
            if line.credit is not None:
                total_credits = (
                    total_credits + line.credit
                    if total_credits is not None
                    else line.credit
                )

        if total_debits is None or total_credits is None:
            raise ValueError("Journal entry must have both debit and credit lines")

        if total_debits.amount != total_credits.amount:
            raise ValueError(
                f"Journal entry is not balanced: "
                f"debits={total_debits.amount} != credits={total_credits.amount}"
            )
        return self

    def __str__(self) -> str:
        return (
            f"JournalEntry({self.entry_id}, {self.entry_date}, "
            f"{len(self.lines)} lines)"
        )


class GeneralLedger(BaseModel):
    """A general ledger containing journal entries for an entity.

    The general ledger is the central repository of accounting data,
    containing all journal entries posted for a specific entity.

    Usage:
        gl = GeneralLedger(
            entity_id=EntityId("US-CORP"),
            fiscal_year=2026,
            entries=[entry1, entry2],
        )
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str
    fiscal_year: int
    entries: list[JournalEntry] = []

    @field_validator("entity_id")
    @classmethod
    def _validate_entity_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Entity ID cannot be empty")
        return v.strip()

    @field_validator("fiscal_year")
    @classmethod
    def _validate_fiscal_year(cls, v: int) -> int:
        if v < 1900 or v > 2100:
            raise ValueError(f"Fiscal year out of range: {v}")
        return v

    @property
    def entry_count(self) -> int:
        """Number of journal entries in the ledger."""
        return len(self.entries)

    @property
    def is_balanced(self) -> bool:
        """Check whether the general ledger is fully balanced.

        The sum of all debit entries must equal the sum of all credit
        entries across all journal entries.
        """
        total_debits: Money | None = None
        total_credits: Money | None = None

        for entry in self.entries:
            for line in entry.lines:
                if line.debit is not None:
                    total_debits = (
                        total_debits + line.debit
                        if total_debits is not None
                        else line.debit
                    )
                if line.credit is not None:
                    total_credits = (
                        total_credits + line.credit
                        if total_credits is not None
                        else line.credit
                    )

        if total_debits is None or total_credits is None:
            return True  # Empty ledger is vacuously balanced
        return (
            total_debits.currency == total_credits.currency
            and total_debits.amount == total_credits.amount
        )

    def entries_for_account(self, account: GLAccountNumber) -> list[JournalLine]:
        """Find all journal lines referencing a specific GL account.

        Args:
            account: The GL account number to search for.

        Returns:
            A list of JournalLine objects referencing that account.
        """
        result: list[JournalLine] = []
        for entry in self.entries:
            for line in entry.lines:
                if line.account == account:
                    result.append(line)
        return result

    def __str__(self) -> str:
        return (
            f"GeneralLedger({self.entity_id}, FY{self.fiscal_year}, "
            f"{len(self.entries)} entries)"
        )
