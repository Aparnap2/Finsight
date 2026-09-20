"""P6-08 HOLD-A digest gate: R1 digest agreement precedes R2/R3 semantics.

Adversarial contract (F18/F22/F65): a digest-mismatched R1 must refuse
as FAILED with VERIFY_DIGEST_MISMATCH without invoking the R2/R3
readers at all — mismatched bytes must never reach semantic parsing.
The matching-digest path must still flow R1 -> R2 -> R3 in order.

No LLM, no network, no wall-clock, no new dependencies: fixed
tz-aware timestamps, hashlib digests, and Decimal-only money.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from finance.domain.verification import VerificationVerdict
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.verification.audit import AuditLog
from finance.verification.orchestrator import (
    R1Observation,
    R2Observation,
    R3Observation,
    verify_execution,
)
from finance.verification.reason_codes import VERIFY_DIGEST_MISMATCH
from finance.verification.replay import ReplayStore

SITUATION = "FS-2026-0916-00231"
EXECUTION = "exec-hold-a-digest-gate-001"
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

T_CHECK = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
T_NOW = datetime(2026, 9, 16, 12, 0, 30, tzinfo=UTC)
T_RECORDED = datetime(2026, 9, 16, 11, 55, 0, tzinfo=UTC)


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


def test_digest_mismatch_never_reaches_r2_semantics() -> None:
    """Arrange tampered R1 bytes; Act verify; Assert R2/R3 never invoked."""
    # Arrange.
    store, log = ReplayStore(), AuditLog()
    calls: list[str] = []
    tampered = RESULT_BYTES + b"\x00"

    def _r1_tampered(handoff: ExecutionHandoff) -> R1Observation:
        calls.append("r1")
        return R1Observation(
            result_bytes=tampered,
            result_sha256=RESULT_SHA,
            observed_at=T_CHECK,
        )

    def _r2_spy(handoff: ExecutionHandoff) -> R2Observation:
        calls.append("r2")
        return R2Observation(
            accepted_total=ACCEPTED,
            prior_total=PRIOR,
            legacy_after=LEGACY_AFTER,
            observed_at=T_CHECK,
        )

    def _r3_spy(handoff: ExecutionHandoff) -> R3Observation:
        calls.append("r3")
        return R3Observation(
            expected=EXPECTED,
            pending=PENDING,
            residual=RESIDUAL_ZERO,
            observed_at=T_CHECK,
        )

    # Act.
    report = verify_execution(
        handoff=_handoff(),
        read_result=_r1_tampered,
        read_legacy=_r2_spy,
        read_expectation=_r3_spy,
        checked_at=T_CHECK,
        now=T_NOW,
        store=store,
        audit_log=log,
    )
    # Assert.
    assert calls == ["r1"]
    assert report.verdict is VerificationVerdict.FAILED
    assert len(log) == 1
    entry = log.entries[0]
    assert entry.outcome == "FAILED"
    assert entry.reason_code == VERIFY_DIGEST_MISMATCH
    assert entry.reread_digests == (hashlib.sha256(tampered).hexdigest(),)
    assert store.lookup(EXECUTION) == report


def test_matching_digest_flows_r1_then_r2_then_r3() -> None:
    """Arrange agreeing digest; Act verify; Assert readers run R1 < R2 < R3."""
    # Arrange.
    store, log = ReplayStore(), AuditLog()
    calls: list[str] = []

    def _r1_spy(handoff: ExecutionHandoff) -> R1Observation:
        calls.append("r1")
        return R1Observation(
            result_bytes=RESULT_BYTES,
            result_sha256=RESULT_SHA,
            observed_at=T_CHECK,
        )

    def _r2_spy(handoff: ExecutionHandoff) -> R2Observation:
        calls.append("r2")
        return R2Observation(
            accepted_total=ACCEPTED,
            prior_total=PRIOR,
            legacy_after=LEGACY_AFTER,
            observed_at=T_CHECK,
        )

    def _r3_spy(handoff: ExecutionHandoff) -> R3Observation:
        calls.append("r3")
        return R3Observation(
            expected=EXPECTED,
            pending=PENDING,
            residual=RESIDUAL_ZERO,
            observed_at=T_CHECK,
        )

    # Act.
    report = verify_execution(
        handoff=_handoff(),
        read_result=_r1_spy,
        read_legacy=_r2_spy,
        read_expectation=_r3_spy,
        checked_at=T_CHECK,
        now=T_NOW,
        store=store,
        audit_log=log,
    )
    # Assert.
    assert calls == ["r1", "r2", "r3"]
    assert report.verdict is VerificationVerdict.VERIFIED
    assert len(log) == 1
