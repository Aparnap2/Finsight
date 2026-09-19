"""P6-08 track B single-pass verification orchestrator (F11-F17, F22-F29, F40).

Runs one handoff end to end with no retry loops: entry gates (F11-F17),
then the injected R1/R2/R3 readers over track B observation shapes, then
computed cross-checks, then the minter, then exactly one audit entry. R1
reader signals carrying a FAILED code mint FAILED (the signal is the
check); R2/R3 signals and non-FAILED R1 signals are missing inputs and
refuse minting as INCOMPLETE (never FAILED-as-verdict). Replays compare
the recomputed identity against the store: identical returns the recorded
report with VERIFY_STALE_REPLAY, differing refuses with F64.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import NoReturn

from pydantic import BaseModel, ConfigDict, field_validator

from finance.business_rules.meridian import CompanyConfiguration
from finance.domain.verification import VerificationReport, VerificationVerdict
from finance.legacy_execution.handoff import ExecutionHandoff
from finance.legacy_execution.ingestion import OutcomeLabel
from finance.verification.audit import AuditEntry, AuditLog, digest_handoff, hash_report
from finance.verification.clock import assess_clock
from finance.verification.minter import MintRefused, mint_report
from finance.verification.reason_codes import (
    FAILED_CODES,
    VERIFY_CASE_SKEW,
    VERIFY_CONTROL_SKEW,
    VERIFY_COUNT_SKEW,
    VERIFY_DIGEST_MISMATCH,
    VERIFY_DOUBLE_MINT_REFUSED,
    VERIFY_HANDOFF_CORRUPT,
    VERIFY_PREFIX_ESCAPE,
    VERIFY_RESULT_MISSING,
    VERIFY_STALE_REPLAY,
    VERIFY_TOLERANCE_EXCEEDED,
    VERIFY_UNAUTHORIZED_EXECUTION,
    require_registered,
)
from finance.verification.replay import ReplayStore

_COMPANY = "meridian"
_ZERO = Decimal("0.00")

__all__ = [
    "R1Observation",
    "R2Observation",
    "R3Observation",
    "ReaderFailed",
    "VerificationRefused",
    "verify_execution",
]


def _is_naive(value: datetime) -> bool:
    """Return True when the timestamp carries no timezone (caller-owned clock)."""
    return value.tzinfo is None or value.utcoffset() is None


def _require_tz_aware(name: str, value: datetime) -> datetime:
    """Return the value when tz-aware, else raise ValueError."""
    if _is_naive(value):
        raise ValueError(f"{name} must be tz-aware (caller-supplied run time).")
    return value


def _require_two_dp(name: str, value: Decimal) -> Decimal:
    """Return the value when it is an exact 2-dp Decimal, else refuse.

    Exactness is representational (exponent -2): numeric comparison cannot
    tell ``Decimal("992500.0")`` from ``Decimal("992500.00")``.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}.")
    if value.as_tuple().exponent != -2:
        raise ValueError(f"{name} must carry exactly 2 dp, got {value!r}.")
    return value


class R1Observation(BaseModel):
    """Track B R1 shape: fresh RESULT bytes plus the claimed digest (F18)."""

    model_config = ConfigDict(frozen=True, strict=True)

    result_bytes: bytes
    """Exact bytes returned by the fresh RESULT GET at verify time."""

    result_sha256: str
    """Digest claimed alongside the bytes; recomputed digest must match."""

    observed_at: datetime
    """Caller-supplied tz-aware verification run time."""

    @field_validator("result_sha256")
    @classmethod
    def _check_sha_hex(cls, value: str) -> str:
        """Require a 64-char lowercase hex digest."""
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("result_sha256 must be 64 lowercase hex chars.")
        return value

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


class R2Observation(BaseModel):
    """Track B R2 shape: books-side totals with the prior detection fact (F19)."""

    model_config = ConfigDict(frozen=True, strict=True)

    accepted_total: Decimal
    """Fresh accepted sum for the correction (Decimal 2-dp)."""

    prior_total: Decimal
    """Caller-supplied pre-correction legacy total with provenance (2-dp)."""

    legacy_after: Decimal
    """Re-read books-side legacy total after posting (sole D1 provenance)."""

    observed_at: datetime
    """Caller-supplied tz-aware verification run time."""

    @field_validator("accepted_total", "prior_total", "legacy_after")
    @classmethod
    def _check_totals_two_dp(cls, value: Decimal) -> Decimal:
        """Require exact 2-dp Decimal totals."""
        return _require_two_dp("r2 total", value)

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


class R3Observation(BaseModel):
    """Track B R3 shape: expectation, pending, and the Decimal residual (F20)."""

    model_config = ConfigDict(frozen=True, strict=True)

    expected: Decimal
    """Re-read expected settlement total (Decimal 2-dp)."""

    pending: Decimal
    """Re-read recognised pending timing total (Decimal 2-dp)."""

    residual: Decimal
    """Claimed expected-minus-legacy-minus-pending gap; recomputed by us."""

    observed_at: datetime
    """Caller-supplied tz-aware verification run time."""

    @field_validator("expected", "pending", "residual")
    @classmethod
    def _check_totals_two_dp(cls, value: Decimal) -> Decimal:
        """Require exact 2-dp Decimal totals."""
        return _require_two_dp("r3 total", value)

    @field_validator("observed_at")
    @classmethod
    def _check_observed_tz(cls, value: datetime) -> datetime:
        """Require the caller-supplied tz-aware run time."""
        return _require_tz_aware("observed_at", value)


class ReaderFailed(Exception):  # noqa: N818 -- contract signal, name frozen by tests
    """A re-reader signalled instead of observing; carries its reason code."""

    def __init__(self, code: str, message: str = "") -> None:
        """Bind a registered signal code to the failure.

        Args:
            code: Registered reason code (unknown codes refused).
            message: Human triage detail; never a second code.

        Raises:
            ValueError: When the code is outside the closed registry.
        """
        require_registered(code)
        super().__init__(message or code)
        self.code: str = code
        """The registered reason the re-read signalled."""


class VerificationRefused(Exception):  # noqa: N818 -- contract signal, frozen name
    """The run minted nothing; carries the code, or None when model-owned."""

    def __init__(self, code: str | None, message: str = "") -> None:
        """Bind the refusal code (None only for naive-stamp model refusals).

        Args:
            code: Registered reason code, or None when Pydantic owns the
                refusal (naive checked_at mints nothing, no code invented).
            message: Human triage detail; never a second code.

        Raises:
            ValueError: When a non-None code is outside the closed registry.
        """
        if code is not None:
            require_registered(code)
        super().__init__(message or code or "verification refused")
        self.code: str | None = code
        """The registered refusal code, or None for model-owned refusals."""


def _handoff_money_corrupt(handoff: ExecutionHandoff) -> bool:
    """Return True when any handoff total breaks Decimal 2-dp hygiene (F16)."""
    for value in (handoff.control_total, handoff.accepted_total, handoff.rejected_total):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, Decimal):
            return True
        if value.as_tuple().exponent != -2:
            return True
    return handoff.outcome != OutcomeLabel.UNKNOWN.value and (
        handoff.accepted_total is None or handoff.rejected_total is None
    )


def _reread_digests(
    r1: R1Observation | None,
    r2: R2Observation | None,
    r3: R3Observation | None,
) -> tuple[str, ...]:
    """Return the hex digests of whichever observations are available (F6)."""
    digests: list[str] = []
    if r1 is not None:
        digests.append(sha256(r1.result_bytes).hexdigest())
    if r2 is not None:
        payload = f"{r2.accepted_total}|{r2.prior_total}|{r2.legacy_after}"
        digests.append(sha256(payload.encode("utf-8")).hexdigest())
    if r3 is not None:
        payload = f"{r3.expected}|{r3.pending}|{r3.residual}"
        digests.append(sha256(payload.encode("utf-8")).hexdigest())
    return tuple(digests)


def verify_execution(
    *,
    handoff: ExecutionHandoff,
    read_result: Callable[[ExecutionHandoff], R1Observation],
    read_legacy: Callable[[ExecutionHandoff], R2Observation],
    read_expectation: Callable[[ExecutionHandoff], R3Observation],
    checked_at: datetime,
    now: datetime,
    store: ReplayStore,
    audit_log: AuditLog,
    for_situation_id: str | None = None,
    tolerance: Decimal | None = None,
) -> VerificationReport:
    """Verify one handoff in a single pass and mint at most one report.

    Entry gates (F11-F17) refuse before any re-read; clock skew short-circuits
    to FAILED with VERIFY_CLOCK_SKEW; R1/R2/R3 readers run once each with no
    retries; computed cross-checks select the first failing code; the
    recomputed identity replays against the store (F40/F64); exactly one
    audit entry is appended on every path.

    Args:
        handoff: The recorded §8 handoff; claims only, trusted in no part.
        read_result: Injected R1 reader returning fresh RESULT bytes.
        read_legacy: Injected R2 reader returning books-side totals.
        read_expectation: Injected R3 reader returning expectation math.
        checked_at: Caller-supplied tz-aware verification run time.
        now: Caller-supplied tz-aware run window anchor for future skew.
        store: Execution-keyed replay store (first record stands).
        audit_log: Append-only spine receiving exactly one entry.
        for_situation_id: Case under verification; mismatch is CASE_SKEW.
        tolerance: Inclusive residual bound; defaults to the frozen minor
            tolerance (Decimal 100), consumed as given, never redefined.

    Returns:
        The minted VERIFIED/FAILED report, or the recorded report on replay.

    Raises:
        TypeError: When tolerance is not a Decimal.
        VerificationRefused: When the run is incomplete (no report minted,
            audit carries the code) or a differing second mint is refused.
    """
    bound = CompanyConfiguration().tolerance_minor if tolerance is None else tolerance
    if isinstance(bound, bool) or not isinstance(bound, Decimal):
        raise TypeError(f"tolerance must be Decimal, got {type(bound).__name__}.")

    def _audit(
        outcome: str,
        code: str | None,
        report: VerificationReport | None,
        digests: tuple[str, ...],
    ) -> None:
        entry = AuditEntry(
            execution_id=handoff.execution_id,
            situation_id=handoff.situation_id,
            handoff_digest=digest_handoff(handoff),
            reread_digests=digests,
            outcome=outcome,
            reason_code=code,
            report_hash=hash_report(report) if report is not None else None,
        )
        audit_log.append(entry)

    def _refuse(
        code: str | None, message: str, digests: tuple[str, ...] = ()
    ) -> NoReturn:
        _audit("INCOMPLETE", code, None, digests)
        raise VerificationRefused(code, message)

    def _settle(
        *,
        legacy_after: Decimal,
        variance_after: Decimal,
        verdict: VerificationVerdict,
        residual_ok: bool,
        digests_ok: bool,
        counts_ok: bool,
        code: str | None,
        digests: tuple[str, ...],
    ) -> VerificationReport:
        existing = store.lookup(handoff.execution_id)
        if existing is not None:
            identical = (
                existing.situation_id == handoff.situation_id
                and existing.legacy_total_after == legacy_after
                and existing.variance_after == variance_after
                and existing.verdict is verdict
            )
            if identical:
                _audit(existing.verdict.value, VERIFY_STALE_REPLAY, existing, digests)
                return existing
            _audit("INCOMPLETE", VERIFY_DOUBLE_MINT_REFUSED, None, digests)
            raise VerificationRefused(
                VERIFY_DOUBLE_MINT_REFUSED,
                f"execution {handoff.execution_id!r} already verified differently.",
            )
        report = mint_report(
            situation_id=handoff.situation_id,
            execution_id=handoff.execution_id,
            legacy_total_after=legacy_after,
            variance_after=variance_after,
            verdict=verdict,
            checked_at=checked_at,
            residual_within_tolerance=residual_ok,
            digests_agree=digests_ok,
            counts_reconcile=counts_ok,
            reason_code=code,
            recorded=None,
        )
        try:
            store.record(report)
        except MintRefused as exc:
            _audit("INCOMPLETE", exc.code, None, digests)
            raise VerificationRefused(exc.code, str(exc)) from exc
        _audit(verdict.value, code, report, digests)
        return report

    if _is_naive(checked_at) or _is_naive(now):
        _refuse(None, "checked_at and now must be tz-aware; naive mints nothing.")
    if handoff.company_id != _COMPANY:
        _refuse(VERIFY_PREFIX_ESCAPE, f"company {handoff.company_id!r} is not meridian.")
    if not handoff.situation_id.strip() or (
        for_situation_id is not None and handoff.situation_id != for_situation_id
    ):
        _refuse(VERIFY_CASE_SKEW, "handoff not bound to the case under verification.")
    if not handoff.authorization_id.strip():
        _refuse(VERIFY_UNAUTHORIZED_EXECUTION, "no G7 authorization binding present.")
    if _handoff_money_corrupt(handoff):
        _refuse(VERIFY_HANDOFF_CORRUPT, "handoff totals are not Decimal 2-dp.")
    if (
        handoff.unknown_flag
        or handoff.outcome == OutcomeLabel.UNKNOWN.value
        or handoff.result_key is None
        or handoff.result_sha256 is None
    ):
        _refuse(VERIFY_RESULT_MISSING, "UNKNOWN handoff or absent RESULT; incomplete.")

    try:
        clock_code = assess_clock(
            checked_at=checked_at, recorded_at=handoff.recorded_at, now=now
        )
    except ValueError as exc:
        _refuse(VERIFY_HANDOFF_CORRUPT, f"handoff recorded_at not tz-aware: {exc}.")
    if clock_code is not None:
        # Clock skew voids every cross-check identity: zero totals carry no
        # observation claim, all flags false, and the code tells the truth.
        return _settle(
            legacy_after=_ZERO,
            variance_after=_ZERO,
            verdict=VerificationVerdict.FAILED,
            residual_ok=False,
            digests_ok=False,
            counts_ok=False,
            code=clock_code,
            digests=(),
        )

    r1: R1Observation | None = None
    r1_signal: str | None = None
    try:
        r1 = read_result(handoff)
    except ReaderFailed as exc:
        r1_signal = exc.code
    r2: R2Observation | None = None
    r2_signal: str | None = None
    try:
        r2 = read_legacy(handoff)
    except ReaderFailed as exc:
        r2_signal = exc.code
    r3: R3Observation | None = None
    r3_signal: str | None = None
    try:
        r3 = read_expectation(handoff)
    except ReaderFailed as exc:
        r3_signal = exc.code
    digests = _reread_digests(r1, r2, r3)

    if r2 is None or r3 is None:
        # Totals unavailable: FAILED needs complete totals, so any R2/R3
        # signal is incomplete with its code kept, never FAILED-as-verdict.
        signal = r2_signal if r2_signal is not None else r3_signal
        _refuse(signal, f"legacy/expectation re-read signalled {signal}; incomplete.", digests)
    if r1 is None:
        if r1_signal is not None and r1_signal in FAILED_CODES:
            # R1 signals carrying a FAILED code are the check itself: R2/R3
            # are complete, so mint FAILED with binding checks voided.
            return _settle(
                legacy_after=r2.legacy_after,
                variance_after=r3.residual,
                verdict=VerificationVerdict.FAILED,
                residual_ok=abs(r3.residual) <= bound,
                digests_ok=False,
                counts_ok=(
                    r2.accepted_total == handoff.accepted_total
                    and r2.prior_total + r2.accepted_total == r2.legacy_after
                ),
                code=r1_signal,
                digests=digests,
            )
        _refuse(r1_signal, f"RESULT re-read signalled {r1_signal}; incomplete.", digests)

    recomputed = sha256(r1.result_bytes).hexdigest()
    digests_ok = recomputed == r1.result_sha256 == handoff.result_sha256
    counts_ok = r2.accepted_total == handoff.accepted_total
    control_ok = (
        r2.prior_total + r2.accepted_total == r2.legacy_after
        and r2.accepted_total == handoff.control_total
    )
    residual = r3.expected - r2.legacy_after - r3.pending
    math_ok = residual == r3.residual
    residual_ok = abs(r3.residual) <= bound
    code: str | None = None
    if not digests_ok:
        code = VERIFY_DIGEST_MISMATCH
    elif not counts_ok:
        code = VERIFY_COUNT_SKEW
    elif not control_ok or not math_ok:
        code = VERIFY_CONTROL_SKEW
    elif not residual_ok:
        code = VERIFY_TOLERANCE_EXCEEDED
    verdict = VerificationVerdict.FAILED if code is not None else VerificationVerdict.VERIFIED
    return _settle(
        legacy_after=r2.legacy_after,
        variance_after=r3.residual,
        verdict=verdict,
        residual_ok=residual_ok,
        digests_ok=digests_ok,
        counts_ok=counts_ok and control_ok and math_ok,
        code=code,
        digests=digests,
    )
