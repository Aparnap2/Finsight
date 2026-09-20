"""P6-08 integration: real track-A readers into track-B orchestrator.

Proves the two tracks compose through real modules — a §8 handoff,
fresh S3 reads, fake source ports, and the real minter produce a
VERIFIED report the frozen D1 gate accepts with zero adaptation.
No stand-in readers; thin adapters map track-A models to the
orchestrator shapes with equality assertions throughout.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from finance.business_rules.meridian import CompanyConfiguration
from finance.domain.verification import VerificationReport, VerificationVerdict
from finance.legacy.protocol import _batch_id_to_compact, _compute_checksum
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.object_store.fake import FakeS3
from finance.verification.audit import AuditLog
from finance.verification.orchestrator import (
    R1Observation,
    R2Observation,
    R3Observation,
    verify_execution,
)
from finance.verification.reason_codes import VERIFY_DIGEST_MISMATCH
from finance.verification.replay import ReplayStore
from finance.verification.rereads import (
    compose_legacy_after,
    derive_accepted_total,
    read_expected,
    read_pending,
    read_result_bytes,
)
from finance.verification.residual import compute_residual

COMPANY = "meridian"
SITUATION = "FS-2026-0916-00231"
BATCH = "LEGACY-20260916-0043"
EXECUTION = "idem-fs231-verify-0001"
T = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
RESULT_KEY = f"{COMPANY}/{BATCH}/RESULT_20260916_231.DAT"


def _result_bytes() -> bytes:
    """Single-AC RESULT bytes via the real frozen codec."""
    compact = _batch_id_to_compact(BATCH)
    body = "01" + compact + "00000001" + "AC" + "10000.00 POSTED 4812".ljust(50)[:50]
    assert len(body) == 76
    return (body + _compute_checksum(body) + "\n").encode("ascii")


def _handoff(result_sha: str) -> ExecutionHandoff:
    """Real §8 handoff claiming the FS-231 ACCEPTED execution."""
    return ExecutionHandoff(
        execution_id=EXECUTION,
        authorization_id="authz-fs231-001",
        proposal_hash="ab" * 32,
        proposal_version=1,
        company_id=COMPANY,
        situation_id=SITUATION,
        batch_id=BATCH,
        s3_outbound_key=f"{COMPANY}/{BATCH}/CORRECTION_20260916_231.DAT",
        outbound_sha256="0" * 64,
        control_total=Decimal("10000.00"),
        record_count=1,
        accepted_count=1,
        rejected_count=0,
        accepted_total=Decimal("10000.00"),
        rejected_total=Decimal("0.00"),
        result_key=RESULT_KEY,
        result_sha256=result_sha,
        outcome="ACCEPTED",
        unknown_flag=False,
        recorded_at=T,
    )


class _ExpectedPort:
    """Fake expected-settlement source (Sheets side, FS-231: 1000000)."""

    def read_expected(self, case_key: str) -> tuple[Decimal, datetime | None]:
        assert case_key == SITUATION
        return Decimal("1000000.00"), T


class _PendingPort:
    """Fake provider-pending source (Razorpay side, FS-231: 7500)."""

    def read_pending(self, batch_key: str) -> tuple[Decimal, datetime | None]:
        assert batch_key == BATCH
        return Decimal("7500.00"), T


def _readers(store: FakeS3):
    """Wire real track-A readers into track-B observation shapes."""

    def read_result(handoff: ExecutionHandoff) -> R1Observation:
        assert handoff.result_key is not None
        fresh = read_result_bytes(store, handoff.result_key, observed_at=T)
        return R1Observation(
            result_bytes=fresh.data,
            result_sha256=fresh.sha256,
            observed_at=T,
        )

    def read_legacy(handoff: ExecutionHandoff) -> R2Observation:
        assert handoff.result_key is not None
        fresh = read_result_bytes(store, handoff.result_key, observed_at=T)
        derived = derive_accepted_total(
            fresh.data, batch_id=handoff.batch_id, observed_at=T
        )
        assert derived.accepted_total == Decimal("10000.00")
        legacy_after = compose_legacy_after(
            Decimal("982500.00"), derived.accepted_total
        )
        assert legacy_after == Decimal("992500.00")
        return R2Observation(
            accepted_total=derived.accepted_total,
            prior_total=Decimal("982500.00"),
            legacy_after=legacy_after,
            observed_at=T,
        )

    def read_expectation(handoff: ExecutionHandoff) -> R3Observation:
        del handoff
        expected = read_expected(_ExpectedPort(), SITUATION, observed_at=T)
        pending = read_pending(_PendingPort(), BATCH, observed_at=T)
        residual = compute_residual(
            expected.total, Decimal("992500.00"), pending.pending
        )
        assert residual == Decimal("0.00")
        return R3Observation(
            expected=expected.total,
            pending=pending.pending,
            residual=residual,
            observed_at=T,
        )

    return read_result, read_legacy, read_expectation


def test_integration_verifies_fs231_end_to_end() -> None:
    """Real readers + real minter: VERIFIED report, D1 shape intact."""
    raw = _result_bytes()
    store = FakeS3(COMPANY)
    store.put_object(RESULT_KEY, raw)
    handoff = _handoff(hashlib.sha256(raw).hexdigest())
    read_result, read_legacy, read_expectation = _readers(store)
    log = AuditLog()

    report = verify_execution(
        handoff=handoff,
        read_result=read_result,
        read_legacy=read_legacy,
        read_expectation=read_expectation,
        checked_at=T,
        now=T,
        store=ReplayStore(),
        audit_log=log,
        for_situation_id=SITUATION,
    )
    assert isinstance(report, VerificationReport)
    assert report.situation_id == SITUATION
    assert report.execution_id == EXECUTION
    assert report.legacy_total_after == Decimal("992500.00")
    assert report.variance_after == Decimal("0.00")
    assert report.verdict.value == "VERIFIED"
    assert report.checked_at == T
    assert report.is_accepted(CompanyConfiguration().tolerance_minor)
    assert len(log) == 1


def test_integration_replay_returns_identical_report() -> None:
    """Second identical run replays the recorded report, mints nothing."""
    raw = _result_bytes()
    store = FakeS3(COMPANY)
    store.put_object(RESULT_KEY, raw)
    handoff = _handoff(hashlib.sha256(raw).hexdigest())
    shared = ReplayStore()
    first_log, second_log = AuditLog(), AuditLog()

    def _run(log: AuditLog) -> VerificationReport:
        read_result, read_legacy, read_expectation = _readers(store)
        return verify_execution(
            handoff=handoff,
            read_result=read_result,
            read_legacy=read_legacy,
            read_expectation=read_expectation,
            checked_at=T,
            now=T,
            store=shared,
            audit_log=log,
            for_situation_id=SITUATION,
        )

    first = _run(first_log)
    second = _run(second_log)
    assert second == first
    assert len(first_log) == 1
    assert len(second_log) == 1


def test_integration_tampered_result_fails() -> None:
    """Bytes differing from the handoff digest fail, never verify."""
    raw = _result_bytes()
    line = raw.decode("ascii").rstrip("\n")
    assert len(line) == 80
    body = line[:76]
    flipped = body[:75] + ("X" if body[75] != "X" else "Y")
    tampered = (flipped + _compute_checksum(flipped) + "\n").encode("ascii")
    assert len(tampered.decode("ascii").rstrip("\n")) == 80
    assert hashlib.sha256(tampered).hexdigest() != hashlib.sha256(raw).hexdigest()
    store = FakeS3(COMPANY)
    store.put_object(RESULT_KEY, tampered)
    handoff = _handoff(hashlib.sha256(raw).hexdigest())
    read_result, read_legacy, read_expectation = _readers(store)
    log = AuditLog()
    report = verify_execution(
        handoff=handoff,
        read_result=read_result,
        read_legacy=read_legacy,
        read_expectation=read_expectation,
        checked_at=T,
        now=T,
        store=ReplayStore(),
        audit_log=log,
        for_situation_id=SITUATION,
    )
    assert report.verdict is VerificationVerdict.FAILED
    assert report.is_accepted(CompanyConfiguration().tolerance_minor) is False
    assert log.entries[0].outcome == "FAILED"
    assert log.entries[0].reason_code == VERIFY_DIGEST_MISMATCH


def test_integration_missing_result_is_incomplete() -> None:
    """Absent RESULT starves the run to incomplete, never FAILED-as-proof."""
    raw = _result_bytes()
    store = FakeS3(COMPANY)
    handoff = _handoff(hashlib.sha256(raw).hexdigest())
    read_result, read_legacy, read_expectation = _readers(store)
    try:
        verify_execution(
            handoff=handoff,
            read_result=read_result,
            read_legacy=read_legacy,
            read_expectation=read_expectation,
            checked_at=T,
            now=T,
            store=ReplayStore(),
            audit_log=AuditLog(),
            for_situation_id=SITUATION,
        )
    except Exception as exc:
        assert "VERIFY_RESULT_MISSING" in str(exc)
    else:
        raise AssertionError("missing RESULT must not mint any report")
