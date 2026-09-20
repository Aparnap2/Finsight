"""P6-08 track B deterministic report minter (F26-F31, F64).

Mints exactly the frozen six-field ``VerificationReport``: VERIFIED only on
the explicit three-flag conjunction with no code, FAILED only with exactly
one registered F28 code and a broken conjunction. Minting is keyed by
``execution_id`` over an injected read-only map: identical replays return
the recorded report, differing second mints refuse with F64 and the first
record stands. Missing inputs refuse minting entirely (incomplete, never
FAILED-as-verdict); that judgment lives in the orchestrator, which simply
never calls the minter on the incomplete path.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from finance.domain.verification import VerificationReport, VerificationVerdict
from finance.verification.reason_codes import (
    VERIFY_DOUBLE_MINT_REFUSED,
    require_failed_code,
    require_registered,
)

__all__ = ["MintRefused", "mint_report"]


class MintRefused(Exception):  # noqa: N818 -- contract signal, name frozen by tests
    """A second mint was refused: carries the registered reason code only."""

    def __init__(self, code: str, message: str = "") -> None:
        """Bind a registered refusal code to the refusal.

        Args:
            code: Registered reason code (unknown codes refused).
            message: Human triage detail; never a second code.

        Raises:
            ValueError: When the code is outside the closed registry.
        """
        require_registered(code)
        super().__init__(message or code)
        self.code: str = code
        """The registered reason the mint was refused."""


def _require_money(name: str, value: Decimal) -> Decimal:
    """Return the value when it is an exact 2-dp Decimal, else refuse.

    Exactness is judged by representation (exponent -2), never by numeric
    comparison: ``Decimal("992500.0")`` is numerically equal to
    ``Decimal("992500.00")`` yet is not 2-dp money and is refused here.

    Args:
        name: Argument label for the refusal message.
        value: Candidate monetary total (Decimal-only; floats never mint).

    Raises:
        TypeError: When the value is not a Decimal (float/int/str/bool/None).
        ValueError: When the value is not exactly 2-dp (never rounded).
    """
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}.")
    if value.as_tuple().exponent != -2:
        raise ValueError(f"{name} must carry exactly 2 dp, got {value!r}.")
    return value


def _same_identity(first: VerificationReport, second: VerificationReport) -> bool:
    """Return True when both reports share one verification identity (F64).

    Identity covers situation, execution, totals, and verdict; checked_at is
    excluded so a replay with a fresh stamp still resolves idempotently.
    """
    return (
        first.situation_id == second.situation_id
        and first.execution_id == second.execution_id
        and first.legacy_total_after == second.legacy_total_after
        and first.variance_after == second.variance_after
        and first.verdict is second.verdict
    )


def mint_report(
    *,
    situation_id: str,
    execution_id: str,
    legacy_total_after: Decimal,
    variance_after: Decimal,
    verdict: VerificationVerdict,
    checked_at: datetime,
    residual_within_tolerance: bool,
    digests_agree: bool,
    counts_reconcile: bool,
    reason_code: str | None,
    recorded: dict[str, VerificationReport] | None = None,
) -> VerificationReport:
    """Mint the frozen six-field report or return/refuse on the F64 registry.

    Args:
        situation_id: Case binding carried from the handoff (post-gate).
        execution_id: Non-blank idempotency binding for the report.
        legacy_total_after: R2 books-side total only (Decimal 2-dp).
        variance_after: R3 residual math only (Decimal 2-dp).
        verdict: VERIFIED needs the full conjunction and no code; FAILED
            needs a broken conjunction and exactly one F28 code.
        checked_at: Caller-supplied tz-aware run time (naive refused by
            the frozen model with ValidationError).
        residual_within_tolerance: Conjunction flag (a).
        digests_agree: Conjunction flag (b).
        counts_reconcile: Conjunction flag (c).
        reason_code: None for VERIFIED; one FAILED code for FAILED.
        recorded: Execution-keyed idempotency map; the new report is stored
            on success and never touched on refusal.

    Returns:
        The minted report, or the recorded identical report on replay.

    Raises:
        TypeError: On non-Decimal money.
        ValueError: On non-2-dp money, contradictory flag/code shapes, or
            unknown/non-FAILED codes.
        MintRefused: On a differing second mint (F64); first record stands.
    """
    _require_money("legacy_total_after", legacy_total_after)
    _require_money("variance_after", variance_after)
    conjunction = residual_within_tolerance and digests_agree and counts_reconcile
    if verdict is VerificationVerdict.VERIFIED:
        if not conjunction:
            raise ValueError("VERIFIED needs all three flags true; refuse, mint nothing.")
        if reason_code is not None:
            raise ValueError("VERIFIED carries no reason code; refuse, mint nothing.")
    elif verdict is VerificationVerdict.FAILED:
        if conjunction:
            raise ValueError("FAILED with a clean conjunction is contradictory; refuse.")
        if reason_code is None:
            raise ValueError("FAILED with no reason code is silent; refuse, mint nothing.")
        require_failed_code(reason_code)
    else:
        raise ValueError(f"Unknown verdict refused: {verdict!r}.")
    candidate = VerificationReport(
        situation_id=situation_id,
        execution_id=execution_id,
        legacy_total_after=legacy_total_after,
        variance_after=variance_after,
        verdict=verdict,
        checked_at=checked_at,
    )
    ledger: dict[str, VerificationReport] = {} if recorded is None else recorded
    existing = ledger.get(candidate.execution_id)
    if existing is None:
        ledger[candidate.execution_id] = candidate
        return candidate
    if _same_identity(existing, candidate):
        return existing
    raise MintRefused(
        VERIFY_DOUBLE_MINT_REFUSED,
        f"execution {candidate.execution_id!r} already holds a verification identity.",
    )
