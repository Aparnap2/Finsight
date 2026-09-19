"""P6-08 track B verification tests — minter, registry, replay, audit, orchestrator.

TDD RED-first suite for the track B ownership surface only
(``finance/verification/{__init__,reason_codes,minter,replay,audit,clock,
orchestrator}``). Sibling track A reader modules are treated as absent:
R1/R2/R3 observations arrive through minimal local stub callables shaped
exactly as the track B contract specifies (``{result_bytes, result_sha256}``,
``{accepted_total, prior_total, legacy_after}``,
``{expected, pending, residual}``, each with ``observed_at``).

Golden path replays FS-231 end to end: prior ``982500`` plus correction
``10000`` equals legacy-after ``992500``; expected ``1000000`` minus
legacy-after minus pending ``7500`` leaves residual ``0``; the minted
``VERIFIED`` report passes the frozen D1 acceptance shape with zero
adaptation. No LLM, no network, no wall-clock, no new dependencies:
fixed tz-aware timestamps and ``hashlib`` digests only.
"""

from __future__ import annotations

import ast
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from finance.business_rules.meridian import CompanyConfiguration
from finance.domain.verification import VerificationReport, VerificationVerdict
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.verification.audit import AuditEntry, AuditLog, digest_handoff
from finance.verification.clock import FUTURE_SKEW_BUDGET, assess_clock
from finance.verification.minter import MintRefused, mint_report
from finance.verification.orchestrator import (
    R1Observation,
    R2Observation,
    R3Observation,
    ReaderFailed,
    VerificationRefused,
    verify_execution,
)
from finance.verification.reason_codes import (
    FAILED_CODES,
    INCOMPLETE_CODES,
    REASON_REGISTRY,
    VERIFY_BATCH_SKEW,
    VERIFY_CASE_SKEW,
    VERIFY_CLOCK_SKEW,
    VERIFY_CONTROL_SKEW,
    VERIFY_COUNT_SKEW,
    VERIFY_DIGEST_MISMATCH,
    VERIFY_DOUBLE_MINT_REFUSED,
    VERIFY_HANDOFF_CORRUPT,
    VERIFY_PREFIX_ESCAPE,
    VERIFY_RESULT_MISSING,
    VERIFY_RESULT_MUTATED,
    VERIFY_STALE_REPLAY,
    VERIFY_TOLERANCE_EXCEEDED,
    VERIFY_UNAUTHORIZED_EXECUTION,
    is_registered,
    require_failed_code,
    require_registered,
)
from finance.verification.replay import ReplayStore

# ---------------------------------------------------------------------------
# Fixed fixtures (no clock, no network, Decimal-only money)
# ---------------------------------------------------------------------------

SITUATION = "FS-2026-0916-00231"
EXECUTION = "exec-fs231-correction-001"
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
TOLERANCE = Decimal("100")

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
) -> VerificationReport:
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


def _mint_verified(**overrides: Any) -> VerificationReport:
    """Mint the FS-231 VERIFIED report; overrides replace single fields."""
    params: dict[str, Any] = {
        "situation_id": SITUATION,
        "execution_id": EXECUTION,
        "legacy_total_after": LEGACY_AFTER,
        "variance_after": RESIDUAL_ZERO,
        "verdict": VerificationVerdict.VERIFIED,
        "checked_at": T_CHECK,
        "residual_within_tolerance": True,
        "digests_agree": True,
        "counts_reconcile": True,
        "reason_code": None,
        "recorded": {},
    }
    params.update(overrides)
    return mint_report(**params)


# ---------------------------------------------------------------------------
# Reason-code registry: closed world, single meaning per code
# ---------------------------------------------------------------------------


class TestReasonRegistry:
    """The registry is frozen: every usable code is known, the rest refuse."""

    def test_registry_covers_f28_plus_f64_plus_incomplete_plus_replay(self) -> None:
        """Arrange the contract code set; Act read registry; Assert exact cover."""
        # Arrange.
        expected = {
            VERIFY_DIGEST_MISMATCH,
            VERIFY_RESULT_MUTATED,
            VERIFY_BATCH_SKEW,
            VERIFY_COUNT_SKEW,
            VERIFY_CONTROL_SKEW,
            VERIFY_TOLERANCE_EXCEEDED,
            VERIFY_CASE_SKEW,
            VERIFY_UNAUTHORIZED_EXECUTION,
            VERIFY_CLOCK_SKEW,
            VERIFY_DOUBLE_MINT_REFUSED,
            VERIFY_RESULT_MISSING,
            VERIFY_HANDOFF_CORRUPT,
            VERIFY_STALE_REPLAY,
            VERIFY_PREFIX_ESCAPE,
        }
        # Act.
        codes = set(REASON_REGISTRY)
        # Assert.
        assert codes == expected
        assert all(isinstance(text, str) and text for text in REASON_REGISTRY.values())

    def test_failed_codes_are_exactly_the_f28_nine(self) -> None:
        """Arrange F28; Act read FAILED_CODES; Assert nine, no refusal codes."""
        # Arrange.
        expected = {
            VERIFY_DIGEST_MISMATCH,
            VERIFY_RESULT_MUTATED,
            VERIFY_BATCH_SKEW,
            VERIFY_COUNT_SKEW,
            VERIFY_CONTROL_SKEW,
            VERIFY_TOLERANCE_EXCEEDED,
            VERIFY_CASE_SKEW,
            VERIFY_UNAUTHORIZED_EXECUTION,
            VERIFY_CLOCK_SKEW,
        }
        # Act + Assert.
        assert expected == FAILED_CODES
        assert VERIFY_DOUBLE_MINT_REFUSED not in FAILED_CODES
        assert VERIFY_STALE_REPLAY not in FAILED_CODES
        assert VERIFY_RESULT_MISSING not in FAILED_CODES
        assert VERIFY_HANDOFF_CORRUPT not in FAILED_CODES

    def test_incomplete_codes_mint_nothing(self) -> None:
        """Arrange refusal codes; Act read set; Assert missing + corrupt only."""
        # Act + Assert.
        assert {VERIFY_RESULT_MISSING, VERIFY_HANDOFF_CORRUPT} == INCOMPLETE_CODES

    def test_unknown_code_refused_at_construction(self) -> None:
        """Arrange an unregistered code; Act require; Assert ValueError."""
        # Arrange + Act + Assert.
        assert not is_registered("VERIFY_NOPE")
        with pytest.raises(ValueError):
            require_registered("VERIFY_NOPE")
        with pytest.raises(ValueError):
            require_failed_code("VERIFY_NOPE")
        with pytest.raises(ValueError):
            require_failed_code(VERIFY_RESULT_MISSING)


# ---------------------------------------------------------------------------
# Minter: VERIFIED golden, conjunction, FAILED codes, double-mint
# ---------------------------------------------------------------------------


class TestMintVerifiedGolden:
    """FS-231 mints VERIFIED with the exact frozen six-field shape."""

    def test_fs231_verified_golden_field_by_field(self) -> None:
        """Arrange FS-231 inputs; Act mint; Assert every D1 field exactly."""
        # Arrange + Act.
        report = _mint_verified()
        # Assert.
        assert report.situation_id == SITUATION
        assert report.execution_id == EXECUTION
        assert report.legacy_total_after == Decimal("992500.00")
        assert report.variance_after == Decimal("0.00")
        assert report.verdict is VerificationVerdict.VERIFIED
        assert report.checked_at == T_CHECK
        assert set(type(report).model_fields) == {
            "situation_id",
            "execution_id",
            "legacy_total_after",
            "variance_after",
            "verdict",
            "checked_at",
        }

    def test_verified_passes_close_gate_with_zero_adaptation(self) -> None:
        """Arrange the golden report; Act acceptance; Assert D1 close-ready."""
        # Arrange.
        report = _mint_verified()
        frozen_tolerance = CompanyConfiguration().tolerance_minor
        # Act.
        accepted = report.is_accepted(frozen_tolerance)
        # Assert.
        assert frozen_tolerance == Decimal("100")
        assert accepted is True
        assert abs(report.variance_after) <= frozen_tolerance

    def test_tolerance_boundary_inclusive_at_minter(self) -> None:
        """Arrange residual exactly 100; Act mint VERIFIED; Assert accepted."""
        # Arrange + Act.
        report = _mint_verified(variance_after=Decimal("100.00"))
        # Assert.
        assert report.is_accepted(TOLERANCE) is True

    def test_verified_conjunction_requires_all_three_flags(self) -> None:
        """Arrange each flag False; Act mint VERIFIED; Assert refusal, no write."""
        # Arrange.
        recorded: dict[str, VerificationReport] = {}
        # Act + Assert.
        for flags in (
            {"residual_within_tolerance": False},
            {"digests_agree": False},
            {"counts_reconcile": False},
        ):
            with pytest.raises(ValueError):
                _mint_verified(recorded=recorded, **flags)
        assert recorded == {}

    def test_verified_with_code_refused(self) -> None:
        """Arrange VERIFIED plus a code; Act mint; Assert refusal."""
        # Arrange + Act + Assert.
        with pytest.raises(ValueError):
            _mint_verified(reason_code=VERIFY_TOLERANCE_EXCEEDED)

    def test_failed_with_all_true_flags_refused_as_contradictory(self) -> None:
        """Arrange FAILED with a clean conjunction; Act mint; Assert refusal."""
        # Arrange + Act + Assert.
        with pytest.raises(ValueError):
            mint_report(
                situation_id=SITUATION,
                execution_id=EXECUTION,
                legacy_total_after=LEGACY_AFTER,
                variance_after=RESIDUAL_ZERO,
                verdict=VerificationVerdict.FAILED,
                checked_at=T_CHECK,
                residual_within_tolerance=True,
                digests_agree=True,
                counts_reconcile=True,
                reason_code=VERIFY_DIGEST_MISMATCH,
                recorded={},
            )

    @pytest.mark.parametrize(
        "code",
        sorted(FAILED_CODES),
        ids=sorted(c.removeprefix("VERIFY_").lower() for c in FAILED_CODES),
    )
    def test_each_failed_code_reachable(self, code: str) -> None:
        """Arrange each F28 code; Act mint FAILED; Assert verdict never accepts."""
        # Arrange + Act.
        report = mint_report(
            situation_id=SITUATION,
            execution_id="exec-failed-matrix-001",
            legacy_total_after=LEGACY_AFTER,
            variance_after=Decimal("250.00"),
            verdict=VerificationVerdict.FAILED,
            checked_at=T_CHECK,
            residual_within_tolerance=False,
            digests_agree=False,
            counts_reconcile=False,
            reason_code=code,
            recorded={},
        )
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert report.is_accepted(TOLERANCE) is False

    def test_failed_without_code_refused(self) -> None:
        """Arrange FAILED with no code; Act mint; Assert refusal, silent never."""
        # Arrange + Act + Assert.
        with pytest.raises(ValueError):
            _mint_verified(
                verdict=VerificationVerdict.FAILED,
                residual_within_tolerance=False,
                digests_agree=False,
                counts_reconcile=False,
                reason_code=None,
            )

    def test_naive_checked_at_mints_nothing(self) -> None:
        """Arrange naive checked_at; Act mint; Assert model refuses, map empty."""
        # Arrange.
        recorded: dict[str, VerificationReport] = {}
        # Act + Assert.
        with pytest.raises(ValidationError):
            _mint_verified(
                checked_at=datetime(2026, 9, 16, 12, 0, 0),
                recorded=recorded,
            )
        assert recorded == {}

    @pytest.mark.parametrize("bad", [10000.0, 10000, "10000.00", True, None])
    def test_non_decimal_money_refused(self, bad: Any) -> None:
        """Arrange float/int/str/bool/None money; Act mint; Assert refusal."""
        # Arrange + Act + Assert.
        with pytest.raises((TypeError, ValueError, ValidationError)):
            _mint_verified(legacy_total_after=bad, recorded={})

    def test_non_two_dp_money_refused(self) -> None:
        """Arrange 1-dp money; Act mint; Assert refusal without rounding."""
        # Arrange + Act + Assert.
        with pytest.raises(ValueError):
            _mint_verified(legacy_total_after=Decimal("992500.0"), recorded={})


class TestDoubleMintMatrix:
    """One execution holds at most one terminal verification identity (F64)."""

    def test_identical_replay_returns_recorded_identical(self) -> None:
        """Arrange recorded report; Act same-content mint; Assert identity back."""
        # Arrange.
        first = _mint_verified()
        recorded = {EXECUTION: first}
        # Act.
        second = _mint_verified(
            checked_at=T_CHECK + timedelta(seconds=45),
            recorded=recorded,
        )
        # Assert.
        assert second is first
        assert second == first

    def test_differing_second_mint_refused_first_stands(self) -> None:
        """Arrange recorded VERIFIED; Act drifted mint; Assert refusal, first kept."""
        # Arrange.
        first = _mint_verified()
        recorded = {EXECUTION: first}
        # Act.
        with pytest.raises(MintRefused) as exc_info:
            _mint_verified(
                legacy_total_after=Decimal("992501.00"),
                recorded=recorded,
            )
        # Assert.
        assert exc_info.value.code == VERIFY_DOUBLE_MINT_REFUSED
        assert recorded[EXECUTION] is first

    def test_differing_verdict_second_mint_refused(self) -> None:
        """Arrange recorded VERIFIED; Act FAILED remint; Assert refusal stands."""
        # Arrange.
        first = _mint_verified()
        recorded = {EXECUTION: first}
        # Act.
        with pytest.raises(MintRefused) as exc_info:
            mint_report(
                situation_id=SITUATION,
                execution_id=EXECUTION,
                legacy_total_after=LEGACY_AFTER,
                variance_after=Decimal("500.00"),
                verdict=VerificationVerdict.FAILED,
                checked_at=T_CHECK,
                residual_within_tolerance=False,
                digests_agree=True,
                counts_reconcile=True,
                reason_code=VERIFY_TOLERANCE_EXCEEDED,
                recorded=recorded,
            )
        # Assert.
        assert exc_info.value.code == VERIFY_DOUBLE_MINT_REFUSED
        assert recorded[EXECUTION] is first

    def test_mint_refused_carries_registered_code_only(self) -> None:
        """Arrange MintRefused; Act construct; Assert unknown codes rejected."""
        # Arrange + Act + Assert.
        refused = MintRefused(VERIFY_DOUBLE_MINT_REFUSED, "drifted totals")
        assert refused.code == VERIFY_DOUBLE_MINT_REFUSED
        with pytest.raises(ValueError):
            MintRefused("VERIFY_NOPE")


# ---------------------------------------------------------------------------
# Clock discipline: naive refused, skew maps to VERIFY_CLOCK_SKEW
# ---------------------------------------------------------------------------


class TestClockMatrix:
    """checked_at discipline is pure: predicates return codes, never the time."""

    def test_naive_checked_at_raises(self) -> None:
        """Arrange naive stamp; Act assess; Assert ValueError (model refuses)."""
        # Arrange + Act + Assert.
        with pytest.raises(ValueError):
            assess_clock(
                checked_at=datetime(2026, 9, 16, 12, 0, 0),
                recorded_at=T_RECORDED,
                now=T_NOW,
            )

    def test_backdated_before_recorded_maps_clock_skew(self) -> None:
        """Arrange checked_at before recorded_at; Act assess; Assert skew code."""
        # Arrange + Act.
        code = assess_clock(
            checked_at=T_RECORDED - timedelta(seconds=1),
            recorded_at=T_RECORDED,
            now=T_NOW,
        )
        # Assert.
        assert code == VERIFY_CLOCK_SKEW

    def test_future_beyond_five_minute_budget_maps_clock_skew(self) -> None:
        """Arrange checked_at past budget; Act assess; Assert skew code."""
        # Arrange.
        now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        # Act.
        over = assess_clock(
            checked_at=now + FUTURE_SKEW_BUDGET + timedelta(seconds=1),
            recorded_at=T_RECORDED,
            now=now,
        )
        # Assert.
        assert timedelta(minutes=5) == FUTURE_SKEW_BUDGET
        assert over == VERIFY_CLOCK_SKEW

    def test_future_within_budget_accepted(self) -> None:
        """Arrange checked_at inside budget; Act assess; Assert no code."""
        # Arrange.
        now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        # Act.
        code = assess_clock(
            checked_at=now + timedelta(minutes=4),
            recorded_at=T_RECORDED,
            now=now,
        )
        # Assert.
        assert code is None

    def test_exact_recorded_at_accepted(self) -> None:
        """Arrange checked_at equal to recorded_at; Act assess; Assert no code."""
        # Arrange + Act.
        code = assess_clock(
            checked_at=T_RECORDED,
            recorded_at=T_RECORDED,
            now=T_NOW,
        )
        # Assert.
        assert code is None


# ---------------------------------------------------------------------------
# Orchestrator: FS-231 end to end, FAILED paths, incomplete paths, replay
# ---------------------------------------------------------------------------


class TestOrchestratorGolden:
    """The FS-231 walk verifies end to end with zero adaptation (F41–F44)."""

    def test_fs231_end_to_end_verified(self) -> None:
        """Arrange handoff plus stub readers; Act verify; Assert golden report."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        # Act.
        report = _run(_handoff(), store, log)
        # Assert.
        assert report.situation_id == SITUATION
        assert report.execution_id == EXECUTION
        assert report.legacy_total_after == Decimal("992500.00")
        assert report.variance_after == Decimal("0.00")
        assert report.verdict is VerificationVerdict.VERIFIED
        assert report.checked_at == T_CHECK
        assert report.is_accepted(CompanyConfiguration().tolerance_minor) is True
        assert store.lookup(EXECUTION) == report
        assert len(log) == 1
        entry = log.entries[0]
        assert entry.outcome == "VERIFIED"
        assert entry.reason_code is None
        assert entry.report_hash is not None
        assert entry.handoff_digest == digest_handoff(_handoff())

    def test_stale_replay_returns_recorded_byte_identically(self) -> None:
        """Arrange an already-verified pair; Act rerun; Assert recorded returns."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        first = _run(_handoff(), store, log)
        # Act.
        second = _run(_handoff(), store, log)
        # Assert.
        assert second == first
        assert second is first
        assert len(log) == 2
        assert log.entries[1].outcome == "VERIFIED"
        assert log.entries[1].reason_code == VERIFY_STALE_REPLAY


class TestOrchestratorFailed:
    """Completed checks with failed re-reads mint FAILED, never VERIFIED."""

    def test_digest_mismatch_failed(self) -> None:
        """Arrange flipped RESULT bytes; Act verify; Assert digest FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _tampered(handoff: ExecutionHandoff) -> R1Observation:
            return R1Observation(
                result_bytes=RESULT_BYTES + b"\x00",
                result_sha256=RESULT_SHA,
                observed_at=T_CHECK,
            )

        # Act.
        report = _run(_handoff(), store, log, read_result=_tampered)
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert report.is_accepted(TOLERANCE) is False
        assert log.entries[0].outcome == "FAILED"
        assert log.entries[0].reason_code == VERIFY_DIGEST_MISMATCH
        assert store.lookup(EXECUTION) == report

    def test_batch_skew_failed_via_reader_signal(self) -> None:
        """Arrange WrongBatch signal; Act verify; Assert batch FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _wrong_batch(handoff: ExecutionHandoff) -> R1Observation:
            raise ReaderFailed(VERIFY_BATCH_SKEW, "header batch drifted")

        # Act.
        report = _run(_handoff(), store, log, read_result=_wrong_batch)
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert log.entries[0].reason_code == VERIFY_BATCH_SKEW

    def test_count_skew_failed_on_accepted_mismatch(self) -> None:
        """Arrange derived sum skew; Act verify; Assert count FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _skewed(handoff: ExecutionHandoff) -> R2Observation:
            return R2Observation(
                accepted_total=Decimal("9999.99"),
                prior_total=PRIOR,
                legacy_after=Decimal("992499.99"),
                observed_at=T_CHECK,
            )

        # Act.
        report = _run(_handoff(), store, log, read_legacy=_skewed)
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert log.entries[0].reason_code == VERIFY_COUNT_SKEW

    def test_control_skew_failed_on_legacy_math(self) -> None:
        """Arrange legacy_after breaking prior+accepted; Act; Assert control FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _broken(handoff: ExecutionHandoff) -> R2Observation:
            return R2Observation(
                accepted_total=ACCEPTED,
                prior_total=PRIOR,
                legacy_after=Decimal("992500.01"),
                observed_at=T_CHECK,
            )

        # Act.
        report = _run(_handoff(), store, log, read_legacy=_broken)
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert log.entries[0].reason_code == VERIFY_CONTROL_SKEW

    def test_tolerance_exceeded_failed(self) -> None:
        """Arrange residual 200; Act verify; Assert tolerance FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _gapped(handoff: ExecutionHandoff) -> R3Observation:
            return R3Observation(
                expected=Decimal("1000200.00"),
                pending=PENDING,
                residual=Decimal("200.00"),
                observed_at=T_CHECK,
            )

        # Act.
        report = _run(_handoff(), store, log, read_expectation=_gapped)
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert report.variance_after == Decimal("200.00")
        assert log.entries[0].reason_code == VERIFY_TOLERANCE_EXCEEDED

    def test_tolerance_boundary_inclusive_end_to_end(self) -> None:
        """Arrange residual exactly 100; Act verify; Assert VERIFIED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _boundary(handoff: ExecutionHandoff) -> R3Observation:
            return R3Observation(
                expected=Decimal("1000100.00"),
                pending=PENDING,
                residual=Decimal("100.00"),
                observed_at=T_CHECK,
            )

        # Act.
        report = _run(_handoff(), store, log, read_expectation=_boundary)
        # Assert.
        assert report.verdict is VerificationVerdict.VERIFIED
        assert report.is_accepted(TOLERANCE) is True

    def test_backdated_checked_at_failed(self) -> None:
        """Arrange backdated checked_at; Act verify; Assert clock FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        # Act.
        report = _run(
            _handoff(),
            store,
            log,
            checked_at=T_RECORDED - timedelta(seconds=10),
        )
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert log.entries[0].reason_code == VERIFY_CLOCK_SKEW

    def test_future_checked_at_beyond_budget_failed(self) -> None:
        """Arrange far-future checked_at; Act verify; Assert clock FAILED."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        # Act.
        report = _run(
            _handoff(),
            store,
            log,
            checked_at=T_NOW + timedelta(minutes=10),
        )
        # Assert.
        assert report.verdict is VerificationVerdict.FAILED
        assert log.entries[0].reason_code == VERIFY_CLOCK_SKEW

    def test_count_skew_reader_signal_without_totals_is_incomplete(self) -> None:
        """Arrange R2 raising count skew; Act; Assert incomplete, code kept."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()

        def _no_totals(handoff: ExecutionHandoff) -> R2Observation:
            raise ReaderFailed(VERIFY_COUNT_SKEW, "lines do not reconcile")

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_legacy=_no_totals)
        # Assert.
        assert exc_info.value.code == VERIFY_COUNT_SKEW
        assert store.lookup(EXECUTION) is None
        assert log.entries[0].outcome == "INCOMPLETE"


class TestOrchestratorIncomplete:
    """Missing inputs refuse minting entirely — never FAILED-as-verdict."""

    def test_unknown_handoff_mints_nothing(self) -> None:
        """Arrange UNKNOWN handoff; Act verify; Assert missing-result refusal."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        unknown = ExecutionHandoff(
            execution_id=EXECUTION,
            authorization_id="g7-fs231-auth-001",
            proposal_hash="ph-fs231-001",
            proposal_version=3,
            company_id="meridian",
            situation_id=SITUATION,
            batch_id=BATCH,
            s3_outbound_key="meridian/LEGACY-20260916-0043/OUTBOUND_231.DAT",
            outbound_sha256="b" * 64,
            control_total=Decimal("10000.00"),
            record_count=1,
            accepted_count=0,
            rejected_count=0,
            outcome="UNKNOWN",
            unknown_flag=True,
            recorded_at=T_RECORDED,
        )
        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(unknown, store, log)
        # Assert.
        assert exc_info.value.code == VERIFY_RESULT_MISSING
        assert store.lookup(EXECUTION) is None
        assert len(log) == 1
        assert log.entries[0].outcome == "INCOMPLETE"
        assert log.entries[0].report_hash is None

    def test_wrong_company_refused(self) -> None:
        """Arrange cross-company handoff; Act verify; Assert escape refusal."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(company_id="acme"), store, log)
        # Assert.
        assert exc_info.value.code == VERIFY_PREFIX_ESCAPE
        assert store.lookup(EXECUTION) is None

    def test_wrong_situation_refused(self) -> None:
        """Arrange case skew; Act verify; Assert refusal, no report."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, for_situation_id="FS-2026-0916-00999")
        # Assert.
        assert exc_info.value.code == VERIFY_CASE_SKEW
        assert store.lookup(EXECUTION) is None

    def test_blank_authorization_refused(self) -> None:
        """Arrange unapproved execution; Act verify; Assert unauthorized refusal."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        hollow = ExecutionHandoff.model_construct(
            execution_id=EXECUTION,
            authorization_id="  ",
            proposal_hash="ph-fs231-001",
            proposal_version=3,
            company_id="meridian",
            situation_id=SITUATION,
            batch_id=BATCH,
            s3_outbound_key="k",
            outbound_sha256="b" * 64,
            control_total=Decimal("10000.00"),
            record_count=1,
            accepted_count=1,
            rejected_count=0,
            accepted_total=ACCEPTED,
            rejected_total=Decimal("0.00"),
            per_record=(),
            result_key=RESULT_KEY,
            result_sha256=RESULT_SHA,
            outcome="ACCEPTED",
            unknown_flag=False,
            recorded_at=T_RECORDED,
        )
        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(hollow, store, log)
        # Assert.
        assert exc_info.value.code == VERIFY_UNAUTHORIZED_EXECUTION
        assert store.lookup(EXECUTION) is None

    def test_corrupt_handoff_totals_refused(self) -> None:
        """Arrange float totals smuggled past the model; Act; Assert corrupt refusal."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        corrupt = ExecutionHandoff.model_construct(
            execution_id=EXECUTION,
            authorization_id="g7-fs231-auth-001",
            proposal_hash="ph-fs231-001",
            proposal_version=3,
            company_id="meridian",
            situation_id=SITUATION,
            batch_id=BATCH,
            s3_outbound_key="k",
            outbound_sha256="b" * 64,
            control_total=10000.0,
            record_count=1,
            accepted_count=1,
            rejected_count=0,
            accepted_total=ACCEPTED,
            rejected_total=Decimal("0.00"),
            per_record=(),
            result_key=RESULT_KEY,
            result_sha256=RESULT_SHA,
            outcome="ACCEPTED",
            unknown_flag=False,
            recorded_at=T_RECORDED,
        )
        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(corrupt, store, log)
        # Assert.
        assert exc_info.value.code == VERIFY_HANDOFF_CORRUPT
        assert store.lookup(EXECUTION) is None

    def test_absent_result_key_refused_before_rereads(self) -> None:
        """Arrange S3 miss signalled by the reader; Act; Assert missing refusal."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        calls: list[str] = []

        def _missing(handoff: ExecutionHandoff) -> R1Observation:
            calls.append("r1")
            raise ReaderFailed(VERIFY_RESULT_MISSING, "key absent at verify time")

        def _r2_spy(handoff: ExecutionHandoff) -> R2Observation:
            calls.append("r2")
            return _r2_ok(handoff)

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_result=_missing, read_legacy=_r2_spy)
        # Assert.
        assert exc_info.value.code == VERIFY_RESULT_MISSING
        assert store.lookup(EXECUTION) is None
        assert calls == ["r1", "r2"]

    def test_naive_checked_at_refused_without_code(self) -> None:
        """Arrange naive checked_at; Act verify; Assert refusal, model owns it."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(
                _handoff(),
                store,
                log,
                checked_at=datetime(2026, 9, 16, 12, 0, 0),
            )
        # Assert.
        assert exc_info.value.code is None
        assert store.lookup(EXECUTION) is None

    def test_double_mint_drift_refused_first_stands(self) -> None:
        """Arrange recorded VERIFIED plus ledger drift; Act rerun; Assert refusal."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        first = _run(_handoff(), store, log)

        def _drifted(handoff: ExecutionHandoff) -> R2Observation:
            return R2Observation(
                accepted_total=ACCEPTED,
                prior_total=PRIOR,
                legacy_after=Decimal("992501.00"),
                observed_at=T_CHECK,
            )

        # Act.
        with pytest.raises(VerificationRefused) as exc_info:
            _run(_handoff(), store, log, read_legacy=_drifted)
        # Assert.
        assert exc_info.value.code == VERIFY_DOUBLE_MINT_REFUSED
        assert store.lookup(EXECUTION) is first
        assert log.entries[-1].reason_code == VERIFY_DOUBLE_MINT_REFUSED


# ---------------------------------------------------------------------------
# Audit spine: one append-only entry per run
# ---------------------------------------------------------------------------


class TestAuditSpine:
    """Every verification run records exactly one audit entry (F6)."""

    def test_one_entry_per_run_across_all_paths(self) -> None:
        """Arrange golden, failed, incomplete runs; Act; Assert three entries."""
        # Arrange.
        store, log = ReplayStore(), AuditLog()
        _run(_handoff(), store, log)

        def _gapped(handoff: ExecutionHandoff) -> R3Observation:
            return R3Observation(
                expected=Decimal("1000200.00"),
                pending=PENDING,
                residual=Decimal("200.00"),
                observed_at=T_CHECK,
            )

        _run(
            _handoff(execution_id="exec-gap-002"),
            store,
            log,
            read_expectation=_gapped,
        )
        with pytest.raises(VerificationRefused):
            _run(_handoff(execution_id="exec-unknown-003", outcome="UNKNOWN",
                          unknown_flag=True, result_key=None, result_sha256=None,
                          accepted_total=None, rejected_total=None,
                          accepted_count=0, rejected_count=0),
                 store, log)
        # Act.
        entries = log.entries
        # Assert.
        assert len(entries) == 3
        assert [(e.outcome, e.reason_code) for e in entries] == [
            ("VERIFIED", None),
            ("FAILED", VERIFY_TOLERANCE_EXCEEDED),
            ("INCOMPLETE", VERIFY_RESULT_MISSING),
        ]
        for entry in entries:
            assert entry.handoff_digest == digest_handoff(_handoff())
            assert isinstance(entry, AuditEntry)

    def test_audit_log_is_append_only(self) -> None:
        """Arrange a log; Act inspect surface; Assert no removal or rewrite API."""
        # Arrange + Act + Assert.
        for forbidden in ("remove", "clear", "pop", "delete", "__delitem__", "update"):
            assert not hasattr(AuditLog, forbidden)
        assert isinstance(AuditLog().entries, tuple)

    def test_replay_store_first_record_stands(self) -> None:
        """Arrange recorded report; Act blind record; Assert first wins."""
        # Arrange.
        store = ReplayStore()
        first = _mint_verified()
        # Act.
        assert store.record(first) is first
        assert store.lookup(EXECUTION) is first
        assert store.lookup("exec-absent-999") is None
        # Assert identical re-record returns the original.
        assert store.record(_mint_verified()) is first


# ---------------------------------------------------------------------------
# Hygiene: no LLM, no network, no wall-clock, no new dependencies
# ---------------------------------------------------------------------------


class TestSourceHygiene:
    """Track B sources stay deterministic: stdlib plus finance/domain only."""

    TRACK_B_FILES = (
        "__init__.py",
        "reason_codes.py",
        "clock.py",
        "minter.py",
        "replay.py",
        "audit.py",
        "orchestrator.py",
    )

    BANNED_ROOTS = frozenset(
        {
            "openai",
            "langchain",
            "langgraph",
            "litellm",
            "groq",
            "httpx",
            "requests",
            "socket",
            "urllib",
            "boto3",
            "botocore",
            "redis",
            "temporalio",
        }
    )

    BANNED_CALLS = frozenset(
        {
            ("datetime", "now"),
            ("datetime", "utcnow"),
            ("datetime", "today"),
            ("time", "time"),
            ("time", "monotonic"),
            ("time", "perf_counter"),
            ("time", "sleep"),
            ("os", "environ"),
            ("os", "getenv"),
            ("random", "random"),
        }
    )

    def test_no_banned_imports_or_wall_clock_calls(self) -> None:
        """Arrange track B sources; Act AST scan; Assert deterministic only."""
        # Arrange.
        package = Path(__file__).resolve().parents[3] / "finance" / "verification"
        # Act + Assert.
        assert len(self.TRACK_B_FILES) == 7
        for name in self.TRACK_B_FILES:
            source = (package / name).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=name)
            roots: set[str] = set()
            calls: set[tuple[str, str]] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    receiver = node.func.value
                    if isinstance(receiver, ast.Name):
                        calls.add((receiver.id, node.func.attr))
            assert not (roots & self.BANNED_ROOTS), f"{name} imports {roots}"
            assert not (calls & self.BANNED_CALLS), f"{name} calls {calls}"
