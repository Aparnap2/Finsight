"""P5-10 COBOL settlement ledger fixed-width batch protocol.

Implements the OUTBOUND→RESULT flow via S3 buckets for Meridian Commerce.
All monetary values use ``decimal.Decimal`` — never ``float``.

Protocol version: ``01`` (80-char fixed-width lines).

Batch ID representation:
- **Full format** (20 chars): ``LEGACY-YYYYMMDD-NNNN`` — used in models, S3 keys.
- **Compact format** (14 chars): ``LEGYYMMDD-NNNN`` — stored in the fixed-width file
  field (cols 3-16). Serialisation uses compact; deserialisation reconstructs full.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROTOCOL_VERSION: str = "01"
LINE_WIDTH: int = 80
FILE_PATTERN: str = "CORRECTION_{date}_231.DAT"
BATCH_ID_PATTERN: str = "LEGACY-{date}-{seq:04d}"
BATCH_ID_COMPACT_LEN: int = 14  # cols 3-16
RECORD_TYPE_CODES: frozenset[str] = frozenset({"01", "02", "03", "99"})
RESULT_CODES: frozenset[str] = frozenset({"AC", "RJ", "DU"})

# Field column ranges (0-indexed slices)
COL_VERSION = slice(0, 2)     # cols 1-2
COL_BATCH_ID = slice(2, 16)   # cols 3-16  (14 chars)
COL_SEQUENCE = slice(16, 24)  # cols 17-24 (8 chars)
COL_RECORD = slice(24, 76)    # cols 25-76 (52 chars)
COL_CHECKSUM = slice(76, 80)  # cols 77-80 (4 chars)

# Result field column ranges
COL_RESULT_CODE = slice(24, 26)   # cols 25-26 (2 chars)
COL_RESULT_DETAIL = slice(26, 76) # cols 27-76 (50 chars)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LegacyProtocolError(Exception):
    """Base for all legacy protocol failures."""


class LegacyParseError(LegacyProtocolError):
    """Fixed-width line fails structural validation."""


class LegacyChecksumError(LegacyProtocolError):
    """SHA-256 checksum mismatch on a line."""


class LegacyControlTotalError(LegacyProtocolError):
    """Control total in result does not match computed total."""


class LegacyUploadError(LegacyProtocolError):
    """S3 upload failed after retries."""


class LegacyResultTimeoutError(LegacyProtocolError):
    """Result file not found within timeout window."""


class LegacyTimeoutError(LegacyProtocolError):
    """S3 read or processing exceeded time limit."""


class CompanyIsolationError(Exception):
    """Company attempted to access another company's key prefix.

    This is an alias for ``TenantIsolationError`` to match the
    Meridian Commerce naming convention.
    """


# Re-export the finance-layer TenantIsolationError as an alias
# so downstream code can raise either name.
TenantIsolationError = CompanyIsolationError


# ---------------------------------------------------------------------------
# Batch ID Encoding (full ↔ compact)
# ---------------------------------------------------------------------------

_FULL_PREFIX = "LEGACY-"
_COMPACT_PREFIX = "LEG"


def _batch_id_to_compact(full_batch_id: str) -> str:
    """Convert ``LEGACY-YYYYMMDD-NNNN`` → ``LEGYYMMDD-NNNN`` (14 chars).

    Example: ``LEGACY-20260916-0042`` → ``LEG260916-0042``
    """
    if not full_batch_id.startswith(_FULL_PREFIX):
        raise LegacyParseError(f"Invalid full batch_id: {full_batch_id!r}")
    # Strip "LEGACY-" (7 chars) → "YYYYMMDD-NNNN" (13 chars)
    rest = full_batch_id[len(_FULL_PREFIX) :]
    if len(rest) != 13:
        raise LegacyParseError(
            f"Invalid full batch_id length: expected 20, got {len(full_batch_id)}"
        )
    # "YYYYMMDD-NNNN" → "YYMMDD-NNNN" (use 2-digit year)
    compact = _COMPACT_PREFIX + rest[2:]  # "LEG" + "YYMMDD-NNNN"
    if len(compact) != BATCH_ID_COMPACT_LEN:
        raise LegacyParseError(
            f"Compact batch_id must be {BATCH_ID_COMPACT_LEN} chars, got {len(compact)}"
        )
    return compact


def _compact_to_batch_id(compact: str) -> str:
    """Convert ``LEGYYMMDD-NNNN`` (14 chars) → ``LEGACY-YYYYMMDD-NNNN`` (20 chars).

    Example: ``LEG260916-0042`` → ``LEGACY-20260916-0042``
    """
    if len(compact) != BATCH_ID_COMPACT_LEN:
        raise LegacyParseError(
            f"Compact batch_id must be {BATCH_ID_COMPACT_LEN} chars, got {len(compact)}"
        )
    if not compact.startswith(_COMPACT_PREFIX):
        raise LegacyParseError(f"Invalid compact batch_id prefix: {compact!r}")
    # compact: "LEGYYMMDD-NNNN" → rest: "YYMMDD-NNNN" (11 chars)
    rest = compact[len(_COMPACT_PREFIX) :]
    # Prepend "20" to year → "YYYYMMDD-NNNN" → full: "LEGACY-YYYYMMDD-NNNN"
    full_rest = "20" + rest  # "20YYMMDD-NNNN" (13 chars)
    return _FULL_PREFIX + full_rest  # "LEGACY-20YYMMDD-NNNN" (20 chars)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_checksum(body: str) -> str:
    """Return last 4 hex chars of SHA-256 of the 76-char body."""
    if len(body) != 76:
        raise LegacyParseError(f"Checksum body must be 76 chars, got {len(body)}")
    return hashlib.sha256(body.encode("ascii")).hexdigest()[-4:]


def _parse_decimal_from_str(value: str) -> Decimal:
    """Parse a space/zero-padded string to Decimal."""
    cleaned = value.strip()
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise LegacyParseError(f"Invalid decimal value: {value!r}") from exc


# ---------------------------------------------------------------------------
# Result Enum
# ---------------------------------------------------------------------------


class RecordResult(StrEnum):
    """Per-record processing result from legacy system."""

    ACCEPTED = "AC"
    REJECTED = "RJ"
    DUPLICATE = "DU"


# ---------------------------------------------------------------------------
# Frozen Models
# ---------------------------------------------------------------------------


class LegacyBatchHeader(BaseModel):
    """Header metadata for a legacy batch — identifies the batch and company."""

    model_config = ConfigDict(frozen=True)

    company_id: str = Field(..., min_length=1, max_length=64)
    batch_id: str = Field(..., pattern=r"^LEGACY-\d{8}-\d{4}$")
    file_name: str = Field(..., pattern=r"^CORRECTION_\d{8}_231\.DAT$")
    version: str = Field(default=PROTOCOL_VERSION, pattern=r"^\d{2}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_records: int = Field(ge=0, default=0)
    control_total: Decimal = Field(default=Decimal("0"))

    @field_validator("control_total")
    @classmethod
    def _validate_control_total_precision(cls, v: Decimal) -> Decimal:
        """Ensure exactly 2 decimal places for monetary control total."""
        try:
            quantized = v.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValueError(f"control_total must be quantizable to 2 dp: {v}") from exc
        return quantized


class LegacyRecord(BaseModel):
    """A single fixed-width record within a batch — 80 chars total."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(default=PROTOCOL_VERSION, pattern=r"^\d{2}$")
    batch_id: str = Field(..., pattern=r"^LEGACY-\d{8}-\d{4}$")
    sequence: Annotated[int, Field(ge=1, le=99_999_999)]
    record_type: str = Field(..., pattern=r"^\d{2}$")
    record_payload: str = Field(..., min_length=50, max_length=50)
    amount: Decimal = Field(default=Decimal("0"))
    checksum: str = Field(..., pattern=r"^[0-9a-f]{4}$")

    @field_validator("record_type")
    @classmethod
    def _validate_record_type(cls, v: str) -> str:
        if v not in RECORD_TYPE_CODES:
            raise ValueError(f"record_type must be one of {sorted(RECORD_TYPE_CODES)}, got {v!r}")
        return v

    @field_validator("amount")
    @classmethod
    def _validate_amount_precision(cls, v: Decimal) -> Decimal:
        """Ensure exactly 2 decimal places for monetary amount."""
        try:
            return v.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValueError(f"amount must be quantizable to 2 dp: {v}") from exc

    def to_line(self) -> str:
        """Serialise to 80-char fixed-width line.

        Uses compact batch_id encoding (14 chars) for the wire format.
        """
        version = self.version.zfill(2)
        compact_bid = _batch_id_to_compact(self.batch_id)
        seq = str(self.sequence).zfill(8)
        record = (self.record_type + self.record_payload)[:52].ljust(52)
        body = version + compact_bid + seq + record
        assert len(body) == 76, f"Body must be 76 chars, got {len(body)}"
        return body + self.checksum

    @classmethod
    def from_line(cls, line: str) -> LegacyRecord:
        """Parse an 80-char fixed-width line into a LegacyRecord.

        The compact batch_id (14 chars) is expanded back to the full format.
        """
        if len(line) != LINE_WIDTH:
            raise LegacyParseError(f"Line must be {LINE_WIDTH} chars, got {len(line)}")

        version = line[COL_VERSION].strip()
        compact_bid = line[COL_BATCH_ID].strip()
        seq_str = line[COL_SEQUENCE].strip()
        record_raw = line[COL_RECORD]
        checksum = line[COL_CHECKSUM]

        # Validate checksum first
        body = line[:76]
        expected_checksum = _compute_checksum(body)
        if expected_checksum != checksum:
            raise LegacyChecksumError(
                f"Checksum mismatch: expected {expected_checksum!r}, got {checksum!r}"
            )

        if not seq_str or not seq_str.isdigit():
            raise LegacyParseError(f"Invalid sequence: {seq_str!r}")

        batch_id = _compact_to_batch_id(compact_bid)
        record_type = record_raw[:2]
        record_payload = record_raw[2:]

        return cls(
            version=version,
            batch_id=batch_id,
            sequence=int(seq_str),
            record_type=record_type,
            record_payload=record_payload.ljust(50)[:50],
            checksum=checksum,
        )


class LegacyBatch(BaseModel):
    """A complete legacy batch: header + records with control total validation."""

    model_config = ConfigDict(frozen=True)

    header: LegacyBatchHeader
    records: tuple[LegacyRecord, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_batch_consistency(self) -> LegacyBatch:
        """Ensure header total matches records count and control total matches."""
        if self.header.total_records != len(self.records):
            raise ValueError(
                f"Header total_records ({self.header.total_records}) "
                f"does not match actual records ({len(self.records)})"
            )
        # Validate control total
        computed = sum((r.amount for r in self.records if r.record_type != "99"), Decimal("0"))
        if computed != self.header.control_total:
            raise LegacyControlTotalError(
                f"Control total mismatch: computed {computed}, "
                f"expected {self.header.control_total}"
            )
        return self

    @model_validator(mode="after")
    def _validate_sequences(self) -> LegacyBatch:
        """Ensure monotonic, non-duplicate sequence numbers."""
        seen: set[int] = set()
        prev = 0
        for rec in self.records:
            if rec.sequence in seen:
                raise ValueError(f"Duplicate sequence {rec.sequence} in batch")
            if rec.sequence <= prev:
                raise ValueError(
                    f"Non-monotonic sequence: {rec.sequence} after {prev}"
                )
            seen.add(rec.sequence)
            prev = rec.sequence
        return self

    @model_validator(mode="after")
    def _validate_batch_ids_match(self) -> LegacyBatch:
        """All records must share the batch_id from the header."""
        for i, rec in enumerate(self.records):
            if rec.batch_id != self.header.batch_id:
                raise ValueError(
                    f"Record {i} batch_id {rec.batch_id!r} "
                    f"does not match header {self.header.batch_id!r}"
                )
        return self

    def to_lines(self) -> list[str]:
        """Serialise all records to 80-char fixed-width lines."""
        return [r.to_line() for r in self.records]

    @classmethod
    def from_lines(cls, lines: list[str], company_id: str) -> LegacyBatch:
        """Parse a list of 80-char lines into a LegacyBatch.

        The first line with record_type ``99`` is the control record.
        """
        if not lines:
            raise LegacyParseError("Empty batch — no lines provided")

        records = [LegacyRecord.from_line(line) for line in lines]

        # Extract control record (type 99) if present
        control_records = [r for r in records if r.record_type == "99"]
        if control_records:
            control_record = control_records[0]
            control_total_str = control_record.record_payload.strip()
            control_total = _parse_decimal_from_str(control_total_str)
        else:
            control_total = Decimal("0")

        # Build header from first record
        first = records[0]
        data_records = [r for r in records if r.record_type != "99"]
        computed_total = sum((r.amount for r in data_records), Decimal("0"))

        header = LegacyBatchHeader(
            company_id=company_id,
            batch_id=first.batch_id,
            file_name=FILE_PATTERN.format(date=first.batch_id[7:15]),
            version=first.version,
            total_records=len(records),
            control_total=control_total if control_records else computed_total,
        )

        return cls(header=header, records=tuple(records))


class LegacyRecordResult(BaseModel):
    """Per-record result from the legacy system."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(default=PROTOCOL_VERSION, pattern=r"^\d{2}$")
    batch_id: str = Field(..., pattern=r"^LEGACY-\d{8}-\d{4}$")
    sequence: Annotated[int, Field(ge=1, le=99_999_999)]
    result_code: RecordResult
    detail: str = Field(default="", max_length=50)
    checksum: str = Field(..., pattern=r"^[0-9a-f]{4}$")

    def to_line(self) -> str:
        """Serialise to 80-char fixed-width result line.

        Uses compact batch_id encoding for the wire format.
        """
        version = self.version.zfill(2)
        compact_bid = _batch_id_to_compact(self.batch_id)
        seq = str(self.sequence).zfill(8)
        result_code = self.result_code.value
        detail = self.detail.ljust(50)[:50]
        body = version + compact_bid + seq + result_code + detail
        assert len(body) == 76, f"Body must be 76 chars, got {len(body)}"
        return body + self.checksum

    @classmethod
    def from_line(cls, line: str) -> LegacyRecordResult:
        """Parse an 80-char result line.

        The compact batch_id is expanded back to the full format.
        """
        if len(line) != LINE_WIDTH:
            raise LegacyParseError(f"Line must be {LINE_WIDTH} chars, got {len(line)}")

        version = line[COL_VERSION].strip()
        compact_bid = line[COL_BATCH_ID].strip()
        seq_str = line[COL_SEQUENCE].strip()
        result_code_str = line[COL_RESULT_CODE].strip()
        detail = line[COL_RESULT_DETAIL]
        checksum = line[COL_CHECKSUM]

        body = line[:76]
        expected = _compute_checksum(body)
        if expected != checksum:
            raise LegacyChecksumError(
                f"Checksum mismatch: expected {expected!r}, got {checksum!r}"
            )

        if not seq_str or not seq_str.isdigit():
            raise LegacyParseError(f"Invalid sequence: {seq_str!r}")

        if result_code_str not in RESULT_CODES:
            raise LegacyParseError(f"Invalid result_code: {result_code_str!r}")

        batch_id = _compact_to_batch_id(compact_bid)

        return cls(
            version=version,
            batch_id=batch_id,
            sequence=int(seq_str),
            result_code=RecordResult(result_code_str),
            detail=detail.strip(),
            checksum=checksum,
        )


class LegacyResult(BaseModel):
    """Complete result from legacy processing — header + per-record results."""

    model_config = ConfigDict(frozen=True)

    header: LegacyBatchHeader
    record_results: tuple[LegacyRecordResult, ...] = Field(default_factory=tuple)

    @property
    def accepted_count(self) -> int:
        """Number of accepted records."""
        return sum(1 for r in self.record_results if r.result_code == RecordResult.ACCEPTED)

    @property
    def rejected_count(self) -> int:
        """Number of rejected records."""
        return sum(1 for r in self.record_results if r.result_code == RecordResult.REJECTED)

    @property
    def duplicate_count(self) -> int:
        """Number of duplicate records."""
        return sum(1 for r in self.record_results if r.result_code == RecordResult.DUPLICATE)

    @property
    def is_complete(self) -> bool:
        """True if all records have a result."""
        return len(self.record_results) == self.header.total_records

    @property
    def has_rejections(self) -> bool:
        """True if any records were rejected."""
        return self.rejected_count > 0

    @property
    def has_duplicates(self) -> bool:
        """True if any records were duplicates."""
        return self.duplicate_count > 0

    def get_result_for_sequence(self, sequence: int) -> LegacyRecordResult | None:
        """Return the result for a specific sequence number, or None."""
        for r in self.record_results:
            if r.sequence == sequence:
                return r
        return None

    @classmethod
    def from_lines(cls, lines: list[str], company_id: str) -> LegacyResult:
        """Parse result lines into a LegacyResult.

        The control record (type ``99`` in the original batch) is used to
        verify the control total.
        """
        if not lines:
            raise LegacyParseError("Empty result — no lines provided")

        record_results = [LegacyRecordResult.from_line(line) for line in lines]

        if not record_results:
            raise LegacyParseError("No valid record results parsed")

        first = record_results[0]

        header = LegacyBatchHeader(
            company_id=company_id,
            batch_id=first.batch_id,
            file_name=FILE_PATTERN.format(date=first.batch_id[7:15]),
            version=first.version,
            total_records=len(record_results),
            control_total=Decimal("0"),  # Will be validated by caller
        )

        return cls(header=header, record_results=tuple(record_results))


# ---------------------------------------------------------------------------
# S3 Key Helpers
# ---------------------------------------------------------------------------


def build_outbound_key(company_id: str, batch_id: str, processing_date: str) -> str:
    """Build the S3 key for an outbound batch file.

    Returns: ``{company_id}/{batch_id}/CORRECTION_{processing_date}_231.DAT``
    """
    file_name = FILE_PATTERN.format(date=processing_date)
    return f"{company_id}/{batch_id}/{file_name}"


def build_result_key(company_id: str, batch_id: str, processing_date: str) -> str:
    """Build the S3 key for a result file.

    Returns: ``{company_id}/{batch_id}/RESULT_{processing_date}_231.DAT``
    """
    return f"{company_id}/{batch_id}/RESULT_{processing_date}_231.DAT"


def validate_s3_key_tenant(key: str, company_id: str) -> None:
    """Validate that an S3 key belongs to the specified company.

    Raises ``CompanyIsolationError`` (alias ``TenantIsolationError``)
    if the key prefix does not match the company.
    """
    if not key or not key.strip():
        raise CompanyIsolationError("S3 key must be non-empty.")
    prefix = key.split("/", 1)[0]
    if prefix != company_id:
        raise CompanyIsolationError(
            f"Company {company_id!r} cannot access key {key!r}. "
            f"Key belongs to company {prefix!r}."
        )


def generate_batch_id(processing_date: str, sequence: int) -> str:
    """Generate a batch ID: ``LEGACY-YYYYMMDD-NNNN``."""
    return BATCH_ID_PATTERN.format(date=processing_date, seq=sequence)


def generate_file_name(processing_date: str) -> str:
    """Generate a file name: ``CORRECTION_YYYYMMDD_231.DAT``."""
    return FILE_PATTERN.format(date=processing_date)


def make_record_line(
    *,
    version: str = PROTOCOL_VERSION,
    batch_id: str,
    sequence: int,
    record_type: str,
    record_payload: str,
) -> str:
    """Build a valid 80-char record line with computed checksum.

    This is the primary factory for outbound lines — it computes the
    checksum automatically.  The ``batch_id`` is the full-format string
    (``LEGACY-YYYYMMDD-NNNN``); it is compacted for the wire.
    """
    version = version.zfill(2)
    compact_bid = _batch_id_to_compact(batch_id)
    seq = str(sequence).zfill(8)
    record = (record_type + record_payload)[:52].ljust(52)
    body = version + compact_bid + seq + record
    assert len(body) == 76, f"Body must be 76 chars, got {len(body)}"
    checksum = _compute_checksum(body)
    return body + checksum
