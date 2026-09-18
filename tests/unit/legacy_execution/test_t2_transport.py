"""P6-07 T2 transport + artifact tests (TDD: RED first, then GREEN).

Covers the T2 seams only: artifact shape for FS-231 (X18-X23 as
amended by A1/A5), refuse-before-transport paths, S3 transport with
read-back verification and bounded retries (X24-X28/A4), the A2
recovery probe trio, and generic A5 SEQ derivation.

Uses :class:`FakeS3` exclusively — no network, no LLM, no wall-clock,
no new dependencies. Timestamps are fixed caller-supplied values.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from finance.legacy.protocol import (
    LegacyRecord,
    LegacyUploadError,
    _batch_id_to_compact,
)
from finance.legacy_execution.artifact import (
    ArtifactBindingError,
    ArtifactRefusedError,
    CorrectionRecordSpec,
    ExecutionIntent,
    OutboundArtifact,
    build_artifact,
    build_control_payload,
    build_type01_payload,
    clear_artifact_bindings,
    derive_file_name,
    derive_file_seq,
    verify_outbound_lines,
)
from finance.legacy_execution.transport import (
    HashMismatchError,
    PrefixEscapeError,
    TransportReceipt,
    TransportRefusedError,
    derive_outbound_key,
    put_verified,
    recover_receipt,
)
from finance.object_store.errors import ObjectNotFoundError
from finance.object_store.fake import FakeS3

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
BUCKET = "finsight-legacy-outbound"
COMPANY = "meridian"
BATCH = "LEGACY-20260916-0043"
SITUATION = "FS-2026-0916-00231"
EXECUTION_ID = "idem-fs231 correction-0001"


@pytest.fixture(autouse=True)
def _isolated_bindings() -> Any:
    """Reset the execution->batch binding registry between tests."""
    clear_artifact_bindings()
    yield
    clear_artifact_bindings()


def _fs231_intent(**overrides: Any) -> ExecutionIntent:
    """Build the golden FS-231 execution intent (10000.00 / 4812)."""
    fields: dict[str, Any] = {
        "action": "REPROCESS_LEGACY_RECORD",
        "amount_exact": Decimal("10000.00"),
        "account_code": "4812",
        "company_id": COMPANY,
        "situation_id": SITUATION,
        "scope_batch": None,
        "idempotency_key": EXECUTION_ID,
        "execution_id": EXECUTION_ID,
        "proposal_hash": "ph" * 32,
        "proposal_version": 3,
    }
    fields.update(overrides)
    return ExecutionIntent(**fields)


def _file_lines(artifact: OutboundArtifact) -> list[str]:
    """Split artifact bytes into 80-char lines (no trailing empty)."""
    text = artifact.file_bytes.decode("ascii")
    assert text.endswith("\n")
    return text[:-1].split("\n")


class _Journal:
    """Wrap FakeS3 counting PUTs and journaling identical-bytes evidence."""

    def __init__(self, inner: FakeS3) -> None:
        self._inner = inner
        self.puts = 0
        self.gets = 0
        self.journal: list[bytes] = []

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> Any:
        self.puts += 1
        self.journal.append(bytes(data))
        return self._inner.put_object(key, data, content_type)

    def get_object(self, key: str) -> tuple[bytes, Any]:
        self.gets += 1
        return self._inner.get_object(key)

    def exists(self, key: str) -> bool:
        return self._inner.exists(key)


class _FlakyPut(_Journal):
    """Fail the first ``failures`` PUTs, then delegate to FakeS3."""

    def __init__(self, inner: FakeS3, failures: int) -> None:
        super().__init__(inner)
        self._failures = failures

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> Any:
        if self._failures > 0:
            self.puts += 1
            self.journal.append(bytes(data))
            self._failures -= 1
            raise LegacyUploadError(f"injected S3 failure for {key!r}")
        return super().put_object(key, data, content_type)


class _AlwaysFail(_Journal):
    """PUT always fails — retry exhaustion path."""

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> Any:
        self.puts += 1
        self.journal.append(bytes(data))
        raise LegacyUploadError(f"persistent S3 failure for {key!r}")


class _TamperPut(_Journal):
    """Store one flipped byte so read-back never matches the artifact hash."""

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> Any:
        self.puts += 1
        self.journal.append(bytes(data))
        tampered = bytearray(data)
        tampered[30] ^= 0x01
        return self._inner.put_object(key, bytes(tampered), content_type)


# ---------------------------------------------------------------------------
# Artifact shape (FS-231 golden)
# ---------------------------------------------------------------------------


def test_fs231_artifact_shape() -> None:
    """FS-231: single 10000.00/4812 correction + control, 80-char lines."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    assert artifact.execution_id == EXECUTION_ID
    assert artifact.batch_id == BATCH
    assert artifact.file_name == "CORRECTION_20260916_231.DAT"
    assert artifact.record_count == 1
    assert artifact.control_total == Decimal("10000.00")
    assert isinstance(artifact.control_total, Decimal)

    lines = _file_lines(artifact)
    assert len(lines) == 2  # one data record + one control record
    for line in lines:
        assert len(line) == 80
    # A1: compact wire id in cols 3-16, logical form recoverable.
    assert lines[0][2:16] == _batch_id_to_compact(BATCH)
    assert "LEGACY-" not in lines[0][2:16]
    parsed = LegacyRecord.from_line(lines[0])
    assert parsed.batch_id == BATCH
    assert [p.sequence for p in (LegacyRecord.from_line(ln) for ln in lines)] == [1, 2]
    # Control total + whole-file sha are the read-back comparators.
    assert artifact.outbound_sha256 == hashlib.sha256(artifact.file_bytes).hexdigest()
    assert artifact.file_bytes.endswith(b"\n")
    assert b"\r" not in artifact.file_bytes


def test_type01_payload_layout_explicit() -> None:
    """Payload window: amount[0:20] right-justified, account[20:30], pad."""
    payload = build_type01_payload(Decimal("10000.00"), "4812")
    assert len(payload) == 50
    assert payload[0:20] == "            10000.00"
    assert payload[20:30] == "4812      "
    assert payload[30:50] == " " * 20
    control = build_control_payload(Decimal("10000.00"))
    assert len(control) == 50
    assert control[0:20] == "            10000.00"


def test_wire_21char_id_refused() -> None:
    """A line carrying the 21-char logical id on the wire refuses."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    good = _file_lines(artifact)[0]
    # Stuff the 21-char logical id into the 14-char wire window (cols 3-16).
    bad = good[:2] + BATCH[:14] + good[16:]
    assert len(bad) == 80
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        verify_outbound_lines(
            [bad], batch_id=BATCH, control_total=Decimal("10000.00")
        )


def test_empty_batch_refused() -> None:
    """Zero data records refuse before transport."""
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        build_artifact(_fs231_intent(), [], batch_id=BATCH, processing_date="20260916")


def test_oversized_batch_refused() -> None:
    """Record count above the configured ceiling refuses naming the count."""
    specs = [CorrectionRecordSpec(amount=Decimal("1.00"), account_code="4812")] * 3
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        build_artifact(
            _fs231_intent(),
            specs,
            batch_id=BATCH,
            processing_date="20260916",
            max_records=2,
        )


def test_non_2dp_amount_refused() -> None:
    """Amounts with more than 2 dp refuse (Decimal-only, cent-pinned)."""
    specs = [CorrectionRecordSpec(amount=Decimal("10.001"), account_code="4812")]
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        build_artifact(
            _fs231_intent(), specs, batch_id=BATCH, processing_date="20260916"
        )


def test_sequence_gap_refused() -> None:
    """A gap in the wire sequence refuses on self-verify."""
    artifact = build_artifact(
        _fs231_intent(),
        [Decimal("60.00"), Decimal("40.00")],
        batch_id=BATCH,
        processing_date="20260916",
    )
    lines = _file_lines(artifact)
    assert len(lines) == 3
    gap = [lines[0], lines[2]]  # drop sequence 2
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        verify_outbound_lines(
            gap, batch_id=BATCH, control_total=Decimal("100.00")
        )


def test_sequence_duplicate_refused() -> None:
    """A duplicated wire sequence refuses on self-verify."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    lines = _file_lines(artifact)
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        verify_outbound_lines(
            [lines[0], lines[0]], batch_id=BATCH, control_total=Decimal("10000.00")
        )


def test_checksum_failure_refused() -> None:
    """A flipped checksum nibble refuses naming the first bad line."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    lines = _file_lines(artifact)
    bad_first = lines[0][:-1] + ("0" if lines[0][-1] != "0" else "1")
    with pytest.raises(ArtifactRefusedError, match="line 1"):
        verify_outbound_lines(
            [bad_first, lines[1]], batch_id=BATCH, control_total=Decimal("10000.00")
        )


def test_control_mismatch_refused() -> None:
    """A control total that does not match the Decimal sum refuses."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    lines = _file_lines(artifact)
    with pytest.raises(ArtifactRefusedError, match="EXEC_ARTIFACT_REFUSED"):
        verify_outbound_lines(lines, batch_id=BATCH, control_total=Decimal("1.00"))


def test_batch_binding_second_id_forbidden() -> None:
    """Same execution key always resolves to the same batch id (X21)."""
    build_artifact(_fs231_intent(), None, batch_id=BATCH, processing_date="20260916")
    build_artifact(_fs231_intent(), None, batch_id=BATCH, processing_date="20260916")
    with pytest.raises(ArtifactBindingError, match="AUTHORIZATION_REPLAYED"):
        build_artifact(
            _fs231_intent(),
            None,
            batch_id="LEGACY-20260916-0044",
            processing_date="20260916",
        )


# ---------------------------------------------------------------------------
# Transport (E4)
# ---------------------------------------------------------------------------


def test_put_verified_success_receipt() -> None:
    """PUT + read-back match yields a receipt bound to execution + batch."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _Journal(FakeS3(COMPANY))
    receipt = put_verified(
        store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
    )
    assert isinstance(receipt, TransportReceipt)
    assert receipt.execution_id == EXECUTION_ID
    assert receipt.batch_id == BATCH
    assert receipt.key == f"{COMPANY}/{BATCH}/CORRECTION_20260916_231.DAT"
    assert receipt.sha256 == artifact.outbound_sha256
    assert receipt.byte_count == len(artifact.file_bytes)
    assert receipt.timestamp == NOW
    assert store.puts == 1


def test_tampered_bytes_readback_refused() -> None:
    """D4: bytes altered in flight refuse; the object is left for triage."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _TamperPut(FakeS3(COMPANY))
    with pytest.raises(HashMismatchError, match="EXEC_HASH_MISMATCH"):
        put_verified(
            store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
        )
    assert store.exists(derive_outbound_key(COMPANY, BATCH, artifact.file_name))


def test_prefix_escape_before_network() -> None:
    """D10: cross-company keys refuse before any network call (0 PUTs)."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _Journal(FakeS3(COMPANY))
    with pytest.raises(PrefixEscapeError, match="EXEC_PREFIX_ESCAPE"):
        put_verified(
            store, artifact, company_id="otherco", bucket_outbound=BUCKET, now=NOW
        )
    assert store.puts == 0
    assert store.gets == 0


def test_retry_then_success_identical_bytes() -> None:
    """Two injected failures then success: 3 PUTs, byte-identical retries."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _FlakyPut(FakeS3(COMPANY), failures=2)
    receipt = put_verified(
        store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
    )
    assert receipt.sha256 == artifact.outbound_sha256
    assert store.puts == 3
    assert all(chunk == artifact.file_bytes for chunk in store.journal)


def test_retry_exhaustion_refuses_identical_bytes() -> None:
    """Persistent S3 failure exhausts 1+3 attempts with identical bytes."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _AlwaysFail(FakeS3(COMPANY))
    with pytest.raises(TransportRefusedError, match="EXEC_TRANSPORT_REFUSED"):
        put_verified(
            store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
        )
    assert store.puts == 4  # 1 initial + 3 retries per A4
    assert len(store.journal) == 4
    assert all(chunk == artifact.file_bytes for chunk in store.journal)


# ---------------------------------------------------------------------------
# Recovery probe (A2)
# ---------------------------------------------------------------------------


def test_recovery_present_match_zero_puts() -> None:
    """Object present with matching hash: receipt recorded, 0 PUTs."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    inner = FakeS3(COMPANY)
    key = derive_outbound_key(COMPANY, BATCH, artifact.file_name)
    inner.put_object(key, artifact.file_bytes)
    store = _Journal(inner)
    receipt = recover_receipt(
        store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
    )
    assert receipt.sha256 == artifact.outbound_sha256
    assert receipt.key == key
    assert store.puts == 0


def test_recovery_absent_single_put() -> None:
    """Object absent: exactly one PUT+verify cycle on the probe path."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _Journal(FakeS3(COMPANY))
    receipt = recover_receipt(
        store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
    )
    assert receipt.sha256 == artifact.outbound_sha256
    assert store.puts == 1  # probe path: single PUT, no retry loop


def test_recovery_differs_refuses_no_reserialize() -> None:
    """Object present with differing bytes: refuse, never reserialize."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    inner = FakeS3(COMPANY)
    key = derive_outbound_key(COMPANY, BATCH, artifact.file_name)
    inner.put_object(key, b"DIFFERING-BYTES" * 64)
    store = _Journal(inner)
    with pytest.raises(HashMismatchError, match="EXEC_HASH_MISMATCH"):
        recover_receipt(
            store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
        )
    assert store.puts == 0
    raw, _ = inner.get_object(key)
    assert raw == b"DIFFERING-BYTES" * 64  # untouched, left for triage


def test_recovery_absent_propagates_transport_refusal() -> None:
    """Absent object + failing PUT on the probe path refuses after 1 try."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _AlwaysFail(FakeS3(COMPANY))
    with pytest.raises(TransportRefusedError, match="EXEC_TRANSPORT_REFUSED"):
        recover_receipt(
            store, artifact, company_id=COMPANY, bucket_outbound=BUCKET, now=NOW
        )
    assert store.puts == 1


# ---------------------------------------------------------------------------
# A5 generic naming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("situation_id", "expected_seq"),
    [
        ("FS-2026-0916-00231", "231"),
        ("FS-2026-0916-00042", "042"),
        ("FS-2026-0916-00107", "107"),
    ],
)
def test_a5_seq_derivation(situation_id: str, expected_seq: str) -> None:
    """SEQ is the last three digits of the situation sequence — never 231."""
    assert derive_file_seq(situation_id) == expected_seq
    assert derive_file_name("20260916", situation_id) == (
        f"CORRECTION_20260916_{expected_seq}.DAT"
    )


def test_a5_filename_flows_into_artifact_and_key() -> None:
    """A non-231 situation flows its own SEQ into file name and S3 key."""
    intent = _fs231_intent(
        situation_id="FS-2026-0916-00042",
        execution_id="idem-fs042-0001",
        idempotency_key="idem-fs042-0001",
    )
    artifact = build_artifact(intent, None, batch_id=BATCH, processing_date="20260916")
    assert artifact.file_name == "CORRECTION_20260916_042.DAT"
    assert "231" not in artifact.file_name
    key = derive_outbound_key(COMPANY, BATCH, artifact.file_name)
    assert key == f"{COMPANY}/{BATCH}/CORRECTION_20260916_042.DAT"


def test_absent_probe_key_raises_not_found() -> None:
    """Sanity: the deterministic probe key is absent before any PUT."""

    with pytest.raises(ObjectNotFoundError):
        FakeS3(COMPANY).get_object(f"{COMPANY}/{BATCH}/CORRECTION_20260916_231.DAT")


def test_receipt_timestamp_must_be_tz_aware() -> None:
    """Naive caller-supplied timestamps are rejected as input hygiene."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    store = _Journal(FakeS3(COMPANY))
    with pytest.raises(ValueError, match="tz-aware"):
        put_verified(
            store,
            artifact,
            company_id=COMPANY,
            bucket_outbound=BUCKET,
            now=datetime(2026, 9, 16, 12, 0, 0),
        )
    assert store.puts == 0


def test_wire_lines_sequence_types() -> None:
    """Helper contract: verify accepts any sequence of 80-char lines."""
    artifact = build_artifact(
        _fs231_intent(), None, batch_id=BATCH, processing_date="20260916"
    )
    lines: Sequence[str] = tuple(_file_lines(artifact))
    verify_outbound_lines(lines, batch_id=BATCH, control_total=Decimal("10000.00"))
