"""Source-independent ingestion service.

One entry point turns raw source data into an auditable ingestion report:
the accepted canonical records with provenance, every refused row with an
actionable reason, and a stable roll-up API error code. The transport is
chosen by adapter, so a CSV upload and a Google Sheets range share the same
schema resolution, normalization, and validation.

The report is the validation preview. It contains no reconciliation
decision — no matching, classification, allocation, or exception resolution
— and it persists nothing.

Only the Python standard library and the frozen reconciliation core are used.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from finance.reconciliation.bank import BankStatementMapping
from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.models import PaymentRecord
from finance.source_ingestion.adapters import (
    ParsedTable,
    SourceAdapter,
    adapter_for,
    content_digest,
)
from finance.source_ingestion.issues import (
    ApiErrorCode,
    IssueCode,
    RowIssue,
)
from finance.source_ingestion.normalizer import (
    IngestedRecord,
    NormalizationOutcome,
    normalize_table,
)
from finance.source_ingestion.schemas import SourceType, schema_for


@dataclass(frozen=True)
class IngestionReport:
    """Outcome of ingesting one source: accepted records and refused rows.

    Attributes:
        source_type: Which of the three sources this report covers.
        source_format: Transport name (``"csv"``, ``"table"``, ...).
        content_digest: sha256 of the raw source bytes (file identity).
        table_digest: sha256 of the parsed table (canonical content identity).
        filename: Original filename, when the transport had one.
        headers: Header cells found in the source.
        unknown_headers: Headers with no canonical meaning, reported not fatal.
        records: Accepted canonical records with provenance, in line order.
        issues: Refused rows with reasons, in line order.
        skipped_debits: Bank debit rows counted but not imported.
        row_count: Data rows examined (accepted + refused + skipped debits).
    """

    source_type: SourceType
    source_format: str
    content_digest: str
    table_digest: str
    filename: str | None
    headers: tuple[str, ...]
    unknown_headers: tuple[str, ...]
    records: tuple[IngestedRecord, ...]
    issues: tuple[RowIssue, ...]
    skipped_debits: int
    row_count: int

    def __post_init__(self) -> None:
        """Validate the counts and the digest lengths."""
        if len(self.content_digest) != 64 or len(self.table_digest) != 64:
            raise ValueError("digests must be sha256 hex strings.")
        for name in ("skipped_debits", "row_count"):
            value: object = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int.")
            if value < 0:
                raise ValueError(f"{name} must be non-negative.")
        expected_rows = len(self.records) + len(self.issues) + self.skipped_debits
        if self.row_count != expected_rows:
            raise ValueError(
                f"row_count={self.row_count} disagrees with "
                f"accepted={len(self.records)} + refused={len(self.issues)} + "
                f"skipped_debits={self.skipped_debits}."
            )

    @property
    def accepted_count(self) -> int:
        """Return the number of accepted canonical records."""
        return len(self.records)

    @property
    def rejected_count(self) -> int:
        """Return the number of refused rows."""
        return len(self.issues)

    @property
    def ok(self) -> bool:
        """Return whether every examined row was accepted or intentionally skipped."""
        return not self.issues

    @property
    def api_error_code(self) -> ApiErrorCode | None:
        """Return the API error code this report rolls up to, if any.

        A report whose only problems are duplicates is a duplicate import; any
        other refused row is a row-level validation failure. Envelope failures
        raise :class:`IngestionError` instead of producing a report.
        """
        if not self.issues:
            return None
        if all(issue.code is IssueCode.DUPLICATE_ROW for issue in self.issues):
            return ApiErrorCode.DUPLICATE_IMPORT
        return ApiErrorCode.VALIDATION_FAILED

    def to_dict(self) -> dict[str, Any]:
        """Render the report as a JSON-safe validation preview."""
        return {
            "source_type": self.source_type.value,
            "source_format": self.source_format,
            "filename": self.filename,
            "content_digest": self.content_digest,
            "table_digest": self.table_digest,
            "headers": list(self.headers),
            "unknown_headers": list(self.unknown_headers),
            "row_count": self.row_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "skipped_debits": self.skipped_debits,
            "api_error_code": None if self.api_error_code is None else self.api_error_code.value,
            "records": [_record_payload(record) for record in self.records],
            "issues": [_issue_payload(issue) for issue in self.issues],
        }


def _record_payload(record: IngestedRecord) -> dict[str, Any]:
    """Render one accepted record for the preview payload."""
    payload: dict[str, Any] = {
        "line_number": record.line_number,
        "source_reference": record.provenance.reference,
        "key": record.key,
    }
    underlying = record.record
    if isinstance(underlying, PaymentRecord):
        payload.update(
            {
                "record_type": "PAYMENT",
                "payment_id": underlying.payment_id,
                "provider": underlying.provider,
                "gross": _money_text(underlying.gross),
                "fee": _money_text(underlying.fee),
                "refund": _money_text(underlying.refund),
                "net": _money_text(underlying.net),
                "currency": underlying.currency,
                "status": underlying.status.value,
                "occurred_at": underlying.occurred_at.isoformat(),
            }
        )
        return payload
    payload.update(
        {
            "record_type": "DEPOSIT",
            "deposit_id": underlying.deposit_id,
            "amount": _money_text(underlying.amount),
            "fee": _money_text(underlying.fee),
            "currency": underlying.currency,
            "posted_at": underlying.posted_at.isoformat(),
        }
    )
    return payload


def _issue_payload(issue: RowIssue) -> dict[str, Any]:
    """Render one refused row for the preview payload."""
    return {
        "code": issue.code.value,
        "api_error_code": issue.api_error_code.value,
        "line_number": issue.line_number,
        "field_name": issue.field_name,
        "detail": issue.detail,
        "related_line": issue.related_line,
        "raw": dict(issue.raw),
    }


def _money_text(value: Decimal) -> str:
    """Render a ``Decimal`` without scientific notation or float conversion."""
    return format(value, "f")


def _build_report(
    table: ParsedTable,
    outcome: NormalizationOutcome,
    *,
    source_type: SourceType,
    digest: str,
    filename: str | None,
) -> IngestionReport:
    """Merge adapter shape issues with normalization issues into a report."""
    shape_issues = tuple(
        RowIssue(
            code=IssueCode.ROW_SHAPE,
            line_number=shape.line_number,
            detail=(
                f"Row has {shape.found_cells} cells but the header has {shape.expected_cells}."
            ),
            raw={f"column_{index + 1}": cell for index, cell in enumerate(shape.cells)},
        )
        for shape in table.shape_issues
    )
    merged_issues = tuple(
        sorted(
            (*shape_issues, *outcome.issues),
            key=lambda issue: (issue.line_number, issue.code),
        )
    )
    return IngestionReport(
        source_type=source_type,
        source_format=table.source_format,
        content_digest=digest,
        table_digest=table.digest(),
        filename=filename,
        headers=table.headers,
        unknown_headers=outcome.unknown_headers,
        records=outcome.records,
        issues=merged_issues,
        skipped_debits=outcome.skipped_debits,
        row_count=len(outcome.records) + len(merged_issues) + outcome.skipped_debits,
    )


def ingest_source(
    raw: bytes | str,
    *,
    source_type: SourceType,
    tenant_id: str,
    filename: str | None = None,
    encoding: str = "utf-8",
    source_format: str = "csv",
    statement_currency: str | None = None,
    bank_mapping: BankStatementMapping | None = None,
    adapter: SourceAdapter | None = None,
) -> IngestionReport:
    """Ingest one source into canonical records plus a validation report.

    Args:
        raw: Raw source bytes or text. Ignored by adapters that bind their
            table at construction (e.g. an in-memory or Sheets range adapter).
        source_type: Which of the three sources is being ingested.
        tenant_id: Authenticated tenant from trusted calling context.
        filename: Original filename, when the transport had one.
        encoding: Text encoding for byte sources.
        source_format: Transport name; ``"csv"`` by default.
        statement_currency: Declared bank currency (required for bank sources
            unless ``bank_mapping`` is supplied).
        bank_mapping: Explicit bank column/currency declaration.
        adapter: Override the transport adapter; it must match ``source_type``.

    Returns:
        The ingestion report.

    Raises:
        IngestionError: For an empty, unreadable, or unsupported source, or a
            header row that does not satisfy the canonical schema.
        InvariantViolation: If ``tenant_id`` is empty.
        TypeError: If an injected adapter does not match ``source_type``.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise InvariantViolation("tenant_id must be a non-empty string.")
    schema = schema_for(source_type)
    resolved_adapter = adapter if adapter is not None else adapter_for(source_type, source_format)
    if resolved_adapter.source_type() is not source_type:
        raise TypeError(f"Adapter handles {resolved_adapter.source_type()}, not {source_type}.")
    table = resolved_adapter.parse_table(raw, encoding=encoding)
    digest = content_digest(raw)
    outcome = normalize_table(
        table,
        schema,
        tenant_id=tenant_id,
        content_digest=digest,
        filename=filename,
        statement_currency=statement_currency,
        bank_mapping=bank_mapping,
    )
    return _build_report(
        table,
        outcome,
        source_type=source_type,
        digest=digest,
        filename=filename,
    )


def ingest_table(
    table: ParsedTable,
    *,
    source_type: SourceType,
    tenant_id: str,
    filename: str | None = None,
    statement_currency: str | None = None,
    bank_mapping: BankStatementMapping | None = None,
) -> IngestionReport:
    """Ingest an already-parsed table (Sheets range, pasted block, fixture).

    This is the source-independent path: the same schema resolution and
    normalization run, with the parsed-table digest standing in for the raw
    file digest.

    Raises:
        IngestionError: If the header row does not satisfy the canonical schema.
        InvariantViolation: If ``tenant_id`` is empty.
    """
    if not isinstance(table, ParsedTable):
        raise TypeError(f"table must be a ParsedTable, got {type(table).__name__}.")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise InvariantViolation("tenant_id must be a non-empty string.")
    schema = schema_for(source_type)
    digest = table.digest()
    outcome = normalize_table(
        table,
        schema,
        tenant_id=tenant_id,
        content_digest=digest,
        filename=filename,
        statement_currency=statement_currency,
        bank_mapping=bank_mapping,
    )
    return _build_report(
        table,
        outcome,
        source_type=source_type,
        digest=digest,
        filename=filename,
    )
