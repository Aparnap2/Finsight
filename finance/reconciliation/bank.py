"""Tenant-declared bank statement normalization into deposit records.

Banks export statements, not payment legs: the same deposit can settle
several charges, the amount may arrive net of a bank fee, and the file
carries no FinSight identifiers. This module turns parsed statement rows
into immutable :class:`BankDepositRecord` values under a caller-declared
mapping and the authenticated tenant.

Design rules enforced here:

* The tenant comes from trusted calling context. A tenant-like column in
  the file is opaque data and can never change ownership.
* Money is ``Decimal``-only; ``float``/``bool`` are rejected outright.
* Amounts are quantized to the currency's minor unit at this boundary.
  Over-precise values are rejected, never rounded.
* A rejected row is reported with its line number; nothing is silently
  coerced or dropped. Debit rows are counted, not reinterpreted.
* Re-importing the same statement yields the same fingerprints and no
  second deposit record.

Pure and deterministic: no LLM, database, network, clock reads, or
randomness. Only the Python standard library is used.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from finance.reconciliation.errors import (
    DuplicateError,
    FloatMoneyError,
    InvariantViolation,
)
from finance.reconciliation.normalizer import minor_unit_exponent

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_CANONICAL_SEPARATOR = "\x1f"
_LEG_SEPARATOR = "\x1e"
_THOUSANDS_SEPARATOR = ","
_DEFAULT_ACCOUNT = "statement"


class AmountUnit(StrEnum):
    """Whether statement amounts are expressed in major or minor units."""

    MAJOR = "MAJOR"
    MINOR = "MINOR"


class SignConvention(StrEnum):
    """How a statement expresses direction."""

    SIGNED = "SIGNED"
    DEBIT_CREDIT = "DEBIT_CREDIT"


class RejectReason(StrEnum):
    """Deterministic reason a statement row was not imported."""

    MISSING_FIELD = "MISSING_FIELD"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    OVER_PRECISION = "OVER_PRECISION"
    INVALID_DATE = "INVALID_DATE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    NOT_A_CREDIT = "NOT_A_CREDIT"


@dataclass(frozen=True)
class RowReject:
    """One statement row that could not become a deposit record."""

    line_number: int
    reason: RejectReason
    detail: str
    field_name: str | None = None

    def __post_init__(self) -> None:
        """Validate the line number and message text."""
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool):
            raise InvariantViolation("line_number must be an int.")
        if self.line_number < 1:
            raise InvariantViolation("line_number must be >= 1.")
        if not isinstance(self.reason, RejectReason):
            raise InvariantViolation("reason must be a RejectReason.")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise InvariantViolation("detail must be a non-empty string.")


@dataclass(frozen=True)
class BankStatementMapping:
    """Caller-declared interpretation of one bank's statement columns.

    The mapping is tenant-scoped by construction: it is resolved from the
    caller's context, never inferred from the file. ``statement_currency``
    is authoritative; an optional ``currency_column`` is only checked for
    agreement and never used to set the record currency.
    """

    statement_currency: str
    deposit_id_column: str = "deposit_id"
    amount_column: str = "amount"
    date_column: str = "posted_at"
    account_column: str | None = "account"
    reference_column: str | None = "reference"
    description_column: str | None = "description"
    fee_column: str | None = "fee"
    credit_column: str | None = None
    debit_column: str | None = None
    currency_column: str | None = None
    amount_unit: AmountUnit = AmountUnit.MAJOR
    sign_convention: SignConvention = SignConvention.SIGNED
    date_format: str = "%Y-%m-%d"
    minor_unit_override: int | None = None

    def __post_init__(self) -> None:
        """Coerce enums, validate columns, and reject ambiguous mappings."""
        currency_value: object = self.statement_currency
        if (
            not isinstance(currency_value, str)
            or _CURRENCY_PATTERN.fullmatch(currency_value.strip().upper()) is None
        ):
            raise InvariantViolation(
                f"statement_currency must be an ISO 4217 code, got {currency_value!r}."
            )
        object.__setattr__(self, "statement_currency", currency_value.strip().upper())
        unit = _coerce_enum(AmountUnit, self.amount_unit, "amount_unit")
        object.__setattr__(self, "amount_unit", unit)
        sign = _coerce_enum(SignConvention, self.sign_convention, "sign_convention")
        object.__setattr__(self, "sign_convention", sign)
        if not isinstance(self.date_format, str) or not self.date_format.strip():
            raise InvariantViolation("date_format must be a non-empty strptime format.")
        columns = (
            self.deposit_id_column,
            self.amount_column,
            self.date_column,
            self.account_column,
            self.reference_column,
            self.description_column,
            self.fee_column,
            self.credit_column,
            self.debit_column,
            self.currency_column,
        )
        present = [name for name in columns if name is not None]
        for name in present:
            if not isinstance(name, str) or not name.strip():
                raise InvariantViolation("Column names must be non-empty strings.")
        if len(set(present)) != len(present):
            raise InvariantViolation("Mapping columns must be distinct.")
        if sign is SignConvention.DEBIT_CREDIT and self.credit_column is None:
            raise InvariantViolation("DEBIT_CREDIT requires a credit_column.")
        if self.minor_unit_override is not None:
            minor_unit_exponent(self.statement_currency, self.minor_unit_override)

    def exponent(self) -> int:
        """Return the minor-unit exponent this mapping quantizes to."""
        return minor_unit_exponent(self.statement_currency, self.minor_unit_override)

    def digest(self) -> str:
        """Return a stable sha256 digest over the mapping declaration."""
        parts = (
            self.statement_currency,
            self.deposit_id_column,
            self.amount_column,
            self.date_column,
            self.account_column or "",
            self.reference_column or "",
            self.description_column or "",
            self.fee_column or "",
            self.credit_column or "",
            self.debit_column or "",
            self.currency_column or "",
            self.amount_unit.value,
            self.sign_convention.value,
            self.date_format,
            "" if self.minor_unit_override is None else str(self.minor_unit_override),
        )
        return hashlib.sha256(_CANONICAL_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BankDepositRecord:
    """Immutable, tenant-owned bank deposit evidence.

    ``amount`` is the amount credited to the account (net of ``fee``).
    ``statement_digest`` plus ``line_number`` locate the originating row
    without storing the file.
    """

    deposit_id: str
    tenant_id: str
    amount: Decimal
    currency: str
    posted_at: datetime
    statement_digest: str
    line_number: int
    fee: Decimal = Decimal("0")
    provider: str = "bank"
    account_reference: str = ""
    reference: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        """Enforce Decimal money, identifiers, currency, and provenance."""
        for field_name in ("amount", "fee"):
            _require_decimal(field_name, getattr(self, field_name))
        if self.amount <= Decimal("0"):
            raise InvariantViolation(f"Deposit amount must be positive, got {self.amount}.")
        if self.fee < Decimal("0"):
            raise InvariantViolation(f"Deposit fee must be non-negative, got {self.fee}.")
        for field_name in ("deposit_id", "tenant_id", "provider"):
            _require_text(field_name, getattr(self, field_name))
        currency_value: object = self.currency
        if not isinstance(currency_value, str):
            raise InvariantViolation("Field 'currency' must be a string.")
        if _CURRENCY_PATTERN.fullmatch(currency_value) is None:
            raise InvariantViolation(
                f"Field 'currency' must be an ISO 4217 code, got {currency_value!r}."
            )
        posted_value: object = self.posted_at
        if not isinstance(posted_value, datetime):
            raise InvariantViolation("Field 'posted_at' must be a datetime.")
        tzinfo = posted_value.tzinfo
        if tzinfo is None or tzinfo.utcoffset(posted_value) is None:
            raise InvariantViolation("Field 'posted_at' must be tz-aware.")
        digest_value: object = self.statement_digest
        if not isinstance(digest_value, str) or _DIGEST_PATTERN.fullmatch(digest_value) is None:
            raise InvariantViolation("Field 'statement_digest' must be a sha256 hex digest.")
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool):
            raise InvariantViolation("Field 'line_number' must be an int.")
        if self.line_number < 1:
            raise InvariantViolation("Field 'line_number' must be >= 1.")
        for field_name in ("account_reference", "reference", "description"):
            value: object = getattr(self, field_name)
            if not isinstance(value, str):
                raise InvariantViolation(f"Field '{field_name}' must be a string.")

    @property
    def source_reference(self) -> str:
        """Return the statement-local location of this deposit."""
        return f"{self.statement_digest}:{self.line_number}"


@dataclass(frozen=True)
class BankIngestResult:
    """Outcome of normalizing one statement, including what was refused."""

    tenant_id: str
    statement_digest: str
    mapping_digest: str
    currency: str
    deposits: tuple[BankDepositRecord, ...] = ()
    duplicates: tuple[tuple[BankDepositRecord, ...], ...] = ()
    rejects: tuple[RowReject, ...] = ()
    skipped_debits: int = 0

    def __post_init__(self) -> None:
        """Validate the envelope and the accounting of skipped rows."""
        _require_text("tenant_id", self.tenant_id)
        if _DIGEST_PATTERN.fullmatch(self.statement_digest) is None:
            raise InvariantViolation("statement_digest must be a sha256 hex digest.")
        if _DIGEST_PATTERN.fullmatch(self.mapping_digest) is None:
            raise InvariantViolation("mapping_digest must be a sha256 hex digest.")
        if not isinstance(self.skipped_debits, int) or isinstance(self.skipped_debits, bool):
            raise InvariantViolation("skipped_debits must be an int.")
        if self.skipped_debits < 0:
            raise InvariantViolation("skipped_debits must be non-negative.")


class _RowError(Exception):
    """Internal control flow for a single rejected statement row."""

    def __init__(
        self,
        reason: RejectReason,
        detail: str,
        field_name: str | None = None,
    ) -> None:
        """Store the deterministic reason, message, and offending column."""
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.field_name = field_name


def _coerce_enum(enum_type: type[StrEnum], value: object, name: str) -> Any:
    """Coerce a string or enum member, rejecting unknown values."""
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip().upper())
        except ValueError as exc:
            raise InvariantViolation(f"Unknown {name} {value!r}.") from exc
    raise InvariantViolation(f"Field '{name}' must be {enum_type.__name__} or a name.")


def _require_decimal(field_name: str, value: object) -> Decimal:
    """Validate a monetary field as a finite ``Decimal``."""
    if isinstance(value, (bool, float)):
        raise FloatMoneyError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvariantViolation(
            f"Field '{field_name}' must be a finite Decimal, got {type(value).__name__}."
        )
    return value


def _require_text(field_name: str, value: object) -> str:
    """Validate a non-empty identifier field and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise InvariantViolation(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _cell(row: Mapping[str, Any], column: str | None) -> Any:
    """Return a raw cell value; blank strings and ``None`` mean absent."""
    if column is None:
        return None
    value = row.get(column)
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _parse_money(value: Any, *, field_name: str, minor: bool) -> Decimal:
    """Parse a statement money cell without lossy coercion."""
    if isinstance(value, (bool, float)):
        raise FloatMoneyError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if minor:
        if not isinstance(value, int):
            raise _RowError(
                RejectReason.INVALID_AMOUNT,
                "minor-unit amounts must be integers",
                field_name,
            )
        return Decimal(value)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip().replace(_THOUSANDS_SEPARATOR, "")
        if not text:
            raise _RowError(RejectReason.MISSING_FIELD, "empty money cell", field_name)
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise _RowError(
                RejectReason.INVALID_AMOUNT,
                f"unparseable amount {value!r}",
                field_name,
            ) from exc
    else:
        raise _RowError(
            RejectReason.INVALID_AMOUNT,
            f"unsupported amount type {type(value).__name__}",
            field_name,
        )
    if not result.is_finite():
        raise _RowError(RejectReason.INVALID_AMOUNT, "non-finite amount", field_name)
    return result


def _quantize(value: Decimal, exponent: int, field_name: str, *, minor: bool) -> Decimal:
    """Scale minor units and reject over-precision instead of rounding."""
    scaled = value / (Decimal(10) ** exponent) if minor else value
    step = Decimal(1).scaleb(-exponent)
    try:
        quantized = scaled.quantize(step)
    except InvalidOperation as exc:
        raise _RowError(
            RejectReason.INVALID_AMOUNT,
            f"amount out of range: {scaled}",
            field_name,
        ) from exc
    if quantized != scaled:
        raise _RowError(
            RejectReason.OVER_PRECISION,
            f"{scaled} has more than {exponent} decimal places",
            field_name,
        )
    return scaled


def _parse_date(value: Any, date_format: str, field_name: str) -> datetime:
    """Parse a statement date, requiring an unambiguous instant."""
    if isinstance(value, datetime):
        tzinfo = value.tzinfo
        if tzinfo is None or tzinfo.utcoffset(value) is None:
            raise _RowError(
                RejectReason.INVALID_DATE,
                "naive datetime has no unambiguous instant",
                field_name,
            )
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.strptime(value.strip(), date_format)
        except ValueError as exc:
            raise _RowError(
                RejectReason.INVALID_DATE,
                f"does not match {date_format!r}: {value!r}",
                field_name,
            ) from exc
        return parsed.replace(tzinfo=UTC)
    raise _RowError(RejectReason.MISSING_FIELD, "empty date cell", field_name)


def _normalize_row(
    row: Mapping[str, Any],
    mapping: BankStatementMapping,
    *,
    tenant_id: str,
    statement_digest: str,
    line_number: int,
    exponent: int,
) -> BankDepositRecord:
    """Convert one raw row into a deposit record or raise a row error."""
    if mapping.currency_column is not None:
        raw_currency = _cell(row, mapping.currency_column)
        if raw_currency is not None:
            declared = str(raw_currency).strip().upper()
            if declared != mapping.statement_currency:
                raise _RowError(
                    RejectReason.CURRENCY_MISMATCH,
                    f"row currency {declared!r} differs from statement "
                    f"{mapping.statement_currency!r}",
                    mapping.currency_column,
                )
    minor = mapping.amount_unit is AmountUnit.MINOR
    if mapping.sign_convention is SignConvention.DEBIT_CREDIT:
        raw_amount = _cell(row, mapping.credit_column)
        if raw_amount is None:
            raise _RowError(
                RejectReason.INVALID_AMOUNT,
                "debit row (no credit amount)",
                mapping.credit_column,
            )
    else:
        raw_amount = _cell(row, mapping.amount_column)
        if raw_amount is None:
            raise _RowError(
                RejectReason.MISSING_FIELD,
                "empty amount cell",
                mapping.amount_column,
            )
    amount = _quantize(
        _parse_money(raw_amount, field_name="amount", minor=minor),
        exponent,
        "amount",
        minor=minor,
    )
    if amount < Decimal("0"):
        raise _RowError(
            RejectReason.NOT_A_CREDIT,
            f"debit row (negative amount {amount})",
            mapping.amount_column,
        )
    if amount == Decimal("0"):
        raise _RowError(
            RejectReason.INVALID_AMOUNT,
            "deposit amount must be positive, got 0",
            mapping.amount_column,
        )
    raw_fee = _cell(row, mapping.fee_column)
    fee = Decimal("0")
    if raw_fee is not None:
        fee = _quantize(
            _parse_money(raw_fee, field_name="fee", minor=minor),
            exponent,
            "fee",
            minor=minor,
        )
        if fee < Decimal("0"):
            raise _RowError(
                RejectReason.INVALID_AMOUNT,
                f"fee must be non-negative, got {fee}",
                mapping.fee_column,
            )
    posted_at = _parse_date(
        _cell(row, mapping.date_column), mapping.date_format, mapping.date_column
    )
    deposit_id = _cell(row, mapping.deposit_id_column)
    if deposit_id is None:
        raise _RowError(
            RejectReason.MISSING_FIELD,
            "empty deposit id",
            mapping.deposit_id_column,
        )
    account = _cell(row, mapping.account_column)
    reference = _cell(row, mapping.reference_column)
    description = _cell(row, mapping.description_column)
    return BankDepositRecord(
        deposit_id=str(deposit_id).strip(),
        tenant_id=tenant_id,
        amount=amount,
        fee=fee,
        currency=mapping.statement_currency,
        posted_at=posted_at,
        statement_digest=statement_digest,
        line_number=line_number,
        account_reference=_DEFAULT_ACCOUNT if account is None else str(account).strip(),
        reference="" if reference is None else str(reference).strip(),
        description="" if description is None else str(description).strip(),
    )


def normalize_bank_statement(
    rows: Sequence[Mapping[str, Any]],
    mapping: BankStatementMapping,
    *,
    tenant_id: str,
    statement_digest: str,
) -> BankIngestResult:
    """Normalize already-parsed statement rows under a declared mapping.

    Args:
        rows: Parsed rows in file order; the first data row is line 2.
        mapping: Caller-declared column/currency declaration.
        tenant_id: Authenticated tenant from trusted context.
        statement_digest: sha256 of the source bytes for provenance.

    Returns:
        A frozen ingest result with unique deposits, duplicate groups,
        per-row rejects, and the skipped-debit count.

    Raises:
        InvariantViolation: For a bad tenant, digest, mapping, or row type.
        FloatMoneyError: If a money cell is ``float``/``bool``.
    """
    _require_text("tenant_id", tenant_id)
    digest_value: object = statement_digest
    if not isinstance(digest_value, str) or _DIGEST_PATTERN.fullmatch(digest_value) is None:
        raise InvariantViolation("statement_digest must be a sha256 hex digest.")
    mapping_value: object = mapping
    if not isinstance(mapping_value, BankStatementMapping):
        raise InvariantViolation("mapping must be a BankStatementMapping.")
    exponent = mapping_value.exponent()
    deposits: list[BankDepositRecord] = []
    rejects: list[RowReject] = []
    skipped = 0
    for index, row in enumerate(rows, start=2):
        row_value: object = row
        if not isinstance(row_value, Mapping):
            raise InvariantViolation(
                f"rows[{index - 2}] must be a Mapping, got {type(row_value).__name__}."
            )
        try:
            record = _normalize_row(
                row_value,
                mapping_value,
                tenant_id=tenant_id.strip(),
                statement_digest=digest_value,
                line_number=index,
                exponent=exponent,
            )
        except _RowError as exc:
            if exc.reason is RejectReason.NOT_A_CREDIT:
                skipped += 1
                continue
            rejects.append(
                RowReject(
                    line_number=index,
                    reason=exc.reason,
                    detail=exc.detail,
                    field_name=exc.field_name,
                )
            )
            continue
        deposits.append(record)
    unique, duplicates = dedupe_deposits(deposits)
    return BankIngestResult(
        tenant_id=tenant_id.strip(),
        statement_digest=digest_value,
        mapping_digest=mapping_value.digest(),
        currency=mapping_value.statement_currency,
        deposits=tuple(unique),
        duplicates=tuple(tuple(group) for group in duplicates.values()),
        rejects=tuple(rejects),
        skipped_debits=skipped,
    )


def canonical_deposit(record: BankDepositRecord) -> str:
    """Render the canonical string form of one deposit record."""
    record_value: object = record
    if not isinstance(record_value, BankDepositRecord):
        raise InvariantViolation(
            f"canonical_deposit requires a BankDepositRecord, got {type(record_value).__name__}."
        )
    posted_utc = record_value.posted_at.astimezone(UTC).isoformat()
    parts = (
        record_value.tenant_id,
        record_value.provider,
        record_value.deposit_id,
        format(record_value.amount, "f"),
        format(record_value.fee, "f"),
        record_value.currency,
        posted_utc,
        record_value.account_reference,
        record_value.reference,
    )
    return _CANONICAL_SEPARATOR.join(parts)


def fingerprint_deposit(record: BankDepositRecord) -> str:
    """Compute the sha256 identity of one deposit.

    The digest covers economic identity only (tenant, provider, id,
    amount, fee, currency, instant, account, reference); the source file
    digest is provenance, not identity, so a re-export deduplicates.
    """
    return hashlib.sha256(canonical_deposit(record).encode("utf-8")).hexdigest()


def find_duplicate_deposits(
    records: Sequence[BankDepositRecord],
) -> dict[str, list[BankDepositRecord]]:
    """Group deposits by fingerprint, returning only repeated groups."""
    groups: dict[str, list[BankDepositRecord]] = {}
    for index, record in enumerate(records):
        record_value: object = record
        if not isinstance(record_value, BankDepositRecord):
            raise InvariantViolation(
                f"records[{index}] must be a BankDepositRecord, got {type(record_value).__name__}."
            )
        groups.setdefault(fingerprint_deposit(record_value), []).append(record_value)
    return {key: group for key, group in groups.items() if len(group) > 1}


def dedupe_deposits(
    records: Sequence[BankDepositRecord],
) -> tuple[list[BankDepositRecord], dict[str, list[BankDepositRecord]]]:
    """Return first-occurrence deposits plus the duplicate groups."""
    duplicates = find_duplicate_deposits(records)
    seen: set[str] = set()
    unique: list[BankDepositRecord] = []
    for record in records:
        key = fingerprint_deposit(record)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique, duplicates


def ensure_unique_deposits(records: Sequence[BankDepositRecord]) -> None:
    """Require each deposit fingerprint to appear at most once.

    Raises:
        DuplicateError: If any fingerprint repeats.
    """
    duplicates = find_duplicate_deposits(records)
    if duplicates:
        keys = ", ".join(sorted(duplicates))
        raise DuplicateError(f"Duplicate bank deposit fingerprint(s) detected: {keys}.")
