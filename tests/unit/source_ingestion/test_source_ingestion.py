"""Source ingestion: canonical output, provenance, and source independence.

Expected values are written as explicit literals or independently derived
arithmetic, never by calling the production normalizer. The properties
tested here are the ones the product depends on: a cell becomes exactly one
canonical record with a known origin, the same cells produce the same
records over any transport, and re-ingesting identical input is idempotent.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance.reconciliation.bank import BankDepositRecord
from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.models import PaymentRecord, PaymentStatus
from finance.source_ingestion import (
    IngestionReport,
    SourceType,
    TableAdapter,
    ingest_source,
    ingest_table,
)

TENANT = "tenant-acme"

INVOICE_CSV = """invoice_id,amount,currency,issued_at
INV-1000,250.00,USD,2026-01-02
INV-1001,"1,000.00",USD,2026-01-05
"""

STRIPE_CSV = """charge_id,amount,currency,created_at,fee
ch_1000,1000.00,USD,2026-01-05T09:15:00Z,29.00
"""

BANK_CSV = """deposit_id,amount,posted_at,currency,fee,account
dep_1000,250.00,2026-01-04,USD,0.00,operating
dep_1001,971.00,2026-01-05,USD,29.00,operating
"""


def _payment(report: IngestionReport, index: int) -> PaymentRecord:
    """Return the ``index``-th accepted record, asserting it is a payment leg."""
    record = report.records[index].record
    assert isinstance(record, PaymentRecord)
    return record


def _deposit(report: IngestionReport, index: int) -> BankDepositRecord:
    """Return the ``index``-th accepted record, asserting it is a deposit."""
    record = report.records[index].record
    assert isinstance(record, BankDepositRecord)
    return record


class TestInvoiceIngestion:
    """An invoice register export becomes canonical payment legs."""

    def test_first_invoice_is_normalized_to_expected_values(self) -> None:
        report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
            filename="invoices.csv",
        )

        assert report.ok
        assert report.accepted_count == 2
        record = _payment(report, 0)
        assert record.payment_id == "INV-1000"
        assert record.gross == Decimal("250.00")
        assert record.fee == Decimal("0")
        assert record.refund == Decimal("0")
        assert record.net == Decimal("250.00")
        assert record.currency == "USD"
        assert record.status is PaymentStatus.CAPTURED
        assert record.provider == "invoice"
        assert record.tenant_id == TENANT
        assert record.occurred_at == datetime(2026, 1, 2, tzinfo=UTC)

    def test_thousands_separator_is_parsed_not_truncated(self) -> None:
        report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert _payment(report, 1).gross == Decimal("1000.00")

    def test_explicit_fee_and_refund_preserve_the_net_equation(self) -> None:
        report = ingest_source(
            "invoice_id,amount,currency,issued_at,fee,refund\n"
            "INV-7,1000.00,USD,2026-01-05,29.00,10.00\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        record = _payment(report, 0)
        # Independently derived: 1000.00 - 29.00 - 10.00
        assert record.net == Decimal("961.00")
        assert record.net == record.gross - record.fee - record.refund


class TestStripeIngestion:
    """A processor export becomes canonical payment legs with its provider."""

    def test_stripe_charge_keeps_fee_and_net(self) -> None:
        report = ingest_source(
            STRIPE_CSV,
            source_type=SourceType.STRIPE,
            tenant_id=TENANT,
        )

        assert report.ok
        record = _payment(report, 0)
        assert record.payment_id == "ch_1000"
        assert record.provider == "stripe"
        assert record.gross == Decimal("1000.00")
        assert record.fee == Decimal("29.00")
        # Independently derived: 1000.00 - 29.00
        assert record.net == Decimal("971.00")
        assert record.occurred_at == datetime(2026, 1, 5, 9, 15, tzinfo=UTC)

    def test_event_id_defaults_to_the_charge_identity(self) -> None:
        report = ingest_source(
            STRIPE_CSV,
            source_type=SourceType.STRIPE,
            tenant_id=TENANT,
        )

        assert _payment(report, 0).provider_event_id == "stripe:ch_1000"

    def test_explicit_event_id_is_preserved(self) -> None:
        report = ingest_source(
            "charge_id,amount,currency,created_at,event_id\n"
            "ch_1,10.00,USD,2026-01-02T00:00:00Z,evt_9\n",
            source_type=SourceType.STRIPE,
            tenant_id=TENANT,
        )

        assert _payment(report, 0).provider_event_id == "evt_9"


class TestBankIngestion:
    """A bank statement becomes canonical deposit evidence."""

    def test_deposits_carry_amount_fee_and_utc_posting_instant(self) -> None:
        report = ingest_source(
            BANK_CSV,
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="USD",
        )

        assert report.ok
        assert report.accepted_count == 2
        first = _deposit(report, 0)
        second = _deposit(report, 1)
        assert first.deposit_id == "dep_1000"
        assert first.amount == Decimal("250.00")
        assert first.fee == Decimal("0")
        assert first.posted_at == datetime(2026, 1, 4, tzinfo=UTC)
        assert second.amount == Decimal("971.00")
        assert second.fee == Decimal("29.00")
        assert second.account_reference == "operating"

    def test_statement_digest_matches_the_parsed_table_digest(self) -> None:
        report = ingest_source(
            BANK_CSV,
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="USD",
        )

        deposit = _deposit(report, 0)
        assert deposit.statement_digest == report.table_digest
        assert deposit.source_reference == f"{report.table_digest}:2"

    def test_declared_statement_currency_is_authoritative(self) -> None:
        report = ingest_source(
            "deposit_id,amount,posted_at\ndep_1,10.00,2026-01-04\n",
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="gbp",
        )

        assert _deposit(report, 0).currency == "GBP"


class TestProvenance:
    """Every accepted record keeps a verifiable pointer to its source row."""

    def test_content_digest_is_the_sha256_of_the_raw_bytes(self) -> None:
        raw = INVOICE_CSV.encode("utf-8")
        report = ingest_source(
            raw,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert report.content_digest == hashlib.sha256(raw).hexdigest()

    def test_line_numbers_follow_the_physical_source_lines(self) -> None:
        report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert [record.line_number for record in report.records] == [2, 3]
        assert [record.provenance.reference for record in report.records] == [
            f"{report.table_digest}:2",
            f"{report.table_digest}:3",
        ]

    def test_original_cells_are_preserved_verbatim(self) -> None:
        report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert dict(report.records[1].raw) == {
            "invoice_id": "INV-1001",
            "amount": "1,000.00",
            "currency": "USD",
            "issued_at": "2026-01-05",
        }

    def test_filename_is_carried_when_the_transport_has_one(self) -> None:
        report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
            filename="invoices-2026-01.csv",
        )

        assert report.records[0].provenance.filename == "invoices-2026-01.csv"

    def test_source_type_is_recorded_on_every_record(self) -> None:
        report = ingest_source(
            BANK_CSV,
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="USD",
        )

        assert {record.provenance.source_type for record in report.records} == {SourceType.BANK}


class TestSourceIndependence:
    """Equivalent cells produce equivalent records over any transport."""

    def test_csv_and_table_transports_agree_record_for_record(self) -> None:
        csv_report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )
        adapter = TableAdapter(
            SourceType.INVOICE,
            ["invoice_id", "amount", "currency", "issued_at"],
            [
                ["INV-1000", "250.00", "USD", "2026-01-02"],
                ["INV-1001", "1,000.00", "USD", "2026-01-05"],
            ],
        )
        table_report = ingest_table(
            adapter.parse_table(),
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert [record.record for record in csv_report.records] == [
            record.record for record in table_report.records
        ]
        assert csv_report.table_digest == table_report.table_digest

    def test_header_aliases_resolve_to_the_same_canonical_record(self) -> None:
        canonical = ingest_source(
            "invoice_id,amount,currency,issued_at\nINV-1,10.00,USD,2026-01-02\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )
        aliased = ingest_source(
            "Invoice Number,Total,Currency Code,Invoice Date\nINV-1,10.00,USD,2026-01-02\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert canonical.records[0].record == aliased.records[0].record

    def test_header_case_spacing_and_punctuation_do_not_matter(self) -> None:
        report = ingest_source(
            "  Invoice-ID , Amount ,CURRENCY,issued.at\nINV-1,10.00,USD,2026-01-02\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert report.ok
        assert report.records[0].key == "INV-1"

    def test_unknown_headers_are_reported_but_not_fatal(self) -> None:
        report = ingest_source(
            "invoice_id,amount,currency,issued_at,customer_note\n"
            "INV-1,10.00,USD,2026-01-02,net 30\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert report.ok
        assert report.unknown_headers == ("customer_note",)
        assert report.records[0].key == "INV-1"


class TestMetamorphicProperties:
    """Transformations that must preserve, or provably change, the result."""

    def test_reingesting_identical_input_is_byte_identical(self) -> None:
        first = ingest_source(
            BANK_CSV,
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="USD",
        )
        second = ingest_source(
            BANK_CSV,
            source_type=SourceType.BANK,
            tenant_id=TENANT,
            statement_currency="USD",
        )

        assert first.to_dict() == second.to_dict()

    def test_permuting_data_rows_preserves_the_record_set(self) -> None:
        original = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )
        permuted = ingest_source(
            "invoice_id,amount,currency,issued_at\n"
            'INV-1001,"1,000.00",USD,2026-01-05\n'
            "INV-1000,250.00,USD,2026-01-02\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert {record.key: record.record for record in original.records} == {
            record.key: record.record for record in permuted.records
        }
        # Line numbers are provenance, so they legitimately change.
        assert [record.line_number for record in permuted.records] == [2, 3]

    def test_adding_an_unrelated_row_does_not_change_existing_records(self) -> None:
        baseline = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )
        extended = ingest_source(
            INVOICE_CSV + "INV-9999,5.00,USD,2026-02-01\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        baseline_by_key = {record.key: record.record for record in baseline.records}
        extended_by_key = {record.key: record.record for record in extended.records}
        assert all(extended_by_key[key] == value for key, value in baseline_by_key.items())
        assert extended.accepted_count == baseline.accepted_count + 1

    def test_different_content_yields_a_different_content_digest(self) -> None:
        first = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )
        second = ingest_source(
            INVOICE_CSV + "INV-9999,5.00,USD,2026-02-01\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert first.content_digest != second.content_digest
        assert first.table_digest != second.table_digest


class TestTenantBoundary:
    """Ownership comes from trusted context, never from the file."""

    def test_a_tenant_column_in_the_file_cannot_reassign_ownership(self) -> None:
        report = ingest_source(
            "invoice_id,amount,currency,issued_at,tenant_id\n"
            "INV-1,10.00,USD,2026-01-02,tenant-attacker\n",
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        assert _payment(report, 0).tenant_id == TENANT
        assert "tenant_id" in report.unknown_headers

    def test_empty_tenant_is_refused(self) -> None:
        with pytest.raises(InvariantViolation):
            ingest_source(INVOICE_CSV, source_type=SourceType.INVOICE, tenant_id="  ")


class TestNoReconciliationDecisions:
    """Ingestion reports evidence only; it never decides an outcome."""

    def test_report_exposes_no_match_or_exception_decision(self) -> None:
        report = ingest_source(
            INVOICE_CSV,
            source_type=SourceType.INVOICE,
            tenant_id=TENANT,
        )

        payload = report.to_dict()
        forbidden = {
            "outcome",
            "exception_code",
            "allocations",
            "matches",
            "materiality",
            "tolerance",
        }
        assert forbidden.isdisjoint(payload)
        assert all(forbidden.isdisjoint(record) for record in payload["records"])

    def test_preview_payload_is_json_safe_and_decimal_exact(self) -> None:
        report = ingest_source(
            STRIPE_CSV,
            source_type=SourceType.STRIPE,
            tenant_id=TENANT,
        )

        payload = report.to_dict()
        assert payload["records"][0]["net"] == "971.00"
        assert payload["records"][0]["fee"] == "29.00"
        assert payload["accepted_count"] == 1
        assert payload["rejected_count"] == 0
        assert payload["api_error_code"] is None
