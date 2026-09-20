"""P6-08 track B checked_at discipline (F29): pure predicates, no clock reads.

``assess_clock`` maps a caller-supplied run time to an optional reason code:
naive stamps are refused outright, backdated or over-budget stamps map to
``VERIFY_CLOCK_SKEW``, and in-window stamps pass with no code. The 5-minute
future budget is a frozen constant consumed as given.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from finance.verification.reason_codes import VERIFY_CLOCK_SKEW

FUTURE_SKEW_BUDGET: timedelta = timedelta(minutes=5)
"""Maximum future skew of checked_at past now before the run mints FAILED."""

__all__ = ["FUTURE_SKEW_BUDGET", "assess_clock"]


def _require_tz_aware(name: str, value: datetime) -> datetime:
    """Return the value when tz-aware, else raise ValueError.

    Args:
        name: Argument label for the refusal message.
        value: Candidate timestamp.

    Raises:
        ValueError: When the timestamp is naive.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be tz-aware, got a naive datetime.")
    return value


def assess_clock(
    *,
    checked_at: datetime,
    recorded_at: datetime,
    now: datetime,
) -> str | None:
    """Assess the run time against the handoff record time and now (F29).

    Args:
        checked_at: Caller-supplied tz-aware verification run time.
        recorded_at: Handoff record time; checked_at must not precede it.
        now: Caller-supplied tz-aware run window anchor for future skew.

    Returns:
        ``VERIFY_CLOCK_SKEW`` when checked_at predates recorded_at or
        exceeds now plus the budget; None when the stamp is in window.

    Raises:
        ValueError: When any stamp is naive (the caller owns the clock).
    """
    _require_tz_aware("checked_at", checked_at)
    _require_tz_aware("recorded_at", recorded_at)
    _require_tz_aware("now", now)
    if checked_at < recorded_at:
        return VERIFY_CLOCK_SKEW
    if checked_at > now + FUTURE_SKEW_BUDGET:
        return VERIFY_CLOCK_SKEW
    return None
