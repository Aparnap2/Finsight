"""Deterministic normalization of parsed source rows into canonical records.

This module is the single place where a source cell becomes a financial
fact. It composes the frozen reconciliation primitives rather than
reimplementing them:

* invoice and Stripe rows become :class:`PaymentRecord` through
  :func:`finance.reconciliation.normalizer.normalize`;
* bank rows become :class:`BankDepositRecord` through
  :func:`finance.reconciliation.bank.normalize_bank_statement`.

Every accepted record keeps its provenance: source type, transport, file
digest, parsed-table digest, and 1-based physical line. Every refused row
keeps its original cells and an actionable reason. Nothing is silently
dropped, rounded, coerced, or inferred.

Money is ``Decimal`` only, quantized to the currency's minor unit; an
over-precise value is refused rather than rounded, matching the bank
statement boundary. A bare calendar date is read as UTC midnight, matching
:func:`finance.reconciliation.bank.normalize_bank_statement`.

Ingestion makes no reconciliation decision: it does not match, classify,
allocate, or resolve exceptions.

Only the Python standard library and the frozen reconciliation core are used.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from finance.reconciliation.bank import (
    BankDepositRecord,
    BankStatementMapping,
    RejectReason,
    normalize_bank_statement,
)
from finance.reconciliation.errors import FloatMoneyError, InvariantViolation
from finance.reconciliation.models import PaymentRecord, PaymentStatus
from finance.reconciliation.normalizer import minor_unit_exponent, normalize
from finance.source_ingestion.adapters import ParsedTable
from finance.source_ingestion.issues import (
    ApiErrorCode,
    IngestionError,
    IssueCode,
    RowIssue,
)
from finance.source_ingestion.schemas import ResolvedColumns, SourceSchema, SourceType

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")
_THOUSANDS_SEPARATOR = ","
_EMPTY_CELL = ""

_PROVIDER_BY_SOURCE: Mapping[SourceType, str] = MappingProxyType(
    {SourceType.INVOICE: "invoice", SourceType.STRIPE: "stripe"}
)
_ID_FIELD_BY_SOURCE: Mapping[SourceType, str] = MappingProxyType(
    {SourceType.INVOICE: "invoice_id", SourceType.STRIPE: "charge_id"}
)
_DATE_FIELD_BY_SOURCE: Mapping[SourceType, str] = MappingProxyType(
    {SourceType.INVOICE: "issued_at", SourceType.STRIPE: "created_at"}
)
_REJECT_CODE_BY_REASON: Mapping[RejectReason, IssueCode] = MappingProxyType(
    {
        RejectReason.MISSING_FIELD: IssueCode.MISSING_FIELD,
        RejectReason.INVALID_AMOUNT: IssueCode.INVALID_AMOUNT,
        RejectReason.OVER_PRECISION: IssueCode.OVER_PRECISION,
        RejectReason.INVALID_DATE: IssueCode.INVALID_DATE,
        RejectReason.CURRENCY_MISMATCH: IssueCode.CURRENCY_MISMATCH,
    }
)


@dataclass(frozen=True)
class Provenance:
    """Where one canonical record came from.

    Attributes:
        source_type: Which of the three sources produced the record.
        source_format: Transport name (``"csv"``, ``"table"``, ...).
        content_digest: sha256 of the raw source bytes (file identity).
        table_digest: sha256 of the parsed table (canonical content identity).
        line_number: 1-based physical line of the originating row.
        filename: Original filename when the transport had one.
    """

    source_type: SourceType
    source_format: str
    content_digest: str
    table_digest: str
    line_number: int
    filename: str | None = None

    def __post_init__(self) -> None:
        """Validate identifiers, digests, and the line number."""
        if not isinstance(self.source_type, SourceType):
            raise TypeError("source_type must be a SourceType.")
        for name in ("source_format", "content_digest", "table_digest"):
            value: object = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
        if len(self.content_digest) != 64 or len(self.table_digest) != 64:
            raise ValueError("digests must be sha256 hex strings.")
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool):
            raise TypeError("line_number must be an int.")
        if self.line_number < 2:
            raise ValueError("line_number must be >= 2 (the header is line 1).")
        if self.filename is not None and (
            not isinstance(self.filename, str) or not self.filename.strip()
        ):
            raise ValueError("filename must be a non-empty string or None.")

    @property
    def reference(self) -> str:
        """Return the ``table_digest:line`` locator used in audit trails."""
        return f"{self.table_digest}:{self.line_number}"


@dataclass(frozen=True)
class IngestedRecord:
    """One canonical record plus the evidence of where it came from."""

    provenance: Provenance
    raw: Mapping[str, str]
    record: PaymentRecord | BankDepositRecord

    def __post_init__(self) -> None:
        """Freeze the original cells and check the record type."""
        raw_value: object = self.raw
        if not isinstance(raw_value, Mapping):
            raise TypeError("raw must be a mapping of header -> cell.")
        object.__setattr__(self, "raw", MappingProxyType(dict(raw_value)))
        record_value: object = self.record
        if not isinstance(record_value, (PaymentRecord, BankDepositRecord)):
            raise TypeError("record must be a PaymentRecord or BankDepositRecord.")

    @property
    def line_number(self) -> int:
        """Return the physical source line of this record."""
        return self.provenance.line_number

    @property
    def key(self) -> str:
        """Return the source identifier of the underlying record."""
        return (
            self.record.payment_id
            if isinstance(self.record, PaymentRecord)
            else (self.record.deposit_id)
        )


@dataclass(frozen=True)
class NormalizationOutcome:
    """Accepted records and refused rows for one parsed table."""

    records: tuple[IngestedRecord, ...] = ()
    issues: tuple[RowIssue, ...] = ()
    skipped_debits: int = 0
    unknown_headers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the skipped-debit count."""
        if not isinstance(self.skipped_debits, int) or isinstance(self.skipped_debits, bool):
            raise TypeError("skipped_debits must be an int.")
        if self.skipped_debits < 0:
            raise ValueError("skipped_debits must be non-negative.")


class _RowRejectedError(Exception):
    """Internal control flow for one refused row."""

    def __init__(
        self,
        code: IssueCode,
        detail: str,
        *,
        field_name: str | None = None,
        related_line: int | None = None,
    ) -> None:
        """Store the deterministic reason and the offending column."""
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.field_name = field_name
        self.related_line = related_line


def normalize_table(
    table: ParsedTable,
    schema: SourceSchema,
    *,
    tenant_id: str,
    content_digest: str,
    filename: str | None = None,
    statement_currency: str | None = None,
    bank_mapping: BankStatementMapping | None = None,
) -> NormalizationOutcome:
    """Normalize one parsed table into canonical records and row issues.

    Args:
        table: Parsed source table with physical line numbers.
        schema: Canonical schema for the source type.
        tenant_id: Authenticated tenant from trusted calling context.
        content_digest: sha256 of the raw source bytes.
        filename: Original filename, when the transport had one.
        statement_currency: Declared bank currency (required for bank sources).
        bank_mapping: Explicit bank column/currency declaration, overriding the
            default mapping derived from the schema and ``statement_currency``.

    Returns:
        Accepted records, refused rows, and the skipped-debit count.

    Raises:
        IngestionError: If the header row does not satisfy the schema, or a
            bank source arrives without a declared statement currency.
        InvariantViolation: If ``tenant_id`` is empty.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise InvariantViolation("tenant_id must be a non-empty string.")
    if not isinstance(table, ParsedTable):
        raise TypeError(f"table must be a ParsedTable, got {type(table).__name__}.")
    if not isinstance(schema, SourceSchema):
        raise TypeError(f"schema must be a SourceSchema, got {type(schema).__name__}.")
    if schema.source_type is SourceType.BANK:
        return _normalize_bank(
            table,
            schema,
            tenant_id=tenant_id.strip(),
            content_digest=content_digest,
            filename=filename,
            statement_currency=statement_currency,
            bank_mapping=bank_mapping,
        )
    return _normalize_payments(
        table,
        schema,
        tenant_id=tenant_id.strip(),
        content_digest=content_digest,
        filename=filename,
    )


def _normalize_payments(
    table: ParsedTable,
    schema: SourceSchema,
    *,
    tenant_id: str,
    content_digest: str,
    filename: str | None,
) -> NormalizationOutcome:
    """Normalize invoice or Stripe rows into ``PaymentRecord`` values."""
    columns = schema.resolve(table.headers)
    table_digest = table.digest()
    source_type = schema.source_type
    records: list[IngestedRecord] = []
    issues: list[RowIssue] = []
    seen: dict[str, tuple[int, PaymentRecord]] = {}

    for line, row in table.pairs():
        cells = _canonical_cells(columns, row)
        try:
            record = _payment_record(cells, source_type, tenant_id=tenant_id)
        except _RowRejectedError as rejected:
            issues.append(
                RowIssue(
                    code=rejected.code,
                    line_number=line,
                    detail=rejected.detail,
                    field_name=rejected.field_name,
                    raw=row,
                    related_line=rejected.related_line,
                )
            )
            continue
        first = seen.get(record.idempotency_key)
        if first is not None:
            first_line, first_record = first
            identical = _economic_identity(first_record) == _economic_identity(record)
            issues.append(
                RowIssue(
                    code=IssueCode.DUPLICATE_ROW if identical else IssueCode.CONFLICTING_ROW,
                    line_number=line,
                    detail=(
                        f"{record.payment_id!r} duplicates the row on line {first_line}; "
                        "the earlier row is kept."
                        if identical
                        else (
                            f"{record.payment_id!r} was already used on line {first_line} "
                            "with different financial content; the earlier row is kept."
                        )
                    ),
                    field_name=_ID_FIELD_BY_SOURCE[source_type],
                    raw=row,
                    related_line=first_line,
                )
            )
            continue
        seen[record.idempotency_key] = (line, record)
        records.append(
            IngestedRecord(
                provenance=Provenance(
                    source_type=source_type,
                    source_format=table.source_format,
                    content_digest=content_digest,
                    table_digest=table_digest,
                    line_number=line,
                    filename=filename,
                ),
                raw=row,
                record=record,
            )
        )
    return NormalizationOutcome(
        records=tuple(records),
        issues=tuple(sorted(issues, key=lambda issue: issue.line_number)),
        unknown_headers=columns.unknown_headers,
    )


def _normalize_bank(
    table: ParsedTable,
    schema: SourceSchema,
    *,
    tenant_id: str,
    content_digest: str,
    filename: str | None,
    statement_currency: str | None,
    bank_mapping: BankStatementMapping | None,
) -> NormalizationOutcome:
    """Normalize bank statement rows into ``BankDepositRecord`` values.

    The frozen statement normalizer numbers rows positionally from 2. Blank
    source lines are not records, so the physical line of every present row is
    mapped back after normalization instead of inserting placeholder rows that
    would be reported as missing-field rejects.
    """
    columns = schema.resolve(table.headers)
    mapping = _bank_mapping(columns, statement_currency, bank_mapping, schema)
    table_digest = table.digest()
    rows_by_line = {line: row for line, row in table.pairs()}
    shape_by_line = {issue.line_number: issue for issue in table.shape_issues}
    present_lines = sorted({*rows_by_line, *shape_by_line})
    core_to_physical = {position: line for position, line in enumerate(present_lines, start=2)}
    ordered_rows: tuple[Mapping[str, Any], ...] = tuple(
        _canonical_cells(columns, rows_by_line.get(line, {})) for line in present_lines
    )
    result = normalize_bank_statement(
        ordered_rows,
        mapping,
        tenant_id=tenant_id,
        statement_digest=table_digest,
    )

    def physical_line(core_line: int) -> int:
        """Translate the frozen normalizer's positional line to the source line."""
        return core_to_physical.get(core_line, core_line)

    issues: list[RowIssue] = []
    for reject in result.rejects:
        line = physical_line(reject.line_number)
        if line in shape_by_line:
            continue
        issues.append(
            RowIssue(
                code=_REJECT_CODE_BY_REASON.get(reject.reason, IssueCode.INVALID_RECORD),
                line_number=line,
                detail=reject.detail,
                field_name=reject.field_name,
                raw=rows_by_line.get(line, {}),
            )
        )

    deposits = tuple(
        replace(deposit, line_number=physical_line(deposit.line_number))
        for deposit in result.deposits
    )
    records: list[IngestedRecord] = [
        _deposit_record(
            deposit,
            table_digest=table_digest,
            content_digest=content_digest,
            filename=filename,
            source_format=table.source_format,
            rows_by_line=rows_by_line,
        )
        for deposit in deposits
    ]
    for group in result.duplicates:
        first_line = physical_line(group[0].line_number)
        for duplicate in group[1:]:
            line = physical_line(duplicate.line_number)
            issues.append(
                RowIssue(
                    code=IssueCode.DUPLICATE_ROW,
                    line_number=line,
                    detail=(
                        f"Deposit {duplicate.deposit_id!r} duplicates the row on line "
                        f"{first_line}; the earlier row is kept."
                    ),
                    field_name="deposit_id",
                    raw=rows_by_line.get(line, {}),
                    related_line=first_line,
                )
            )
    return NormalizationOutcome(
        records=tuple(sorted(records, key=lambda record: record.line_number)),
        issues=tuple(sorted(issues, key=lambda issue: (issue.line_number, issue.code))),
        skipped_debits=result.skipped_debits,
        unknown_headers=columns.unknown_headers,
    )


def _deposit_record(
    deposit: BankDepositRecord,
    *,
    table_digest: str,
    content_digest: str,
    filename: str | None,
    source_format: str,
    rows_by_line: Mapping[int, Mapping[str, str]],
) -> IngestedRecord:
    """Attach provenance to one normalized bank deposit."""
    return IngestedRecord(
        provenance=Provenance(
            source_type=SourceType.BANK,
            source_format=source_format,
            content_digest=content_digest,
            table_digest=table_digest,
            line_number=deposit.line_number,
            filename=filename,
        ),
        raw=rows_by_line.get(deposit.line_number, {}),
        record=deposit,
    )


def _bank_mapping(
    columns: ResolvedColumns,
    statement_currency: str | None,
    explicit: BankStatementMapping | None,
    schema: SourceSchema,
) -> BankStatementMapping:
    """Resolve the bank column/currency declaration.

    Raises:
        IngestionError: If no mapping or statement currency is supplied, or an
            explicit mapping names a column that is not a canonical bank field.
    """
    if explicit is not None:
        if not isinstance(explicit, BankStatementMapping):
            raise TypeError("bank_mapping must be a BankStatementMapping or None.")
        canonical = set(schema.expected_headers)
        declared = (
            explicit.deposit_id_column,
            explicit.amount_column,
            explicit.date_column,
            explicit.account_column,
            explicit.reference_column,
            explicit.description_column,
            explicit.fee_column,
            explicit.currency_column,
        )
        unknown = tuple(name for name in declared if name is not None and name not in canonical)
        if unknown:
            raise IngestionError(
                ApiErrorCode.INVALID_SCHEMA,
                f"Bank mapping names non-canonical columns: {list(unknown)}.",
                missing_columns=unknown,
            )
        return explicit
    if statement_currency is None:
        raise IngestionError(
            ApiErrorCode.INVALID_SCHEMA,
            "Bank ingestion requires the declared statement currency.",
        )
    currency_header = columns.header_for("currency")
    return BankStatementMapping(
        statement_currency=statement_currency.strip().upper(),
        currency_column=currency_header,
    )


def _canonical_cells(columns: ResolvedColumns, row: Mapping[str, str]) -> dict[str, str]:
    """Project one raw row onto canonical field names."""
    cells: dict[str, str] = {}
    for field_name, header in columns.columns.items():
        cells[field_name] = row.get(header, _EMPTY_CELL)
    return cells


def _require_cell(cells: Mapping[str, str], field_name: str) -> str:
    """Return a required non-empty cell or reject the row."""
    value = cells.get(field_name, _EMPTY_CELL)
    if not isinstance(value, str) or not value.strip():
        raise _RowRejectedError(
            IssueCode.MISSING_FIELD,
            f"Required field {field_name!r} is missing or blank.",
            field_name=field_name,
        )
    return value.strip()


def _optional_cell(cells: Mapping[str, str], field_name: str) -> str | None:
    """Return an optional cell, treating blank as absent."""
    value = cells.get(field_name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _currency(cells: Mapping[str, str]) -> str:
    """Parse and validate the ISO 4217 currency cell."""
    raw = _require_cell(cells, "currency").upper()
    if _CURRENCY_PATTERN.fullmatch(raw) is None:
        raise _RowRejectedError(
            IssueCode.INVALID_CURRENCY,
            f"Currency {raw!r} is not an ISO 4217 three-letter code.",
            field_name="currency",
        )
    return raw


def _money(
    cells: Mapping[str, str],
    field_name: str,
    currency: str,
    *,
    required: bool,
) -> Decimal | None:
    """Parse one money cell as ``Decimal`` and enforce minor-unit precision."""
    raw = _require_cell(cells, field_name) if required else _optional_cell(cells, field_name)
    if raw is None:
        return None
    text = raw.replace(_THOUSANDS_SEPARATOR, "")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise _RowRejectedError(
            IssueCode.INVALID_AMOUNT,
            f"{field_name!r} is not a parseable amount: {raw!r}.",
            field_name=field_name,
        ) from exc
    if not value.is_finite():
        raise _RowRejectedError(
            IssueCode.INVALID_AMOUNT,
            f"{field_name!r} must be finite, got {raw!r}.",
            field_name=field_name,
        )
    exponent = minor_unit_exponent(currency)
    step = Decimal(1).scaleb(-exponent)
    try:
        quantized = value.quantize(step)
    except InvalidOperation as exc:
        raise _RowRejectedError(
            IssueCode.INVALID_AMOUNT,
            f"{field_name!r} is out of range: {raw!r}.",
            field_name=field_name,
        ) from exc
    if quantized != value:
        raise _RowRejectedError(
            IssueCode.OVER_PRECISION,
            f"{field_name!r} has more than {exponent} decimal places: {raw!r}.",
            field_name=field_name,
        )
    return value


def _instant(cells: Mapping[str, str], field_name: str) -> datetime:
    """Parse an ISO 8601 instant, treating a bare date as UTC midnight."""
    raw = _require_cell(cells, field_name)
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _RowRejectedError(
            IssueCode.INVALID_DATE,
            f"{field_name!r} is not an ISO 8601 date or instant: {raw!r}.",
            field_name=field_name,
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if len(raw) == 10:
            return parsed.replace(tzinfo=UTC)
        raise _RowRejectedError(
            IssueCode.INVALID_DATE,
            f"{field_name!r} must include a UTC offset: {raw!r}.",
            field_name=field_name,
        )
    return parsed.astimezone(UTC)


def _status(cells: Mapping[str, str]) -> PaymentStatus:
    """Parse an optional payment status, defaulting to CAPTURED."""
    raw = _optional_cell(cells, "status")
    if raw is None:
        return PaymentStatus.CAPTURED
    try:
        return PaymentStatus(raw.upper())
    except ValueError as exc:
        allowed = ", ".join(member.value for member in PaymentStatus)
        raise _RowRejectedError(
            IssueCode.INVALID_STATUS,
            f"Status {raw!r} is not one of: {allowed}.",
            field_name="status",
        ) from exc


def _economic_identity(
    record: PaymentRecord,
) -> tuple[Decimal, Decimal, Decimal, str, datetime, PaymentStatus]:
    """Return the financial content used to distinguish a duplicate from a conflict."""
    return (
        record.gross,
        record.fee,
        record.refund,
        record.currency,
        record.occurred_at,
        record.status,
    )


def _payment_record(
    cells: Mapping[str, str],
    source_type: SourceType,
    *,
    tenant_id: str,
) -> PaymentRecord:
    """Build one ``PaymentRecord`` from canonical cells.

    Provenance (file digest, line number) lives on the enclosing
    :class:`IngestedRecord`, not on the financial record, so equivalent data
    from two transports yields equal canonical records.

    Raises:
        _RowRejectedError: If any field is invalid or the domain rejects the record.
    """
    currency = _currency(cells)
    gross_value = _money(cells, "amount", currency, required=True)
    if gross_value is None:  # pragma: no cover - required=True always yields a value
        raise _RowRejectedError(
            IssueCode.MISSING_FIELD,
            "Required field 'amount' is missing.",
            field_name="amount",
        )
    gross = gross_value
    fee = _money(cells, "fee", currency, required=False) or Decimal("0")
    refund = _money(cells, "refund", currency, required=False) or Decimal("0")
    if gross < 0:
        raise _RowRejectedError(
            IssueCode.NEGATIVE_AMOUNT,
            f"'amount' must be non-negative, got {gross}.",
            field_name="amount",
        )
    for name, value in (("fee", fee), ("refund", refund)):
        if value < 0:
            raise _RowRejectedError(
                IssueCode.NEGATIVE_AMOUNT,
                f"{name!r} must be non-negative, got {value}.",
                field_name=name,
            )
    if gross - fee - refund < 0:
        raise _RowRejectedError(
            IssueCode.NEGATIVE_AMOUNT,
            f"Refund and fee exceed the gross amount ({gross} - {fee} - {refund}).",
            field_name="refund",
        )
    occurred_at = _instant(cells, _DATE_FIELD_BY_SOURCE[source_type])
    status = _status(cells)
    identifier = _require_cell(cells, _ID_FIELD_BY_SOURCE[source_type])
    provider = _PROVIDER_BY_SOURCE[source_type]
    event_id = _optional_cell(cells, "event_id") or f"{provider}:{identifier}"
    payload: dict[str, Any] = {
        "payment_id": identifier,
        "provider": provider,
        "provider_event_id": event_id,
        "idempotency_key": f"{provider}:{identifier}",
        "gross": gross,
        "fee": fee,
        "refund": refund,
        "currency": currency,
        "status": status,
        "occurred_at": occurred_at,
        "source_reference": _optional_cell(cells, "reference"),
    }
    try:
        return normalize(payload, tenant_id=tenant_id)
    except (FloatMoneyError, InvariantViolation) as exc:
        raise _RowRejectedError(
            IssueCode.INVALID_RECORD,
            f"Record rejected by the financial domain: {exc}.",
        ) from exc
