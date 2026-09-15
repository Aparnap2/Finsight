"""Stable sha256 fingerprints over canonical payment representations.

Fingerprints give idempotency and identity without a database: the same
normalized ``PaymentRecord`` always hashes to the same digest, in any
process, with no clock, randomness, network, or LLM involvement.
Canonicalization fixes field order, money scale rendering, and
timestamps (always UTC ISO-8601), so only the record content determines
the digest.

Only the Python standard library is used (``hashlib`` + ``decimal``).
"""

import hashlib
from datetime import UTC
from decimal import Decimal

from finance.reconciliation.errors import InvariantViolation
from finance.reconciliation.models import PaymentRecord

_CANONICAL_SEPARATOR = "\x1f"
_PAIR_SEPARATOR = "\x1e"


def _canonical_decimal(value: Decimal) -> str:
    """Render a Decimal in plain fixed-point form, preserving scale."""
    return format(value, "f")


def canonical_payment(record: PaymentRecord) -> str:
    """Render the canonical string form of one payment leg.

    Field order is fixed, money uses plain fixed-point rendering,
    ``occurred_at`` is normalized to UTC, and ``None``
    ``source_reference`` renders as the empty string.

    Args:
        record: The payment leg to canonicalize.

    Returns:
        The canonical string (never hashed here; see below).

    Raises:
        InvariantViolation: If ``record`` is not a ``PaymentRecord``.
    """
    record_value: object = record
    if not isinstance(record_value, PaymentRecord):
        raise InvariantViolation(
            f"canonical_payment requires a PaymentRecord, got {type(record_value).__name__}."
        )
    occurred_utc = record_value.occurred_at.astimezone(UTC).isoformat()
    parts = (
        record_value.payment_id,
        record_value.provider,
        record_value.provider_event_id,
        record_value.idempotency_key,
        _canonical_decimal(record_value.gross),
        _canonical_decimal(record_value.fee),
        _canonical_decimal(record_value.refund),
        _canonical_decimal(record_value.net),
        record_value.currency,
        record_value.status.value,
        occurred_utc,
        record_value.tenant_id,
        record_value.source_reference or "",
    )
    return _CANONICAL_SEPARATOR.join(parts)


def fingerprint_payment(record: PaymentRecord) -> str:
    """Compute the sha256 hex digest of one canonical payment leg.

    Args:
        record: The payment leg to fingerprint.

    Returns:
        64-character lowercase hex digest.
    """
    canonical = canonical_payment(record)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_pair(expected: PaymentRecord, observed: PaymentRecord) -> str:
    """Compute the sha256 hex digest of a canonical expected+observed pair.

    Leg order is significant: ``fingerprint_pair(a, b)`` differs from
    ``fingerprint_pair(b, a)`` because legs are directional (processor
    intent versus ledger observation).

    Args:
        expected: The expected (processor-side) leg.
        observed: The observed (ledger-side) leg.

    Returns:
        64-character lowercase hex digest identifying the pair.
    """
    joined = (
        canonical_payment(expected) + _PAIR_SEPARATOR + canonical_payment(observed)
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
