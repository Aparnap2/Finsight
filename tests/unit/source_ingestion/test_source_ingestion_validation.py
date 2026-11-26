"""Source ingestion: refusal behavior and the no-silent-drop guarantee.

Every malformed input must produce a specific, actionable refusal at the
right physical line, and no financial row may disappear without a trace.
Envelope failures raise :class:`IngestionError` with the frozen API code;
row failures are reported on the report with a stable reason code.

Expected outcomes are the specified catalog codes and explicit boundary
values, not whatever the implementation happens to emit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from finance.reconciliation.bank import BankStatementMapping
from finance.reconciliation.models import PaymentRecord
from finance.source_ingestion import (
    ApiErrorCode,
    IngestionError,
    IngestionReport,
    IssueCode,
    SourceType,
    ingest_source,
)

TENANT = "tenant-acme"

INVOICE_HEADER = "invoice_id,amount,currency,issued_at\n"
BANK_HEADER = "deposit_id,amount,posted_at\n"


def _invoice(body: str, *, header: str = INVOICE_HEADER) -> IngestionReport:
    """Ingest an invoice CSV with the canonical header."""
    return ingest_source(
        header + body,
        source_type=SourceType.INVOICE,
        tenant_id=TENANT,
    )


def _payment(report: IngestionReport) -> PaymentRecord:
    """Return the first accepted record, asserting it is a payment leg."""
    record = report.records[0].record
    assert isinstance(record, PaymentRecord)
    return record


def _bank(body: str) -> IngestionReport:
    """Ingest a bank CSV with the canonical header and a declared currency."""
    return ingest_source(
        BANK_HEADER + body,
        source_type=SourceType.BANK,
        tenant_id=TENANT,
        statement_currency="USD",
    )


class TestEnvelopeFailures:
    """File-level failures raise with the frozen API error code."""

    def test_empty_source_is_invalid_file(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source("", source_type=SourceType.INVOICE, tenant_id=TENANT)

        assert caught.value.code is ApiErrorCode.INVALID_FILE

    def test_whitespace_only_source_is_invalid_file(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source("  \n\t\n", source_type=SourceType.INVOICE, tenant_id=TENANT)

        assert caught.value.code is ApiErrorCode.INVALID_FILE

    def test_header_without_data_rows_is_invalid_file(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(INVOICE_HEADER, source_type=SourceType.INVOICE, tenant_id=TENANT)

        assert caught.value.code is ApiErrorCode.INVALID_FILE

    def test_undecodable_bytes_are_invalid_file(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                b"invoice_id,amount\n\xff\xfe,1.00\n",
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
            )

        assert caught.value.code is ApiErrorCode.INVALID_FILE

    def test_unknown_encoding_is_invalid_file(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                (INVOICE_HEADER + "INV-1,1.00,USD,2026-01-02\n").encode("utf-8"),
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
                encoding="not-a-codec",
            )

        assert caught.value.code is ApiErrorCode.INVALID_FILE

    def test_unsupported_transport_is_invalid_file(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                INVOICE_HEADER + "INV-1,1.00,USD,2026-01-02\n",
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
                source_format="xlsx",
            )

        assert caught.value.code is ApiErrorCode.INVALID_FILE

    def test_missing_required_columns_are_invalid_schema(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                "amount,currency\n10.00,USD\n",
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
            )

        assert caught.value.code is ApiErrorCode.INVALID_SCHEMA
        assert caught.value.missing_columns == ("invoice_id", "issued_at")
        assert caught.value.found_columns == ("amount", "currency")

    def test_blank_header_cell_is_invalid_schema(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                "invoice_id,,currency,issued_at\nINV-1,x,USD,2026-01-02\n",
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
            )

        assert caught.value.code is ApiErrorCode.INVALID_SCHEMA

    def test_duplicate_header_columns_are_invalid_schema(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                "invoice_id,amount,currency,issued_at,Amount\nINV-1,10.00,USD,2026-01-02,10.00\n",
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
            )

        assert caught.value.code is ApiErrorCode.INVALID_SCHEMA

    def test_two_aliases_for_one_field_are_invalid_schema(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                "invoice_id,invoice_number,amount,currency,issued_at\n"
                "INV-1,INV-1,10.00,USD,2026-01-02\n",
                source_type=SourceType.INVOICE,
                tenant_id=TENANT,
            )

        assert caught.value.code is ApiErrorCode.INVALID_SCHEMA

    def test_bank_source_without_declared_currency_is_invalid_schema(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                BANK_HEADER + "dep_1,10.00,2026-01-04\n",
                source_type=SourceType.BANK,
                tenant_id=TENANT,
            )

        assert caught.value.code is ApiErrorCode.INVALID_SCHEMA

    def test_bank_mapping_naming_a_non_canonical_column_is_invalid_schema(self) -> None:
        with pytest.raises(IngestionError) as caught:
            ingest_source(
                BANK_HEADER + "dep_1,10.00,2026-01-04\n",
                source_type=SourceType.BANK,
                tenant_id=TENANT,
                bank_mapping=BankStatementMapping(
                    statement_currency="USD",
                    amount_column="not_a_bank_field",
                ),
            )

        assert caught.value.code is ApiErrorCode.INVALID_SCHEMA


class TestRowShape:
    """A row whose width disagrees with the header is reported, not coerced."""

    def test_short_row_is_reported_at_its_line_and_others_survive(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02\nINV-2,20.00,USD\nINV-3,30.00,USD,2026-01-04\n"
        )

        assert report.accepted_count == 2
        assert report.rejected_count == 1
        issue = report.issues[0]
        assert issue.code is IssueCode.ROW_SHAPE
        assert issue.line_number == 3
        assert dict(issue.raw) == {
            "column_1": "INV-2",
            "column_2": "20.00",
            "column_3": "USD",
        }

    def test_no_row_disappears_without_a_reason(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02\n"
            "INV-2,20.00,USD\n"
            "INV-3,30.00,USD,\n"
            "INV-4,40.00,USD,2026-01-05\n"
        )

        assert report.row_count == 4
        assert report.row_count == (
            report.accepted_count + report.rejected_count + report.skipped_debits
        )
        assert {issue.line_number for issue in report.issues} == {3, 4}


class TestFieldValidation:
    """Field-level failures name the row, the column, and the reason."""

    def test_missing_required_value_is_reported(self) -> None:
        report = _invoice("INV-1,,USD,2026-01-02\n")

        assert report.rejected_count == 1
        issue = report.issues[0]
        assert issue.code is IssueCode.MISSING_FIELD
        assert issue.field_name == "amount"
        assert issue.line_number == 2

    def test_blank_optional_fields_default_to_zero(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02,,\n",
            header="invoice_id,amount,currency,issued_at,fee,refund\n",
        )

        assert report.ok
        record = _payment(report)
        assert record.fee == Decimal("0")
        assert record.refund == Decimal("0")

    def test_zero_amount_is_accepted_as_a_boundary(self) -> None:
        report = _invoice("INV-1,0.00,USD,2026-01-02\n")

        assert report.ok
        assert _payment(report).gross == 0

    def test_non_numeric_amount_is_rejected(self) -> None:
        report = _invoice("INV-1,ten dollars,USD,2026-01-02\n")

        assert report.issues[0].code is IssueCode.INVALID_AMOUNT
        assert report.issues[0].field_name == "amount"

    def test_negative_amount_is_rejected(self) -> None:
        report = _invoice("INV-1,-10.00,USD,2026-01-02\n")

        assert report.issues[0].code is IssueCode.NEGATIVE_AMOUNT

    def test_refund_and_fee_above_gross_are_rejected(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02,5.00,6.00\n",
            header="invoice_id,amount,currency,issued_at,fee,refund\n",
        )

        assert report.issues[0].code is IssueCode.NEGATIVE_AMOUNT
        assert report.issues[0].field_name == "refund"

    def test_over_precision_is_rejected_not_rounded(self) -> None:
        report = _invoice("INV-1,10.005,USD,2026-01-02\n")

        assert report.issues[0].code is IssueCode.OVER_PRECISION
        assert report.accepted_count == 0

    def test_trailing_zeros_are_not_over_precision(self) -> None:
        report = _invoice("INV-1,10.000,USD,2026-01-02\n")

        assert report.ok
        assert _payment(report).gross == 10

    def test_zero_decimal_currency_rejects_fractional_minor_units(self) -> None:
        report = _invoice("INV-1,1000.5,JPY,2026-01-02\n")

        assert report.issues[0].code is IssueCode.OVER_PRECISION

    def test_zero_decimal_currency_accepts_whole_units(self) -> None:
        report = _invoice("INV-1,1000,JPY,2026-01-02\n")

        assert report.ok
        assert _payment(report).currency == "JPY"
        assert _payment(report).gross == 1000

    def test_three_decimal_currency_accepts_three_places(self) -> None:
        report = _invoice("INV-1,1.234,BHD,2026-01-02\n")

        assert report.ok
        assert _payment(report).gross == Decimal("1.234")

    def test_bad_date_is_reported(self) -> None:
        report = _invoice("INV-1,10.00,USD,02/01/2026\n")

        assert report.issues[0].code is IssueCode.INVALID_DATE

    def test_naive_timestamp_with_time_is_rejected_as_ambiguous(self) -> None:
        report = _invoice("INV-1,10.00,USD,2026-01-02T09:15:00\n")

        assert report.issues[0].code is IssueCode.INVALID_DATE

    def test_offset_timestamp_is_normalized_to_utc(self) -> None:
        report = _invoice("INV-1,10.00,USD,2026-01-02T09:15:00+02:00\n")

        assert report.ok
        assert _payment(report).occurred_at.hour == 7

    def test_bad_currency_is_reported(self) -> None:
        report = _invoice("INV-1,10.00,US,2026-01-02\n")

        assert report.issues[0].code is IssueCode.INVALID_CURRENCY

    def test_lowercase_currency_is_normalized(self) -> None:
        report = _invoice("INV-1,10.00,usd,2026-01-02\n")

        assert report.ok
        assert _payment(report).currency == "USD"

    def test_unknown_status_is_reported(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02,SETTLED_MAYBE\n",
            header="invoice_id,amount,currency,issued_at,status\n",
        )

        assert report.issues[0].code is IssueCode.INVALID_STATUS


class TestDuplicates:
    """Duplicates are detected explicitly; the first occurrence is kept."""

    def test_identical_repeat_is_a_duplicate_and_keeps_the_first(self) -> None:
        report = _invoice("INV-1,10.00,USD,2026-01-02\nINV-1,10.00,USD,2026-01-02\n")

        assert report.accepted_count == 1
        issue = report.issues[0]
        assert issue.code is IssueCode.DUPLICATE_ROW
        assert issue.line_number == 3
        assert issue.related_line == 2

    def test_reused_identifier_with_different_money_is_a_conflict(self) -> None:
        report = _invoice("INV-1,10.00,USD,2026-01-02\nINV-1,11.00,USD,2026-01-02\n")

        assert report.accepted_count == 1
        issue = report.issues[0]
        assert issue.code is IssueCode.CONFLICTING_ROW
        assert issue.related_line == 2
        assert _payment(report).gross == 10

    def test_duplicates_only_roll_up_to_duplicate_import(self) -> None:
        report = _invoice("INV-1,10.00,USD,2026-01-02\nINV-1,10.00,USD,2026-01-02\n")

        assert report.api_error_code is ApiErrorCode.DUPLICATE_IMPORT

    def test_mixed_problems_roll_up_to_validation_failed(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02\n"
            "INV-1,10.00,USD,2026-01-02\n"
            "INV-2,not-a-number,USD,2026-01-02\n"
        )

        assert report.api_error_code is ApiErrorCode.VALIDATION_FAILED

    def test_bank_duplicate_deposit_is_reported(self) -> None:
        report = _bank("dep_1,10.00,2026-01-04\ndep_1,10.00,2026-01-04\n")

        assert report.accepted_count == 1
        issue = report.issues[0]
        assert issue.code is IssueCode.DUPLICATE_ROW
        assert issue.related_line == 2
        assert issue.field_name == "deposit_id"


class TestBankSpecificRules:
    """Bank rows follow the frozen statement rules, including debits."""

    def test_debit_rows_are_counted_not_imported(self) -> None:
        report = _bank("dep_1,10.00,2026-01-04\ndep_2,-25.00,2026-01-05\n")

        assert report.accepted_count == 1
        assert report.skipped_debits == 1
        assert report.ok

    def test_currency_column_disagreeing_with_the_declaration_is_rejected(self) -> None:
        report = ingest_source(
            "deposit_id,amount,posted_at,currency\ndep_1,10.00,2026-01-04,EUR\n",
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="USD",
        )

        assert report.issues[0].code is IssueCode.CURRENCY_MISMATCH

    def test_bank_over_precision_is_rejected(self) -> None:
        report = _bank("dep_1,10.001,2026-01-04\n")

        assert report.issues[0].code is IssueCode.OVER_PRECISION


class TestLineMapping:
    """Physical line numbers survive blank lines and refused rows."""

    def test_blank_line_does_not_create_a_phantom_row(self) -> None:
        report = _bank("dep_1,10.00,2026-01-04\n\ndep_2,20.00,2026-01-05\n")

        assert report.ok
        assert report.accepted_count == 2
        assert report.row_count == 2
        assert [record.line_number for record in report.records] == [2, 4]

    def test_rows_after_a_refused_row_keep_their_physical_lines(self) -> None:
        report = _bank("dep_1,10.00,2026-01-04\ndep_2,20.00\ndep_3,30.00,2026-01-06\n")

        assert [record.line_number for record in report.records] == [2, 4]
        assert report.issues[0].code is IssueCode.ROW_SHAPE
        assert report.issues[0].line_number == 3
        assert report.row_count == 3

    def test_duplicate_after_a_blank_line_reports_both_real_lines(self) -> None:
        report = _bank("dep_1,10.00,2026-01-04\n\ndep_1,10.00,2026-01-04\n")

        assert report.accepted_count == 1
        issue = report.issues[0]
        assert issue.code is IssueCode.DUPLICATE_ROW
        assert issue.line_number == 4
        assert issue.related_line == 2


class TestReportRollUp:
    """The report is a complete, self-consistent account of the source."""

    def test_clean_source_has_no_api_error(self) -> None:
        report = _invoice("INV-1,10.00,USD,2026-01-02\n")

        assert report.ok
        assert report.api_error_code is None

    def test_counts_reconcile_with_the_source_rows(self) -> None:
        report = _invoice(
            "INV-1,10.00,USD,2026-01-02\nINV-2,20.00,USD,2026-01-03\nINV-3,bad,USD,2026-01-04\n"
        )

        assert report.row_count == 3
        assert report.accepted_count == 2
        assert report.rejected_count == 1
        assert report.skipped_debits == 0

    def test_every_issue_names_a_line_and_a_reason(self) -> None:
        report = _invoice(
            "INV-1,10.005,USD,2026-01-02\nINV-2,,USD,2026-01-03\nINV-3,10.00,US,2026-01-04\n"
        )

        assert [issue.line_number for issue in report.issues] == [2, 3, 4]
        assert all(issue.detail.strip() for issue in report.issues)
        assert all(issue.api_error_code is not None for issue in report.issues)
