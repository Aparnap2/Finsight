"""Deterministic matching primitives for reconciling leg pairs.

Three layers, cheapest first: ``exact_match`` (same currency, equal
net), ``within_tolerance`` (same currency, difference inside the
tenant-injected tolerance window), and ``find_match`` (deterministic
1:N candidate scan preferring reference linkage, then exact amount,
then the closest within-tolerance amount). ``find_duplicates`` and
``ensure_unique`` give the dedup layer pure idempotency-key grouping.

Pure and deterministic: no LLM, database, network, clock reads, or
randomness. Only the Python standard library is used.
"""

import logging
from collections.abc import Sequence
from decimal import Decimal

from finance.reconciliation.errors import (
    DuplicateError,
    InvariantViolation,
    ToleranceError,
)
from finance.reconciliation.models import PaymentRecord
from finance.reconciliation.tolerances import ReconciliationTolerance

logger = logging.getLogger(__name__)


def _require_record(name: str, value: object) -> PaymentRecord:
    """Narrow an argument to ``PaymentRecord``, rejecting anything else."""
    if not isinstance(value, PaymentRecord):
        raise InvariantViolation(
            f"{name} must be a PaymentRecord, got {type(value).__name__}."
        )
    return value


def _require_tolerance(value: object) -> ReconciliationTolerance:
    """Narrow an argument to ``ReconciliationTolerance``."""
    if not isinstance(value, ReconciliationTolerance):
        raise ToleranceError(
            "tolerance must be a ReconciliationTolerance, "
            f"got {type(value).__name__}."
        )
    return value


def exact_match(expected: PaymentRecord, observed: PaymentRecord) -> bool:
    """Return True when legs share a currency and have equal nets.

    Equality is numeric ``Decimal`` equality (scale-insensitive):
    ``Decimal("35")`` equals ``Decimal("35.00")``.
    """
    _require_record("expected", expected)
    _require_record("observed", observed)
    return expected.currency == observed.currency and expected.net == observed.net


def within_tolerance(
    expected: PaymentRecord,
    observed: PaymentRecord,
    tolerance: ReconciliationTolerance,
) -> bool:
    """Return True when legs share a currency and fit the tolerance window.

    A currency mismatch returns False (never raises): incomparable legs
    are a break for the reconciler to report, not a matcher error.
    """
    _require_record("expected", expected)
    _require_record("observed", observed)
    _require_tolerance(tolerance)
    if expected.currency != observed.currency:
        return False
    difference = observed.net - expected.net
    return tolerance.allows(difference, abs(expected.net))


def find_match(
    target: PaymentRecord,
    candidates: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    window_seconds: int | None = None,
    prefer_reference: bool = True,
) -> PaymentRecord | None:
    """Scan candidates deterministically and return the best match, if any.

    Selection order: (1) a candidate sharing the target's
    ``idempotency_key`` whose net fits the tolerance window (when
    ``prefer_reference``), (2) the first candidate with an exactly equal
    net, (3) the smallest absolute difference within tolerance (ties
    resolve to the earliest candidate). Candidates with a different
    currency, or outside ``window_seconds`` of the target when set, are
    skipped. Returns None when nothing qualifies.

    Args:
        target: The leg to match.
        candidates: Ordered candidate legs; order breaks all ties.
        tolerance: Tenant-injected tolerance window.
        window_seconds: Optional maximum ``|occurred_at|`` skew in
            seconds; None disables the time gate.
        prefer_reference: Whether to prefer ``idempotency_key`` linkage.

    Raises:
        InvariantViolation: For non-record inputs or a bad time window.
        ToleranceError: If ``tolerance`` is not a tolerance object.
    """
    _require_record("target", target)
    _require_tolerance(tolerance)
    for index, candidate in enumerate(candidates):
        _require_record(f"candidates[{index}]", candidate)
    window_value: object = window_seconds
    if window_value is not None:
        if isinstance(window_value, bool) or not isinstance(window_value, int):
            raise InvariantViolation("window_seconds must be an int or null.")
        if window_value < 0:
            raise InvariantViolation("window_seconds must be non-negative.")
    prefer_value: object = prefer_reference
    if not isinstance(prefer_value, bool):
        raise InvariantViolation("prefer_reference must be a bool.")

    shortlist = [
        candidate
        for candidate in candidates
        if candidate.currency == target.currency
        and (
            window_value is None
            or abs((candidate.occurred_at - target.occurred_at).total_seconds())
            <= window_value
        )
    ]
    base = abs(target.net)
    if prefer_value:
        for candidate in shortlist:
            if candidate.idempotency_key != target.idempotency_key:
                continue
            difference = candidate.net - target.net
            if difference == Decimal("0") or tolerance.allows(difference, base):
                logger.debug(
                    "Reference-linked match for target=%s candidate=%s",
                    target.payment_id,
                    candidate.payment_id,
                )
                return candidate
    for candidate in shortlist:
        if candidate.net == target.net:
            logger.debug(
                "Exact match for target=%s candidate=%s",
                target.payment_id,
                candidate.payment_id,
            )
            return candidate
    best: PaymentRecord | None = None
    best_difference: Decimal | None = None
    for candidate in shortlist:
        difference = abs(candidate.net - target.net)
        if not tolerance.allows(candidate.net - target.net, base):
            continue
        if best is None or best_difference is None or difference < best_difference:
            best = candidate
            best_difference = difference
    if best is not None:
        logger.debug(
            "Tolerance match for target=%s candidate=%s", target.payment_id, best.payment_id
        )
    return best


def find_duplicates(
    records: Sequence[PaymentRecord],
) -> dict[str, list[PaymentRecord]]:
    """Group records by ``idempotency_key``, returning only repeated keys.

    Order within each group follows input order; the mapping only
    contains keys seen more than once.
    """
    for index, record in enumerate(records):
        _require_record(f"records[{index}]", record)
    groups: dict[str, list[PaymentRecord]] = {}
    for record in records:
        groups.setdefault(record.idempotency_key, []).append(record)
    return {key: group for key, group in groups.items() if len(group) > 1}


def ensure_unique(records: Sequence[PaymentRecord]) -> None:
    """Require each ``idempotency_key`` to appear at most once.

    Raises:
        InvariantViolation: If any element is not a ``PaymentRecord``.
        DuplicateError: If any ``idempotency_key`` repeats, naming the keys.
    """
    duplicates = find_duplicates(records)
    if duplicates:
        keys = ", ".join(sorted(duplicates))
        raise DuplicateError(f"Duplicate idempotency_key(s) detected: {keys}.")
