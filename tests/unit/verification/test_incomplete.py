"""P6-08 HOLD-B incomplete-path semantics suite (F36, F40).

Failing-first tests for the specified incomplete-run contract: a missing
or unreadable R1/R2/R3 source ends the run INCOMPLETE (never
FAILED-as-verdict) with exactly one audit entry carrying a registered
incomplete code, no VerificationReport minted, nothing replayable in the
store, and no zero-filled totals anywhere. A genuinely corrupt RESULT
(checksum failure surfaced as a FAILED-code signal) still mints FAILED,
proving the suite does not conflate incomplete-missing with
corrupt-invalid.

No S3, no network, no LLM, no wall-clock: fixed tz-aware timestamps and
stub readers raising the existing ReaderFailed signal per the track B
call convention.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from finance.domain.verification import VerificationVerdict
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.verification.audit import AuditLog
from finance.verification.orchestrator import (
    R1Observation,
    R2Observation,
    R3Observation,
    ReaderFailed,
    VerificationRefused,
    verify_execution,
)
from finance.verification.reason_codes import (
    INCOMPLETE_CODES,
    VERIFY_RESULT_MISSING,
    VERIFY_RESULT_MUTATED,
    is_registered,
)
from finance.verification.replay import ReplayStore

SITUATION = "FS-2026-0916-00231"
EXECUTION = "exec-holdb-incomplete-001"
BATCH = "LEGACY-20260916-0043"
RESULT_KEY = "meridian/LEGACY-20260916-0043/RESULT_20260916_231.DAT"
RESULT_BYTES = b"FS-231|LEGACY-20260916-0043|AC:10000.00|4812\n"
RESULT_SHA = hashlib.sha256(RESULT_BYTES).hexdigest()

PRIOR = Decimal("982500.00")
ACCEPTED = Decimal("10000.00")
LEGACY_AFTER = Decimal("992500.00")
EXPECTED = Decimal("1000000.00")
PENDING = Decimal("7500.00")
RESIDUAL_ZERO = Decimal("0.00")

T_RECORDED = datetime(2026, 9, 16, 11, 55, 0, tzinfo=UTC)
T_CHECK = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
T_NOW = datetime(2026, 9, 16, 12, 0, 30, tzinfo=UTC)


def _handoff(**overrides: Any) -> ExecutionHandoff:
    """Build the FS-231 ACCEPTED handoff; overrides replace single fields."""
    fields: dict[str, Any] = {
        "execution_id": EXECUTION,
        "authorization_id": "g7-fs231-auth-001",
        "proposal_hash": "ph-fs231-001",
        "proposal_version": 3,
        "company_id": "meridian",
        "situation_id": SITUATION,
        "batch_id": BATCH,
        "s3_outbound_key": "meridian/LEGACY-20260916-0043/OUTBOUND_231.DAT",
        "outbound_sha256": "b" * 64,
        "control_total": Decimal("10000.00"),
        "record_count": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "accepted_total": ACCEPTED,
        "rejected_total": Decimal("0.00"),
        "result_key": RESULT_KEY,
        "result_sha256": RESULT_SHA,
        "outcome": "ACCEPTED",
        "unknown_flag": False,
        "recorded_at": T_RECORDED,
    }
    fields.update(overrides)
    return ExecutionHandoff(**fields)


def _r1_ok(handoff: ExecutionHandoff) -> R1Observation:
    """Return the digest-agreeing R1 stub observation."""
    return R1Observation(
        result_bytes=RESULT_BYTES,
        result_sha256=RESULT_SHA,
        observed_at=T_CHECK,
    )


def _r2_ok(handoff: ExecutionHandoff) -> R2Observation:
    """Return the FS-231 R2 stub observation (982500 + 10000 = 992500)."""
    return R2Observation(
        accepted_total=ACCEPTED,
        prior_total=PRIOR,
        legacy_after=LEGACY_AFTER,
        observed_at=T_CHECK,
    )


def _r3_ok(handoff: ExecutionHandoff) -> R3Observation:
    """Return the FS-231 R3 stub observation (residual exactly zero)."""
    return R3Observation(
        expected=EXPECTED,
        pending=PENDING,
        residual=RESIDUAL_ZERO,
        observed_at=T_CHECK,
    )


def _run(
    handoff: ExecutionHandoff,
    store: ReplayStore,
    log: AuditLog,
    **overrides: Any,
) -> Any:
    """Run the orchestrator with FS-231 stub readers and fixed timestamps."""
    params: dict[str, Any] = {
        "handoff": handoff,
        "read_result": _r1_ok,
        "read_legacy": _r2_ok,
        "read_expectation": _r3_ok,
        "checked_at": T_CHECK,
        "now": T_NOW,
        "store": store,
        "audit_log": log,
    }
    params.update(overrides)
    return verify_execution(**params)


def _assert_incomplete_run(
    store: ReplayStore,
    log: AuditLog,
    exc_code: str | None,
) -> None:
    """Assert the shared INCOMPLETE contract: one entry, code kept, no mint."""
    assert exc_code == VERIFY_RESULT_MISSING
    assert exc_code in INCOMPLETE_CODES
    assert is_registered(exc_code)
    assert len(log) == 1
    entry = log.entries[0]
    assert entry.outcome == "INCOMPLETE"
    assert entry.reason_code == VERIFY_RESULT_MISSING
    assert entry.reason_code in INCOMPLETE_CODES
    assert entry.report_hash is None
    assert store.lookup(EXECUTION) is None


class TestMissingR1Incomplete:
    """Missing R1 source ends INCOMPLETE per F36 (never FAILED-as-verdict)."""

    def test_missing_r1_source_ends_incomplete(self) -> None:
        """Arrange R1 signalling missing; Act verify; Assert one entry, no mint."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _missing(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "RESULT key absent")

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_result=_missing)
        # Assert.
        _assert_incomplete_run(store, log, exc_info.value.code)


class TestMissingR2Incomplete:
    """Missing R2 source ends INCOMPLETE per F36/F65 (never zero-filled)."""

    def test_missing_r2_source_ends_incomplete(self) -> None:
        """Arrange R2 signalling missing; Act verify; Assert one entry, no mint."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _missing(handoff: ExecutionHandoff) -> R2Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "legacy total unreadable")

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_legacy=_missing)
        # Assert.
        _assert_incomplete_run(store, log, exc_info.value.code)


class TestMissingR3Incomplete:
    """Missing R3 source ends INCOMPLETE per F36/F66 (never zero-filled)."""

    def test_missing_r3_source_ends_incomplete(self) -> None:
        """Arrange R3 signalling missing; Act verify; Assert one entry, no mint."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _missing(handoff: ExecutionHandoff) -> R3Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "expectation unreadable")

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_expectation=_missing)
        # Assert.
        _assert_incomplete_run(store, log, exc_info.value.code)


class TestCorruptR2BytesSurfacedIncomplete:
    """Unreadable R2 bytes surfaced as incomplete stay INCOMPLETE (F36)."""

    def test_unreadable_r2_bytes_end_incomplete(self) -> None:
        """Arrange corrupt R2 bytes as incomplete; Act; Assert one entry, no mint."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _unreadable(handoff: ExecutionHandoff) -> R2Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R2 bytes corrupt/unreadable")

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_legacy=_unreadable)
        # Assert.
        _assert_incomplete_run(store, log, exc_info.value.code)


class TestAuditEntryCountInvariant:
    """Every incomplete run records exactly one INCOMPLETE audit entry (F6)."""

    @pytest.mark.parametrize("case", ["r1-missing", "r2-missing", "r3-missing"])
    def test_incomplete_records_exactly_one_entry(self, case: str) -> None:
        """Arrange each missing source; Act verify; Assert len == 1, INCOMPLETE."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _r1_missing(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R1 absent")

        def _r2_missing(handoff: ExecutionHandoff) -> R2Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R2 absent")

        def _r3_missing(handoff: ExecutionHandoff) -> R3Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R3 absent")

        overrides: dict[str, Any] = {
            "r1-missing": {"read_result": _r1_missing},
            "r2-missing": {"read_legacy": _r2_missing},
            "r3-missing": {"read_expectation": _r3_missing},
        }[case]
        # Act.
        with pytest.raises(VerificationRefused):
            _run(_handoff(), store, log, **overrides)
        # Assert.
        assert len(log) == 1
        entry = log.entries[0]
        assert entry.outcome == "INCOMPLETE"
        assert entry.reason_code in INCOMPLETE_CODES
        assert entry.reason_code is not None and is_registered(entry.reason_code)


class TestNoReportMinted:
    """Incomplete runs mint nothing replayable: the store stays empty (F40)."""

    @pytest.mark.parametrize("case", ["r1-missing", "r2-missing", "r3-missing"])
    def test_incomplete_holds_no_report_for_execution(self, case: str) -> None:
        """Arrange each missing source; Act verify; Assert store empty, no hash."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _r1_missing(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R1 absent")

        def _r2_missing(handoff: ExecutionHandoff) -> R2Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R2 absent")

        def _r3_missing(handoff: ExecutionHandoff) -> R3Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "R3 absent")

        overrides: dict[str, Any] = {
            "r1-missing": {"read_result": _r1_missing},
            "r2-missing": {"read_legacy": _r2_missing},
            "r3-missing": {"read_expectation": _r3_missing},
        }[case]
        # Act.
        with pytest.raises(VerificationRefused):
            _run(_handoff(), store, log, **overrides)
        # Assert: nothing minted, nothing to replay, no zero-filled totals exist.
        assert store.lookup(EXECUTION) is None
        assert log.entries[0].report_hash is None


class TestIncompleteVsCorruptDistinction:
    """Incomplete-missing never conflates with corrupt-invalid (F34 vs F36)."""

    def test_checksum_failure_mints_failed_with_its_code(self) -> None:
        """Arrange R1 FAILED-code signal; Act verify; Assert FAILED minted."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _checksum_failed(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_RESULT_MUTATED, "line checksum failure")

        # Act.
        report = _run(_handoff(), store, log, read_result=_checksum_failed)
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert report.is_accepted(Decimal("100")) is False
        assert log.entries[0].outcome == "FAILED"
        assert log.entries[0].reason_code == VERIFY_RESULT_MUTATED
        assert store.lookup(EXECUTION) == report

    def test_missing_and_corrupt_paths_stay_distinct(self) -> None:
        """Arrange both signals; Act each run; Assert INCOMPLETE versus FAILED."""
        # Arrange.
        def _missing(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_RESULT_MISSING, "RESULT key absent")

        def _checksum_failed(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_RESULT_MUTATED, "line checksum failure")

        missing_store, missing_log = ReplayStore(), AuditLog()
        corrupt_store, corrupt_log = ReplayStore(), AuditLog()
        # Act.
        with pytest.raises(VerificationRefused) as missing_exc:
            _run(_handoff(), missing_store, missing_log, read_result=_missing)
        corrupt_report = _run(
            _handoff(), corrupt_store, corrupt_log, read_result=_checksum_failed
        )
        # Assert: the two paths diverge exactly as specified.
        assert missing_exc.value.code == VERIFY_RESULT_MISSING
        assert missing_log.entries[0].outcome == "INCOMPLETE"
        assert missing_store.lookup(EXECUTION) is None
        assert corrupt_report.verdict is VerificationVerdict.FAILED
        assert corrupt_log.entries[0].outcome == "FAILED"
        assert corrupt_log.entries[0].reason_code == VERIFY_RESULT_MUTATED
        assert corrupt_store.lookup(EXECUTION) == corrupt_report
