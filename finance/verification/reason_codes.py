"""P6-08 track B closed reason-code registry (F28 + F64 + incomplete + replay).

The minter emits no code outside this registry: nine ``FAILED`` codes from
F28, two incomplete codes for runs that mint nothing (F36/F16 family), the
F64 double-mint refusal code, the F40 stale-replay marker, and the F15
prefix-escape code. Unknown codes are refused at construction so silent or
invented verdicts can never enter an audit entry or a report.
"""

from __future__ import annotations

VERIFY_DIGEST_MISMATCH = "VERIFY_DIGEST_MISMATCH"
"""R1 recomputed digest differs from the handoff result_sha256 (F34)."""

VERIFY_RESULT_MUTATED = "VERIFY_RESULT_MUTATED"
"""RESULT bytes changed after handoff: tamper-evident late mutation (F34)."""

VERIFY_BATCH_SKEW = "VERIFY_BATCH_SKEW"
"""RESULT header batch_id differs from the handoff batch_id (F35)."""

VERIFY_COUNT_SKEW = "VERIFY_COUNT_SKEW"
"""Accepted/rejected counts disagree with the R1 re-read (F35)."""

VERIFY_CONTROL_SKEW = "VERIFY_CONTROL_SKEW"
"""Control totals disagree across OUTBOUND, RESULT, and books (F35)."""

VERIFY_TOLERANCE_EXCEEDED = "VERIFY_TOLERANCE_EXCEEDED"
"""Completed re-reads with residual beyond tolerance (F37)."""

VERIFY_CASE_SKEW = "VERIFY_CASE_SKEW"
"""Handoff situation_id is blank or bound to another case (F38)."""

VERIFY_UNAUTHORIZED_EXECUTION = "VERIFY_UNAUTHORIZED_EXECUTION"
"""Handoff carries no G7 authorization binding (F39)."""

VERIFY_CLOCK_SKEW = "VERIFY_CLOCK_SKEW"
"""checked_at backdated before recorded_at or beyond the future budget (F29)."""

VERIFY_DOUBLE_MINT_REFUSED = "VERIFY_DOUBLE_MINT_REFUSED"
"""Second mint for one execution_id with differing content refused (F64)."""

VERIFY_RESULT_MISSING = "VERIFY_RESULT_MISSING"
"""RESULT absent at verify time or handoff UNKNOWN: incomplete, no mint (F36)."""

VERIFY_HANDOFF_CORRUPT = "VERIFY_HANDOFF_CORRUPT"
"""Handoff totals are not Decimal 2-dp: no re-read runs on it (F16)."""

VERIFY_STALE_REPLAY = "VERIFY_STALE_REPLAY"
"""Repeat run returned the recorded report byte-identically (F40)."""

VERIFY_PREFIX_ESCAPE = "VERIFY_PREFIX_ESCAPE"
"""Handoff company_id is not meridian: cross-company run refused (F15)."""

REASON_REGISTRY: dict[str, str] = {
    VERIFY_DIGEST_MISMATCH: "R1 digest differs from the handoff result digest.",
    VERIFY_RESULT_MUTATED: "RESULT bytes mutated after handoff; nothing repaired.",
    VERIFY_BATCH_SKEW: "RESULT header batch differs from the handoff batch.",
    VERIFY_COUNT_SKEW: "Counts disagree with the RESULT re-read population.",
    VERIFY_CONTROL_SKEW: "Control totals disagree across seams.",
    VERIFY_TOLERANCE_EXCEEDED: "Residual beyond tolerance with agreeing digests.",
    VERIFY_CASE_SKEW: "Handoff bound to another case or to no case.",
    VERIFY_UNAUTHORIZED_EXECUTION: "No G7 authorization binding present.",
    VERIFY_CLOCK_SKEW: "checked_at outside the recorded-to-budget window.",
    VERIFY_DOUBLE_MINT_REFUSED: "One execution holds one identity; drift refused.",
    VERIFY_RESULT_MISSING: "Cannot complete: RESULT missing or handoff UNKNOWN.",
    VERIFY_HANDOFF_CORRUPT: "Handoff money is not Decimal 2-dp.",
    VERIFY_STALE_REPLAY: "Replay returned the recorded report; no new mint.",
    VERIFY_PREFIX_ESCAPE: "Cross-company verification never runs.",
}
"""Closed world: every code the minter or orchestrator may emit, with meaning."""

FAILED_CODES: frozenset[str] = frozenset(
    {
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
)
"""Exactly the nine F28 codes a FAILED report may carry; refusals excluded."""

INCOMPLETE_CODES: frozenset[str] = frozenset(
    {VERIFY_RESULT_MISSING, VERIFY_HANDOFF_CORRUPT}
)
"""Runs that mint nothing: missing inputs or a corrupt handoff."""

__all__ = [
    "FAILED_CODES",
    "INCOMPLETE_CODES",
    "REASON_REGISTRY",
    "VERIFY_BATCH_SKEW",
    "VERIFY_CASE_SKEW",
    "VERIFY_CLOCK_SKEW",
    "VERIFY_CONTROL_SKEW",
    "VERIFY_COUNT_SKEW",
    "VERIFY_DIGEST_MISMATCH",
    "VERIFY_DOUBLE_MINT_REFUSED",
    "VERIFY_HANDOFF_CORRUPT",
    "VERIFY_PREFIX_ESCAPE",
    "VERIFY_RESULT_MISSING",
    "VERIFY_RESULT_MUTATED",
    "VERIFY_STALE_REPLAY",
    "VERIFY_TOLERANCE_EXCEEDED",
    "VERIFY_UNAUTHORIZED_EXECUTION",
    "is_registered",
    "require_failed_code",
    "require_registered",
]


def is_registered(code: str) -> bool:
    """Return True only for codes present in the closed registry."""
    return code in REASON_REGISTRY


def require_registered(code: str) -> str:
    """Return the code when registered, else raise ValueError.

    Args:
        code: Candidate reason code.

    Raises:
        ValueError: When the code is outside the closed registry.
    """
    if code not in REASON_REGISTRY:
        raise ValueError(f"Unknown verification reason code refused: {code!r}.")
    return code


def require_failed_code(code: str) -> str:
    """Return the code when it is a FAILED-carrying F28 code, else refuse.

    Args:
        code: Candidate reason code for a FAILED report.

    Raises:
        ValueError: When the code is unknown or is not one of the nine
            FAILED codes (refusal, incomplete, and replay markers excluded).
    """
    require_registered(code)
    if code not in FAILED_CODES:
        raise ValueError(f"Not a FAILED-carrying reason code: {code!r}.")
    return code
