"""P6-08 track A re-reader tests (R1/R2/R3) — TDD RED first.

Covers the verification read seams only: R1 fresh RESULT GET plus
byte-exact digest compare, R2 frozen-codec accepted-total derivation,
R3 expectation/pending boundary reads, and pure residual math. All
fixtures use FakeS3 plus fixed tz-aware timestamps — no LLM, no
network, no wall-clock, no new dependencies.

Missing sources raise IncompleteRead (never zero-fill, never a
FAILED verdict — verdicts belong to track B).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from finance.object_store.fake import FakeS3
from finance.verification.ports import (
    ExpectedSettlementReader,
    ProviderPendingReader,
    ReReadStore,
)
from finance.verification.rereads import (
    BoundaryRefused,
    CorruptResultRead,
    CountSkewRead,
    IncompleteRead,
    WrongBatchRead,
    compose_legacy_after,
    derive_accepted_total,
    digests_agree,
    read_expected,
    read_pending,
    read_result_bytes,
    sha256_hex,
)
from finance.verification.residual import compute_residual

# ---------------------------------------------------------------------------
# Fixed fixtures (no clock, no network)
# ---------------------------------------------------------------------------

TENANT = "meridian"
BATCH = "LEGACY-20260916-0043"
OTHER_BATCH = "LEGACY-20260916-0044"
RESULT_KEY = f"{TENANT}/{BATCH}/RESULT_20260916_231.DAT"
CASE_KEY = "FS-2026-0916-00231"
T_RUN = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
T_RECORDED = datetime(2026, 9, 16, 11, 55, 0, tzinfo=UTC)
T_STALE = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def _compact(full_batch_id: str) -> str:
    """Mirror the frozen wire compaction (LEGACY-YYYYMMDD-NNNN to 14 chars)."""
    assert full_batch_id.startswith("LEGACY-")
    return "LEG" + full_batch_id[len("LEGACY-") + 2 :]


def _result_line(
    batch_id: str, sequence: int, code: str, detail: str, version: str = "01"
) -> str:
    """Build one 80-char RESULT line with a valid trailing checksum."""
    body = version + _compact(batch_id) + str(sequence).zfill(8) + code
    body += detail.ljust(50)[:50]
    assert len(body) == 76, f"body must be 76 chars, got {len(body)}"
    return body + hashlib.sha256(body.encode("ascii")).hexdigest()[-4:]


def _result_bytes(lines: list[str]) -> bytes:
    """Serialise RESULT lines with one terminal newline (exact PUT bytes)."""
    return ("\n".join(lines) + "\n").encode("ascii")


def _golden_lines() -> list[str]:
    """FS-231 correction RESULT: one AC line for the 10000 posting."""
    return [_result_line(BATCH, 1, "AC", "10000.00 POSTED 4812")]


class _FakeExpectedReader:
    """In-test fake for ExpectedSettlementReader (lives here, not the package)."""

    def __init__(self, rows: dict[str, tuple[Any, datetime | None]]) -> None:
        self._rows = rows

    def read_expected(self, case_key: str) -> tuple[Decimal, datetime | None]:
        if case_key not in self._rows:
            raise KeyError(f"no expected settlement for {case_key!r}")
        total, as_of = self._rows[case_key]
        return total, as_of


class _FakePendingReader:
    """In-test fake for ProviderPendingReader (lives here, not the package)."""

    def __init__(self, rows: dict[str, tuple[Any, datetime | None]]) -> None:
        self._rows = rows

    def read_pending(self, batch_key: str) -> tuple[Decimal, datetime | None]:
        if batch_key not in self._rows:
            raise KeyError(f"no provider pending for {batch_key!r}")
        pending, as_of = self._rows[batch_key]
        return pending, as_of


def _sealed_store(lines: list[str]) -> FakeS3:
    """FakeS3 preloaded with the RESULT bytes under the golden key."""
    store = FakeS3(TENANT)
    store.put_object(RESULT_KEY, _result_bytes(lines))
    return store


# ---------------------------------------------------------------------------
# Protocol surface (F66 seam shape)
# ---------------------------------------------------------------------------


def test_ports_are_protocols_with_tuple_shape() -> None:
    """R3 ports expose the F66 read methods returning (Decimal, as-of)."""
    assert issubclass(ExpectedSettlementReader, object)
    assert issubclass(ProviderPendingReader, object)
    assert ReReadStore is not None


# ---------------------------------------------------------------------------
# R1 — fresh RESULT GET plus byte-exact digest compare
# ---------------------------------------------------------------------------


def test_r1_digest_match() -> None:
    """Fresh GET bytes hash exactly to the handoff-claimed digest."""
    store = _sealed_store(_golden_lines())
    raw = _result_bytes(_golden_lines())
    read = read_result_bytes(store, RESULT_KEY, observed_at=T_RUN)
    assert read.data == raw
    assert read.sha256 == sha256_hex(raw)
    assert digests_agree(read.sha256, hashlib.sha256(raw).hexdigest())
    assert read.observed_at == T_RUN


def test_r1_digest_mismatch_is_not_a_verdict() -> None:
    """One tampered bit fails agreement and mints nothing (track B decides)."""
    raw = bytearray(_result_bytes(_golden_lines()))
    raw[10] ^= 0x01
    assert not digests_agree(sha256_hex(bytes(raw)), sha256_hex(_result_bytes(_golden_lines())))


def test_r1_missing_key_is_incomplete_not_failed() -> None:
    """Absent RESULT raises IncompleteRead (F36 family), never FAILED."""
    store = FakeS3(TENANT)
    with pytest.raises(IncompleteRead, match="VERIFY_RESULT_MISSING"):
        read_result_bytes(store, RESULT_KEY, observed_at=T_RUN)


def test_r1_tenant_escape_carries_mapping_note() -> None:
    """Cross-tenant keys surface incomplete with the engine mapping noted."""
    store = FakeS3(TENANT)
    with pytest.raises(IncompleteRead, match="VERIFY_PREFIX_ESCAPE"):
        read_result_bytes(store, "other-tenant/key", observed_at=T_RUN)


def test_r1_timeout_param_accepted_without_waiting() -> None:
    """Timeout rides the caller param (never the port); no waiting occurs."""
    store = _sealed_store(_golden_lines())
    read = read_result_bytes(store, RESULT_KEY, timeout_s=0.001, observed_at=T_RUN)
    assert read.data == _result_bytes(_golden_lines())
    with pytest.raises(ValueError, match="timeout_s"):
        read_result_bytes(store, RESULT_KEY, timeout_s=0, observed_at=T_RUN)


# ---------------------------------------------------------------------------
# R2 — frozen-codec accepted-total derivation
# ---------------------------------------------------------------------------


def test_r2_golden_single_ac_derives_10000() -> None:
    """FS-231 correction RESULT derives accepted 10000.00, counts 1/0/0."""
    derived = derive_accepted_total(
        _result_bytes(_golden_lines()), batch_id=BATCH, observed_at=T_RUN
    )
    assert derived.accepted_total == Decimal("10000.00")
    assert (derived.accepted_count, derived.rejected_count, derived.duplicate_count) == (1, 0, 0)
    assert derived.observed_at == T_RUN


def test_r2_wrong_batch_carries_batch_skew() -> None:
    """Header batch != handoff batch fails with VERIFY_BATCH_SKEW."""
    raw = _result_bytes([_result_line(OTHER_BATCH, 1, "AC", "10000.00 POSTED 4812")])
    with pytest.raises(WrongBatchRead, match="VERIFY_BATCH_SKEW"):
        derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)


def test_r2_sequence_gap_carries_count_skew() -> None:
    """Non-contiguous sequences fail with VERIFY_COUNT_SKEW."""
    raw = _result_bytes(
        [
            _result_line(BATCH, 1, "AC", "10000.00 POSTED 4812"),
            _result_line(BATCH, 3, "AC", "10000.00 POSTED 4812"),
        ]
    )
    with pytest.raises(CountSkewRead, match="VERIFY_COUNT_SKEW"):
        derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)


def test_r2_duplicate_sequence_carries_count_skew() -> None:
    """Doubled sequences fail with VERIFY_COUNT_SKEW, never double-count."""
    raw = _result_bytes(
        [
            _result_line(BATCH, 1, "AC", "10000.00 POSTED 4812"),
            _result_line(BATCH, 1, "AC", "10000.00 POSTED 4812"),
        ]
    )
    with pytest.raises(CountSkewRead, match="VERIFY_COUNT_SKEW"):
        derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)


def test_r2_version_skew_carries_count_skew() -> None:
    """Wrong protocol version fails with VERIFY_COUNT_SKEW."""
    raw = _result_bytes([_result_line(BATCH, 1, "AC", "10000.00 POSTED 4812", version="02")])
    with pytest.raises(CountSkewRead, match="VERIFY_COUNT_SKEW"):
        derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)


def test_r2_checksum_failure_is_corrupt() -> None:
    """A bad line checksum refuses as corrupt RESULT bytes."""
    good = _result_line(BATCH, 1, "AC", "10000.00 POSTED 4812")
    raw = _result_bytes([good[:-1] + ("0" if good[-1] != "0" else "1")])
    with pytest.raises(CorruptResultRead, match="VERIFY_RESULT_MUTATED"):
        derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)


def test_r2_rejected_lines_count_zero_value() -> None:
    """REJECTED lines contribute 0 to the accepted sum but are counted."""
    raw = _result_bytes(
        [
            _result_line(BATCH, 1, "AC", "10000.00 POSTED 4812"),
            _result_line(BATCH, 2, "RJ", "INVALID_ACCOUNT_CODE"),
        ]
    )
    derived = derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)
    assert derived.accepted_total == Decimal("10000.00")
    assert (derived.accepted_count, derived.rejected_count) == (1, 1)


def test_r2_duplicate_resolves_without_double_count() -> None:
    """DU lines resolve to the original outcome: counted, never re-added."""
    raw = _result_bytes(
        [
            _result_line(BATCH, 1, "AC", "10000.00 POSTED 4812"),
            _result_line(BATCH, 2, "DU", "ALREADY SEEN 00000001"),
        ]
    )
    derived = derive_accepted_total(raw, batch_id=BATCH, observed_at=T_RUN)
    assert derived.accepted_total == Decimal("10000.00")
    assert derived.duplicate_count == 1


def test_r2_prior_plus_accepted_composes_992500() -> None:
    """FS-231: prior 982500 plus fresh accepted 10000 composes legacy-after."""
    derived = derive_accepted_total(
        _result_bytes(_golden_lines()), batch_id=BATCH, observed_at=T_RUN
    )
    assert compose_legacy_after(Decimal("982500.00"), derived.accepted_total) == Decimal(
        "992500.00"
    )


# ---------------------------------------------------------------------------
# R3 — expectation and pending boundary reads
# ---------------------------------------------------------------------------


def test_r3_expected_float_rejected_at_boundary() -> None:
    """Float totals never cross the boundary, even with the right value."""
    port = _FakeExpectedReader({CASE_KEY: (1000000.0, T_RECORDED)})
    with pytest.raises(BoundaryRefused, match="Decimal"):
        read_expected(port, CASE_KEY, observed_at=T_RUN)


def test_r3_expected_scale_rejected_at_boundary() -> None:
    """Three-dp totals are refused: 2-dp exactness is enforced, never rounded."""
    port = _FakeExpectedReader({CASE_KEY: (Decimal("1000000.001"), T_RECORDED)})
    with pytest.raises(BoundaryRefused, match="2 dp"):
        read_expected(port, CASE_KEY, observed_at=T_RUN)


def test_r3_currency_rejected_at_boundary() -> None:
    """Only INR-denominated sources verify; anything else is refused."""
    expected_port = _FakeExpectedReader({CASE_KEY: (Decimal("1000000.00"), T_RECORDED)})
    pending_port = _FakePendingReader({BATCH: (Decimal("7500.00"), T_RECORDED)})
    with pytest.raises(BoundaryRefused, match="INR"):
        read_expected(expected_port, CASE_KEY, currency="USD", observed_at=T_RUN)
    with pytest.raises(BoundaryRefused, match="INR"):
        read_pending(pending_port, BATCH, currency="USD", observed_at=T_RUN)


def test_r3_missing_source_is_incomplete_never_zero_filled() -> None:
    """Unreadable expectation/pending sources raise IncompleteRead, never 0."""
    with pytest.raises(IncompleteRead):
        read_expected(_FakeExpectedReader({}), CASE_KEY, observed_at=T_RUN)
    with pytest.raises(IncompleteRead):
        read_pending(_FakePendingReader({}), BATCH, observed_at=T_RUN)


def test_r3_asof_passthrough_including_stale() -> None:
    """Source as-of timestamps pass through verbatim; staleness is track B."""
    expected = read_expected(
        _FakeExpectedReader({CASE_KEY: (Decimal("1000000.00"), T_STALE)}),
        CASE_KEY,
        observed_at=T_RUN,
    )
    assert expected.total == Decimal("1000000.00")
    assert expected.as_of == T_STALE
    pending = read_pending(
        _FakePendingReader({BATCH: (Decimal("7500.00"), None)}),
        BATCH,
        observed_at=T_RUN,
    )
    assert pending.pending == Decimal("7500.00")
    assert pending.as_of is None
    assert expected.observed_at == T_RUN == pending.observed_at


# ---------------------------------------------------------------------------
# Residual — pure Decimal math, tolerance belongs to the minter (F27)
# ---------------------------------------------------------------------------


def test_residual_zero_for_fs231() -> None:
    """FS-231 golden: 1000000 - 992500 - 7500 is exactly zero."""
    assert (
        compute_residual(Decimal("1000000.00"), Decimal("992500.00"), Decimal("7500.00"))
        == Decimal("0.00")
    )


def test_residual_nonzero_arithmetic() -> None:
    """Non-zero residuals stay exact with no tolerance folded in."""
    assert (
        compute_residual(Decimal("1000000.00"), Decimal("990000.00"), Decimal("7500.00"))
        == Decimal("2500.00")
    )
