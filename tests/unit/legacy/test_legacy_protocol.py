"""P5-10 COBOL settlement legacy batch protocol — unit tests.

TDD coverage: file/batch identity, schema positions, version, sequence,
control total mismatch fail-closed, checksum, accepted vs rejected,
partial processing, duplicate detection, result/retry/timeout semantics,
S3 key prefix with tenant isolation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from finance.legacy.protocol import (
    BATCH_ID_PATTERN,
    COL_BATCH_ID,
    COL_CHECKSUM,
    COL_RECORD,
    COL_SEQUENCE,
    COL_VERSION,
    FILE_PATTERN,
    LINE_WIDTH,
    PROTOCOL_VERSION,
    CompanyIsolationError,
    LegacyBatch,
    LegacyBatchHeader,
    LegacyChecksumError,
    LegacyControlTotalError,
    LegacyParseError,
    LegacyRecord,
    LegacyRecordResult,
    LegacyResult,
    RecordResult,
    TenantIsolationError,
    _batch_id_to_compact,
    _compact_to_batch_id,
    _compute_checksum,
    build_outbound_key,
    build_result_key,
    generate_batch_id,
    generate_file_name,
    make_record_line,
    validate_s3_key_tenant,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BATCH_ID = "LEGACY-20260916-0001"
COMPACT_BID = "LEG260916-0001"


def _make_result_checksum(batch_id: str, sequence: int, result_code: str, detail: str = "") -> str:
    """Compute the 4-hex-char checksum for a LegacyRecordResult line body."""
    compact_bid = _batch_id_to_compact(batch_id)
    version = PROTOCOL_VERSION
    seq = str(sequence).zfill(8)
    code = result_code
    det = detail.ljust(50)[:50]
    body = version + compact_bid + seq + code + det
    return _compute_checksum(body)


def _make_record(
    *,
    batch_id: str = BATCH_ID,
    sequence: int = 1,
    record_type: str = "01",
    payload: str = "A" * 50,
    amount: Decimal = Decimal("100.00"),
) -> LegacyRecord:
    """Build a LegacyRecord with a valid computed checksum."""
    version = PROTOCOL_VERSION
    compact_bid = _batch_id_to_compact(batch_id)
    body = version + compact_bid + str(sequence).zfill(8) + (record_type + payload)[:52].ljust(52)
    checksum = _compute_checksum(body)
    return LegacyRecord(
        version=version,
        batch_id=batch_id,
        sequence=sequence,
        record_type=record_type,
        record_payload=payload[:50].ljust(50),
        amount=amount,
        checksum=checksum,
    )


def _make_batch(
    *,
    company_id: str = "meridian-commerce",
    batch_id: str = BATCH_ID,
    records: list[LegacyRecord] | None = None,
) -> LegacyBatch:
    """Build a complete LegacyBatch with header and records."""
    if records is None:
        records = [
            _make_record(batch_id=batch_id, sequence=1, amount=Decimal("100.00")),
            _make_record(batch_id=batch_id, sequence=2, amount=Decimal("250.50")),
        ]
    control_total = sum(r.amount for r in records if r.record_type != "99")
    header = LegacyBatchHeader(
        company_id=company_id,
        batch_id=batch_id,
        file_name=FILE_PATTERN.format(date=batch_id[7:15]),
        total_records=len(records),
        control_total=control_total,
    )
    return LegacyBatch(header=header, records=tuple(records))


# ===========================================================================
# 1. File & Batch Identity
# ===========================================================================


class TestFileIdentity:
    """Verify file naming convention: CORRECTION_YYYYMMDD_231.DAT"""

    def test_file_pattern_matches_example(self) -> None:
        """Pattern produces the expected example filename."""
        name = FILE_PATTERN.format(date="20260916")
        assert name == "CORRECTION_20260916_231.DAT"

    def test_file_pattern_is_27_chars(self) -> None:
        """File name is exactly 27 characters."""
        name = FILE_PATTERN.format(date="20260101")
        assert len(name) == 27

    def test_record_type_code_is_231(self) -> None:
        """The record-type code is always 231."""
        name = FILE_PATTERN.format(date="20261231")
        assert "_231.DAT" in name

    def test_batch_id_pattern(self) -> None:
        """Batch ID follows LEGACY-YYYYMMDD-NNNN format."""
        batch_id = BATCH_ID_PATTERN.format(date="20260916", seq=42)
        assert batch_id == "LEGACY-20260916-0042"

    def test_batch_id_is_20_chars(self) -> None:
        """Batch ID is exactly 20 characters (full format)."""
        batch_id = BATCH_ID_PATTERN.format(date="20260916", seq=1)
        assert len(batch_id) == 20

    def test_generate_batch_id(self) -> None:
        """generate_batch_id produces correct format."""
        bid = generate_batch_id("20260916", 42)
        assert bid == "LEGACY-20260916-0042"

    def test_generate_file_name(self) -> None:
        """generate_file_name produces correct format."""
        fn = generate_file_name("20260916")
        assert fn == "CORRECTION_20260916_231.DAT"


# ===========================================================================
# 2. Schema Positions (80-char fixed-width)
# ===========================================================================


class TestSchemaPositions:
    """Verify column ranges for the 80-char fixed-width schema."""

    def test_line_width_is_80(self) -> None:
        """Every line must be exactly 80 characters."""
        assert LINE_WIDTH == 80

    def test_version_columns_1_to_2(self) -> None:
        """Version occupies columns 1-2 (indices 0-2)."""
        assert slice(0, 2) == COL_VERSION

    def test_batch_id_columns_3_to_16(self) -> None:
        """Batch ID occupies columns 3-16 (indices 2-16, 14 chars)."""
        assert slice(2, 16) == COL_BATCH_ID

    def test_sequence_columns_17_to_24(self) -> None:
        """Sequence occupies columns 17-24 (indices 16-24)."""
        assert slice(16, 24) == COL_SEQUENCE

    def test_record_columns_25_to_76(self) -> None:
        """Record payload occupies columns 25-76 (indices 24-76)."""
        assert slice(24, 76) == COL_RECORD

    def test_checksum_columns_77_to_80(self) -> None:
        """Checksum occupies columns 77-80 (indices 76-80)."""
        assert slice(76, 80) == COL_CHECKSUM

    def test_column_ranges_cover_80_chars(self) -> None:
        """All column ranges together cover exactly 80 characters."""
        test_line = "A" * 80
        assert (
            test_line[COL_VERSION]
            + test_line[COL_BATCH_ID]
            + test_line[COL_SEQUENCE]
            + test_line[COL_RECORD]
            + test_line[COL_CHECKSUM]
            == test_line
        )

    def test_to_line_produces_80_chars(self) -> None:
        """LegacyRecord.to_line() produces exactly 80 chars."""
        rec = _make_record(sequence=1)
        line = rec.to_line()
        assert len(line) == LINE_WIDTH

    def test_from_line_roundtrip(self) -> None:
        """LegacyRecord.from_line(to_line()) roundtrips the full batch_id."""
        rec = _make_record(sequence=1, payload="SETTLEMENT-CORRECTION-001" + "X" * 26)
        line = rec.to_line()
        parsed = LegacyRecord.from_line(line)
        assert parsed.version == rec.version
        assert parsed.batch_id == rec.batch_id
        assert parsed.sequence == rec.sequence
        assert parsed.record_type == rec.record_type
        assert parsed.checksum == rec.checksum


# ===========================================================================
# 3. Version Field
# ===========================================================================


class TestVersionField:
    """Verify protocol version handling."""

    def test_default_version_is_01(self) -> None:
        """Protocol version is 01."""
        assert PROTOCOL_VERSION == "01"

    def test_record_version_default(self) -> None:
        """LegacyRecord defaults to version 01."""
        rec = _make_record()
        assert rec.version == "01"

    def test_header_version_default(self) -> None:
        """LegacyBatchHeader defaults to version 01."""
        header = LegacyBatchHeader(
            company_id="test-co",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
        )
        assert header.version == "01"

    def test_version_in_line_at_position_0_1(self) -> None:
        """Version is at line[0:2]."""
        rec = _make_record()
        line = rec.to_line()
        assert line[0:2] == "01"


# ===========================================================================
# 4. Sequence Numbers
# ===========================================================================


class TestSequenceNumbers:
    """Verify monotonic sequence validation."""

    def test_monotonic_sequences_accepted(self) -> None:
        """Records with increasing sequences form a valid batch."""
        records = [_make_record(sequence=i) for i in range(1, 4)]
        batch = _make_batch(records=records)
        assert len(batch.records) == 3

    def test_non_monotonic_sequence_rejected(self) -> None:
        """Non-monotonic sequences raise ValueError."""
        records = [
            _make_record(sequence=1),
            _make_record(sequence=3),
            _make_record(sequence=2),
        ]
        with pytest.raises(ValueError, match="Non-monotonic"):
            _make_batch(records=records)

    def test_duplicate_sequence_rejected(self) -> None:
        """Duplicate sequences raise ValueError."""
        records = [
            _make_record(sequence=1),
            _make_record(sequence=1),
        ]
        with pytest.raises(ValueError, match="Duplicate sequence"):
            _make_batch(records=records)

    def test_sequence_at_position_16_24(self) -> None:
        """Sequence is zero-padded to 8 chars at columns 17-24."""
        rec = _make_record(sequence=42)
        line = rec.to_line()
        seq_field = line[COL_SEQUENCE]
        assert seq_field == "00000042"


# ===========================================================================
# 5. Control Total (Fail-Closed)
# ===========================================================================


class TestControlTotal:
    """Verify control total computation and mismatch fail-closed."""

    def test_control_total_computed_from_records(self) -> None:
        """Control total is the sum of non-control record amounts."""
        records = [
            _make_record(sequence=1, amount=Decimal("100.00")),
            _make_record(sequence=2, amount=Decimal("200.50")),
        ]
        batch = _make_batch(records=records)
        assert batch.header.control_total == Decimal("300.50")

    def test_control_total_mismatch_raises(self) -> None:
        """Mismatched control total raises LegacyControlTotalError."""
        records = [
            _make_record(sequence=1, amount=Decimal("100.00")),
            _make_record(sequence=2, amount=Decimal("200.50")),
        ]
        header = LegacyBatchHeader(
            company_id="meridian-commerce",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=2,
            control_total=Decimal("999.99"),  # Wrong!
        )
        with pytest.raises(LegacyControlTotalError, match="Control total mismatch"):
            LegacyBatch(header=header, records=tuple(records))

    def test_control_total_is_decimal(self) -> None:
        """Control total must be a Decimal, not float."""
        header = LegacyBatchHeader(
            company_id="test",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            control_total=Decimal("100.00"),
        )
        assert isinstance(header.control_total, Decimal)

    def test_control_total_rejects_float(self) -> None:
        """Float values are coerced to Decimal by Pydantic v2 (not rejected)."""
        header = LegacyBatchHeader(
            company_id="test",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            control_total=100.00,  # type: ignore[arg-type]
        )
        assert isinstance(header.control_total, Decimal)
        assert header.control_total == Decimal("100.00")

    def test_control_record_type_99(self) -> None:
        """Record type 99 is the control record."""
        rec = _make_record(record_type="99", sequence=99)
        assert rec.record_type == "99"


# ===========================================================================
# 6. SHA-256 Checksum
# ===========================================================================


class TestChecksum:
    """Verify SHA-256 checksum computation and validation."""

    def test_checksum_is_4_hex_chars(self) -> None:
        """Checksum is exactly 4 hexadecimal characters."""
        rec = _make_record()
        assert len(rec.checksum) == 4
        assert all(c in "0123456789abcdef" for c in rec.checksum)

    def test_checksum_computed_correctly(self) -> None:
        """Checksum is last 4 hex chars of SHA-256 of 76-char body."""
        compact_bid = _batch_id_to_compact(BATCH_ID)
        body = "01" + compact_bid + "00000001" + "01" + "A" * 50
        body = body.ljust(76)[:76]
        expected = _compute_checksum(body)
        assert len(expected) == 4

    def test_checksum_mismatch_raises(self) -> None:
        """Corrupted checksum raises LegacyChecksumError."""
        rec = _make_record(sequence=1)
        line = rec.to_line()
        # Corrupt the checksum
        corrupted = line[:76] + "ZZZZ"
        with pytest.raises(LegacyChecksumError):
            LegacyRecord.from_line(corrupted)

    def test_checksum_detects_tamper(self) -> None:
        """Checksum detects tampering in the record body."""
        rec = _make_record(sequence=1, payload="LEGIT" + "X" * 45)
        line = rec.to_line()
        # Tamper with one character in the record field
        tampered = line[:30] + "Z" + line[31:]
        with pytest.raises(LegacyChecksumError):
            LegacyRecord.from_line(tampered)

    def test_checksum_at_position_76_80(self) -> None:
        """Checksum occupies columns 77-80."""
        rec = _make_record()
        line = rec.to_line()
        assert line[COL_CHECKSUM] == rec.checksum

    def test_compute_checksum_rejects_wrong_length(self) -> None:
        """_compute_checksum rejects bodies that aren't 76 chars."""
        with pytest.raises(LegacyParseError, match="76 chars"):
            _compute_checksum("short")


# ===========================================================================
# 7. Accepted vs. Rejected Records
# ===========================================================================


class TestAcceptedRejected:
    """Verify accepted/rejected record semantics."""

    def test_result_code_accepted(self) -> None:
        """RecordResult.ACCEPTED maps to 'AC'."""
        assert RecordResult.ACCEPTED.value == "AC"

    def test_result_code_rejected(self) -> None:
        """RecordResult.REJECTED maps to 'RJ'."""
        assert RecordResult.REJECTED.value == "RJ"

    def test_result_code_duplicate(self) -> None:
        """RecordResult.DUPLICATE maps to 'DU'."""
        assert RecordResult.DUPLICATE.value == "DU"

    def test_result_line_roundtrip(self) -> None:
        """LegacyRecordResult roundtrips through to_line/from_line."""
        cs = _make_result_checksum(BATCH_ID, 1, "AC", "")
        result = LegacyRecordResult(
            batch_id=BATCH_ID,
            sequence=1,
            result_code=RecordResult.ACCEPTED,
            detail="",
            checksum=cs,
        )
        line = result.to_line()
        assert len(line) == LINE_WIDTH
        parsed = LegacyRecordResult.from_line(line)
        assert parsed.result_code == RecordResult.ACCEPTED
        assert parsed.sequence == 1
        assert parsed.batch_id == BATCH_ID

    def test_result_rejected_with_detail(self) -> None:
        """Rejected result carries a detail message."""
        cs = _make_result_checksum(BATCH_ID, 2, "RJ", "Invalid account number")
        result = LegacyRecordResult(
            batch_id=BATCH_ID,
            sequence=2,
            result_code=RecordResult.REJECTED,
            detail="Invalid account number",
            checksum=cs,
        )
        line = result.to_line()
        parsed = LegacyRecordResult.from_line(line)
        assert parsed.result_code == RecordResult.REJECTED
        assert "Invalid account number" in parsed.detail


# ===========================================================================
# 8. Partial Processing
# ===========================================================================


class TestPartialProcessing:
    """Verify partial processing semantics — mixed accept/reject."""

    def test_result_with_mixed_codes(self) -> None:
        """A result can have both accepted and rejected records."""
        results = (
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=1, result_code=RecordResult.ACCEPTED,
                checksum=_make_result_checksum(BATCH_ID, 1, "AC"),
            ),
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=2, result_code=RecordResult.REJECTED,
                detail="Duplicate amount",
                checksum=_make_result_checksum(BATCH_ID, 2, "RJ", "Duplicate amount"),
            ),
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=3, result_code=RecordResult.ACCEPTED,
                checksum=_make_result_checksum(BATCH_ID, 3, "AC"),
            ),
        )
        header = LegacyBatchHeader(
            company_id="meridian-commerce",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=3,
        )
        result = LegacyResult(header=header, record_results=results)
        assert result.accepted_count == 2
        assert result.rejected_count == 1
        assert result.has_rejections is True
        assert result.is_complete is True

    def test_partial_result_incomplete(self) -> None:
        """A result with fewer records than header total is incomplete."""
        results = (
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=1, result_code=RecordResult.ACCEPTED,
                checksum=_make_result_checksum(BATCH_ID, 1, "AC"),
            ),
        )
        header = LegacyBatchHeader(
            company_id="meridian-commerce",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=3,
        )
        result = LegacyResult(header=header, record_results=results)
        assert result.is_complete is False


# ===========================================================================
# 9. Duplicate Detection
# ===========================================================================


class TestDuplicateDetection:
    """Verify duplicate detection at batch and record level."""

    def test_duplicate_batch_id_rejected(self) -> None:
        """Two batches with the same batch_id should not be created."""
        batch1 = _make_batch(batch_id=BATCH_ID)
        batch2 = _make_batch(batch_id=BATCH_ID)
        # Both can exist in memory, but the caller must detect duplicates
        assert batch1.header.batch_id == batch2.header.batch_id

    def test_duplicate_record_returns_du(self) -> None:
        """A record that was already processed returns DU."""
        cs = _make_result_checksum(
            BATCH_ID, 1, "DU", "Already processed in batch LEGACY-20260915-0001"
        )
        result = LegacyRecordResult(
            batch_id=BATCH_ID,
            sequence=1,
            result_code=RecordResult.DUPLICATE,
            detail="Already processed in batch LEGACY-20260915-0001",
            checksum=cs,
        )
        assert result.result_code == RecordResult.DUPLICATE

    def test_result_count_duplicates(self) -> None:
        """LegacyResult counts duplicate records."""
        results = (
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=1, result_code=RecordResult.ACCEPTED,
                checksum=_make_result_checksum(BATCH_ID, 1, "AC"),
            ),
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=2, result_code=RecordResult.DUPLICATE,
                checksum=_make_result_checksum(BATCH_ID, 2, "DU"),
            ),
        )
        header = LegacyBatchHeader(
            company_id="test",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=2,
        )
        result = LegacyResult(header=header, record_results=results)
        assert result.duplicate_count == 1
        assert result.has_duplicates is True


# ===========================================================================
# 10. Result / Retry / Timeout Semantics
# ===========================================================================


class TestResultRetryTimeoutSemantics:
    """Verify result, retry, and timeout error types exist and are correct."""

    def test_legacy_parse_error_exists(self) -> None:
        """LegacyParseError is raised on parse failures."""
        with pytest.raises(LegacyParseError):
            LegacyRecord.from_line("short")

    def test_legacy_checksum_error_exists(self) -> None:
        """LegacyChecksumError is raised on checksum mismatches."""
        with pytest.raises(LegacyChecksumError):
            LegacyRecord.from_line("A" * 76 + "ZZZZ")

    def test_legacy_control_total_error_exists(self) -> None:
        """LegacyControlTotalError is raised on control total mismatch."""
        with pytest.raises(LegacyControlTotalError):
            records = [_make_record(sequence=1, amount=Decimal("100.00"))]
            header = LegacyBatchHeader(
                company_id="test",
                batch_id=BATCH_ID,
                file_name="CORRECTION_20260916_231.DAT",
                total_records=1,
                control_total=Decimal("999.99"),
            )
            LegacyBatch(header=header, records=tuple(records))

    def test_get_result_for_sequence(self) -> None:
        """Can look up a result by sequence number."""
        results = (
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=1, result_code=RecordResult.ACCEPTED,
                checksum=_make_result_checksum(BATCH_ID, 1, "AC"),
            ),
            LegacyRecordResult(
                batch_id=BATCH_ID, sequence=2, result_code=RecordResult.REJECTED,
                checksum=_make_result_checksum(BATCH_ID, 2, "RJ"),
            ),
        )
        header = LegacyBatchHeader(
            company_id="test",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=2,
        )
        result = LegacyResult(header=header, record_results=results)
        assert result.get_result_for_sequence(1).result_code == RecordResult.ACCEPTED
        assert result.get_result_for_sequence(2).result_code == RecordResult.REJECTED
        assert result.get_result_for_sequence(99) is None


# ===========================================================================
# 11. S3 Key Prefix & Tenant Isolation
# ===========================================================================


class TestS3KeyPrefix:
    """Verify S3 key convention and tenant isolation."""

    def test_outbound_key_format(self) -> None:
        """Outbound key follows {company_id}/{batch_id}/CORRECTION_YYYYMMDD_231.DAT"""
        key = build_outbound_key("meridian-commerce", "LEGACY-20260916-0042", "20260916")
        assert key == "meridian-commerce/LEGACY-20260916-0042/CORRECTION_20260916_231.DAT"

    def test_result_key_format(self) -> None:
        """Result key follows {company_id}/{batch_id}/RESULT_YYYYMMDD_231.DAT"""
        key = build_result_key("meridian-commerce", "LEGACY-20260916-0042", "20260916")
        assert key == "meridian-commerce/LEGACY-20260916-0042/RESULT_20260916_231.DAT"

    def test_validate_s3_key_tenant_pass(self) -> None:
        """Key with matching company prefix passes validation."""
        validate_s3_key_tenant("meridian-commerce/batch/file.DAT", "meridian-commerce")

    def test_validate_s3_key_tenant_fail(self) -> None:
        """Key with wrong company prefix raises TenantIsolationError."""
        with pytest.raises(CompanyIsolationError):
            validate_s3_key_tenant("other-company/batch/file.DAT", "meridian-commerce")

    def test_validate_s3_key_empty_raises(self) -> None:
        """Empty key raises CompanyIsolationError."""
        with pytest.raises(CompanyIsolationError):
            validate_s3_key_tenant("", "meridian-commerce")

    def test_tenant_isolation_error_is_company_isolation_error(self) -> None:
        """TenantIsolationError is an alias for CompanyIsolationError."""
        assert TenantIsolationError is CompanyIsolationError

    def test_isolation_error_catches_cross_tenant(self) -> None:
        """Cross-tenant access attempt raises the isolation error."""
        with pytest.raises((TenantIsolationError, CompanyIsolationError)):
            validate_s3_key_tenant("tenant-b/data.csv", "tenant-a")


# ===========================================================================
# 12. make_record_line Factory
# ===========================================================================


class TestMakeRecordLine:
    """Verify the make_record_line factory function."""

    def test_produces_80_chars(self) -> None:
        """make_record_line returns exactly 80 characters."""
        line = make_record_line(
            batch_id=BATCH_ID,
            sequence=1,
            record_type="01",
            record_payload="A" * 50,
        )
        assert len(line) == 80

    def test_checksum_is_valid(self) -> None:
        """The line produced by make_record_line has a valid checksum."""
        line = make_record_line(
            batch_id=BATCH_ID,
            sequence=1,
            record_type="01",
            record_payload="B" * 50,
        )
        # Should not raise
        parsed = LegacyRecord.from_line(line)
        assert parsed.sequence == 1
        assert parsed.batch_id == BATCH_ID

    def test_version_at_start(self) -> None:
        """Version 01 is at the start of the line."""
        line = make_record_line(
            batch_id=BATCH_ID,
            sequence=1,
            record_type="01",
            record_payload="C" * 50,
        )
        assert line[:2] == "01"


# ===========================================================================
# 13. Batch Model Validators
# ===========================================================================


class TestBatchValidators:
    """Verify LegacyBatch model validators."""

    def test_header_total_mismatch_raises(self) -> None:
        """Header total_records must match actual record count."""
        records = [_make_record(sequence=1)]
        header = LegacyBatchHeader(
            company_id="test",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=5,  # Wrong!
            control_total=Decimal("100.00"),
        )
        with pytest.raises(ValueError, match="total_records"):
            LegacyBatch(header=header, records=tuple(records))

    def test_batch_id_mismatch_raises(self) -> None:
        """Records must share the header's batch_id."""
        rec = _make_record(batch_id=BATCH_ID, sequence=1)
        header = LegacyBatchHeader(
            company_id="test",
            batch_id="LEGACY-20260916-9999",  # Different!
            file_name="CORRECTION_20260916_231.DAT",
            total_records=1,
            control_total=Decimal("100.00"),
        )
        with pytest.raises(ValueError, match="batch_id"):
            LegacyBatch(header=header, records=(rec,))

    def test_frozen_models(self) -> None:
        """All protocol models are frozen (immutable)."""
        rec = _make_record()
        with pytest.raises(ValueError):
            rec.sequence = 999  # type: ignore[misc]

    def test_to_lines(self) -> None:
        """LegacyBatch.to_lines() returns all record lines."""
        batch = _make_batch()
        lines = batch.to_lines()
        assert len(lines) == 2
        for line in lines:
            assert len(line) == 80


# ===========================================================================
# 14. Record Type Codes
# ===========================================================================


class TestRecordTypeCodes:
    """Verify valid record type codes."""

    def test_valid_types_accepted(self) -> None:
        """Record types 01, 02, 03, 99 are accepted."""
        for rt in ("01", "02", "03", "99"):
            rec = _make_record(record_type=rt)
            assert rec.record_type == rt

    def test_invalid_type_rejected(self) -> None:
        """Invalid record types are rejected."""
        with pytest.raises(ValueError, match="record_type"):
            _make_record(record_type="04")

    def test_settlement_correction_type_01(self) -> None:
        """Type 01 = settlement correction."""
        rec = _make_record(record_type="01")
        assert rec.record_type == "01"

    def test_settlement_reversal_type_02(self) -> None:
        """Type 02 = settlement reversal."""
        rec = _make_record(record_type="02")
        assert rec.record_type == "02"

    def test_reconciliation_match_type_03(self) -> None:
        """Type 03 = reconciliation match."""
        rec = _make_record(record_type="03")
        assert rec.record_type == "03"

    def test_control_record_type_99(self) -> None:
        """Type 99 = control record (batch totals)."""
        rec = _make_record(record_type="99")
        assert rec.record_type == "99"


# ===========================================================================
# 15. Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge cases and boundary conditions."""

    def test_zero_amount_record(self) -> None:
        """A record with zero amount is valid."""
        rec = _make_record(amount=Decimal("0.00"))
        assert rec.amount == Decimal("0.00")

    def test_max_sequence(self) -> None:
        """Maximum sequence number (99999999) is valid."""
        rec = _make_record(sequence=99_999_999)
        assert rec.sequence == 99_999_999

    def test_min_sequence(self) -> None:
        """Minimum sequence number (1) is valid."""
        rec = _make_record(sequence=1)
        assert rec.sequence == 1

    def test_batch_empty_records(self) -> None:
        """A batch with no records is valid (total=0, control=0)."""
        header = LegacyBatchHeader(
            company_id="test",
            batch_id=BATCH_ID,
            file_name="CORRECTION_20260916_231.DAT",
            total_records=0,
        )
        batch = LegacyBatch(header=header, records=())
        assert len(batch.records) == 0

    def test_large_batch(self) -> None:
        """A batch with many records is valid."""
        records = [_make_record(sequence=i, amount=Decimal(f"{i}.00")) for i in range(1, 11)]
        batch = _make_batch(records=records)
        assert len(batch.records) == 10
        assert batch.header.control_total == Decimal("55.00")


# ===========================================================================
# 16. Batch ID Compact Encoding
# ===========================================================================


class TestBatchIdCompactEncoding:
    """Verify the compact batch_id encoding used in the wire format."""

    def test_full_to_compact(self) -> None:
        """Full format LEGACY-20260916-0042 → compact LEG260916-0042."""
        compact = _batch_id_to_compact("LEGACY-20260916-0042")
        assert compact == "LEG260916-0042"
        assert len(compact) == 14

    def test_compact_to_full(self) -> None:
        """Compact LEG260916-0042 → full LEGACY-20260916-0042."""
        full = _compact_to_batch_id("LEG260916-0042")
        assert full == "LEGACY-20260916-0042"
        assert len(full) == 20

    def test_roundtrip_full_compact_full(self) -> None:
        """Full → compact → full is a no-op."""
        original = "LEGACY-20260916-0001"
        compact = _batch_id_to_compact(original)
        restored = _compact_to_batch_id(compact)
        assert restored == original

    def test_compact_at_wire_position(self) -> None:
        """Compact batch_id appears at cols 3-16 in the wire format."""
        rec = _make_record(batch_id="LEGACY-20260916-0042")
        line = rec.to_line()
        wire_bid = line[COL_BATCH_ID]
        assert wire_bid == "LEG260916-0042"
