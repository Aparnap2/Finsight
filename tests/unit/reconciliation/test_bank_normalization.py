"""Bank statement normalization: declared mapping, Decimal money, rejects.

Covers the tenant boundary (the file can never reassign ownership), minor
unit quantization per currency (JPY 0, BHD 3, override), over-precision
rejection (never rounding), debit rows counted rather than imported, and
re-import deduplication by economic fingerprint.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.reconciliation.bank import (
    AmountUnit,
    BankDepositRecord,
    BankIngestResult,
    BankStatementMapping,
    RejectReason,
    SignConvention,
    ensure_unique_deposits,
    fingerprint_deposit,
    normalize_bank_statement,
)
from finance.reconciliation.errors import (
    DuplicateError,
    FloatMoneyError,
    InvariantViolation,
)

_DIGEST = "a" * 64
_TENANT = "tenant-acme"


def _row(**overrides: object) -> dict[str, object]:
    """Build one valid statement row, overriding any cell."""
    row: dict[str, object] = {
        "deposit_id": "dep_1001",
        "amount": "1,970.00",
        "posted_at": "2026-05-02",
        "account": "acct-9",
        "reference": "payout-1",
        "description": "weekly payout",
    }
    row.update(overrides)
    return row


def _ingest(
    rows: list[dict[str, object]],
    mapping: BankStatementMapping | None = None,
) -> BankIngestResult:
    """Normalize rows under a default USD MAJOR mapping."""
    return normalize_bank_statement(
        rows,
        mapping or BankStatementMapping(statement_currency="USD"),
        tenant_id=_TENANT,
        statement_digest=_DIGEST,
    )


class TestMapping:
    """Mapping declaration is validated before any row is read."""

    def test_exponent_follows_currency_minor_units(self) -> None:
        assert BankStatementMapping(statement_currency="JPY").exponent() == 0
        assert BankStatementMapping(statement_currency="usd").exponent() == 2
        assert BankStatementMapping(statement_currency="BHD").exponent() == 3

    def test_exponent_override_is_validated(self) -> None:
        mapping = BankStatementMapping(statement_currency="USD", minor_unit_override=2)
        assert mapping.exponent() == 2
        with pytest.raises(InvariantViolation):
            BankStatementMapping(statement_currency="USD", minor_unit_override=-1)
        with pytest.raises(InvariantViolation):
            BankStatementMapping(statement_currency="USD", minor_unit_override=True)

    def test_invalid_currency_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            BankStatementMapping(statement_currency="US")

    def test_columns_must_be_distinct(self) -> None:
        with pytest.raises(InvariantViolation):
            BankStatementMapping(statement_currency="USD", reference_column="amount")

    def test_debit_credit_requires_credit_column(self) -> None:
        with pytest.raises(InvariantViolation):
            BankStatementMapping(
                statement_currency="USD", sign_convention=SignConvention.DEBIT_CREDIT
            )
        mapping = BankStatementMapping(
            statement_currency="USD",
            sign_convention=SignConvention.DEBIT_CREDIT,
            credit_column="credit",
            debit_column="debit",
        )
        assert mapping.sign_convention is SignConvention.DEBIT_CREDIT

    def test_digest_is_stable_and_sensitive(self) -> None:
        first = BankStatementMapping(statement_currency="USD")
        second = BankStatementMapping(statement_currency="USD")
        other = BankStatementMapping(statement_currency="USD", date_format="%d/%m/%Y")
        assert first.digest() == second.digest()
        assert first.digest() != other.digest()


class TestIngest:
    """Rows are converted, refused, or counted -- never silently coerced."""

    def test_happy_path_parses_money_and_date(self) -> None:
        result = _ingest([_row()])
        assert len(result.deposits) == 1
        deposit = result.deposits[0]
        assert deposit.amount == Decimal("1970.00")
        assert deposit.tenant_id == _TENANT
        assert deposit.line_number == 2
        assert deposit.posted_at == datetime(2026, 5, 2, tzinfo=UTC)
        assert result.rejects == ()
        assert result.skipped_debits == 0
        assert result.mapping_digest == BankStatementMapping(statement_currency="USD").digest()

    def test_file_tenant_column_cannot_reassign_ownership(self) -> None:
        result = _ingest([_row(tenant_id="tenant-attacker")])
        assert result.deposits[0].tenant_id == _TENANT

    def test_debit_rows_are_skipped_and_counted(self) -> None:
        result = _ingest([_row(amount="-20.00"), _row(deposit_id="dep_2")])
        assert result.skipped_debits == 1
        assert result.rejects == ()
        assert [deposit.deposit_id for deposit in result.deposits] == ["dep_2"]

    def test_zero_amount_is_rejected_not_skipped(self) -> None:
        result = _ingest([_row(amount="0.00")])
        assert result.skipped_debits == 0
        assert [reject.reason for reject in result.rejects] == [RejectReason.INVALID_AMOUNT]

    def test_over_precision_is_rejected_not_rounded(self) -> None:
        result = _ingest([_row(amount="10.001")])
        assert [reject.reason for reject in result.rejects] == [RejectReason.OVER_PRECISION]
        assert result.deposits == ()

    def test_currency_minor_units_are_enforced(self) -> None:
        jpy = _ingest([_row(amount="1000.5")], BankStatementMapping(statement_currency="JPY"))
        assert [reject.reason for reject in jpy.rejects] == [RejectReason.OVER_PRECISION]
        bhd = _ingest([_row(amount="1.2345")], BankStatementMapping(statement_currency="BHD"))
        assert [reject.reason for reject in bhd.rejects] == [RejectReason.OVER_PRECISION]
        bhd_ok = _ingest([_row(amount="1.234")], BankStatementMapping(statement_currency="BHD"))
        assert bhd_ok.deposits[0].amount == Decimal("1.234")

    def test_minor_unit_amounts_are_scaled(self) -> None:
        mapping = BankStatementMapping(statement_currency="USD", amount_unit=AmountUnit.MINOR)
        result = _ingest([_row(amount=197000)], mapping)
        assert result.deposits[0].amount == Decimal("1970.00")

    def test_row_currency_must_agree_with_statement(self) -> None:
        mapping = BankStatementMapping(statement_currency="USD", currency_column="currency")
        result = _ingest([_row(currency="EUR")], mapping)
        assert [reject.reason for reject in result.rejects] == [RejectReason.CURRENCY_MISMATCH]

    def test_missing_and_unparseable_cells_are_reported_with_line_numbers(self) -> None:
        rows = [_row(), _row(deposit_id=""), _row(posted_at="not-a-date"), _row(amount="abc")]
        result = _ingest(rows)
        assert [(reject.line_number, reject.reason) for reject in result.rejects] == [
            (3, RejectReason.MISSING_FIELD),
            (4, RejectReason.INVALID_DATE),
            (5, RejectReason.INVALID_AMOUNT),
        ]

    def test_float_money_is_refused(self) -> None:
        with pytest.raises(FloatMoneyError):
            _ingest([_row(amount=10.5)])

    def test_reingest_is_deterministic_and_deduplicated(self) -> None:
        rows = [_row(), _row()]
        first = _ingest(rows)
        second = _ingest(list(rows))
        assert len(first.deposits) == 1
        assert len(first.duplicates) == 1
        assert fingerprint_deposit(first.deposits[0]) == fingerprint_deposit(second.deposits[0])

    def test_ensure_unique_deposits_raises_on_repeats(self) -> None:
        deposit = _ingest([_row()]).deposits[0]
        ensure_unique_deposits([deposit])
        with pytest.raises(DuplicateError):
            ensure_unique_deposits([deposit, deposit])

    def test_bad_envelope_inputs_raise(self) -> None:
        mapping = BankStatementMapping(statement_currency="USD")
        with pytest.raises(InvariantViolation):
            normalize_bank_statement([], mapping, tenant_id="", statement_digest=_DIGEST)
        with pytest.raises(InvariantViolation):
            normalize_bank_statement([], mapping, tenant_id=_TENANT, statement_digest="short")
        with pytest.raises(InvariantViolation):
            normalize_bank_statement(
                ["not-a-row"],  # type: ignore[list-item]
                mapping,
                tenant_id=_TENANT,
                statement_digest=_DIGEST,
            )

    def test_deposit_fingerprint_is_provenance_independent(self) -> None:
        base = _ingest([_row()]).deposits[0]
        moved = BankDepositRecord(
            deposit_id=base.deposit_id,
            tenant_id=base.tenant_id,
            amount=base.amount,
            currency=base.currency,
            posted_at=base.posted_at,
            statement_digest="b" * 64,
            line_number=99,
            account_reference=base.account_reference,
            reference=base.reference,
        )
        assert fingerprint_deposit(moved) == fingerprint_deposit(base)
