"""Break classification into the 3 versioned P0 exception types.

When a leg pair exceeds tolerance, :func:`classify` attributes the net
break to exactly one :class:`ExceptionCode`: a duplicate re-ingest, a
fee-only drift, or a refund/capture timing lag (the flagship
50k-authorized / 15k-refunded / 35k-settled shape: gross agrees while
the refund component lags). Mixed breaks resolve to the largest
absolute contributing component with ties broken refund, then fee,
then gross.

Pure and deterministic: no LLM, database, network, clock reads, or
randomness. Only the Python standard library is used.
"""

import logging

from finance.reconciliation.errors import CurrencyMismatch, InvariantViolation
from finance.reconciliation.models import ExceptionCode, PaymentRecord

logger = logging.getLogger(__name__)


def _require_record(name: str, value: object) -> PaymentRecord:
    """Narrow an argument to ``PaymentRecord``, rejecting anything else."""
    if not isinstance(value, PaymentRecord):
        raise InvariantViolation(
            f"{name} must be a PaymentRecord, got {type(value).__name__}."
        )
    return value


def classify(
    expected: PaymentRecord,
    observed: PaymentRecord,
    *,
    duplicate: bool = False,
) -> ExceptionCode:
    """Attribute an over-tolerance break to one versioned exception type.

    Args:
        expected: The expected (processor-side) leg.
        observed: The observed (ledger-side) leg.
        duplicate: Set by the dedup layer when the observed leg reuses an
            already-reconciled ``idempotency_key``.

    Returns:
        The single applicable :class:`ExceptionCode`.

    Raises:
        InvariantViolation: For non-record inputs, a non-bool flag, or
            legs with no component difference to attribute.
        CurrencyMismatch: If the legs use different currencies.
    """
    _require_record("expected", expected)
    _require_record("observed", observed)
    duplicate_value: object = duplicate
    if not isinstance(duplicate_value, bool):
        raise InvariantViolation(
            f"duplicate must be a bool, got {type(duplicate_value).__name__}."
        )
    if expected.currency != observed.currency:
        raise CurrencyMismatch(expected.currency, observed.currency, "classify")
    if duplicate_value:
        logger.debug("Classified break as DUPLICATE_LEDGER_ENTRY (dedup flag).")
        return ExceptionCode.DUPLICATE_LEDGER_ENTRY
    delta_gross = observed.gross - expected.gross
    delta_fee = observed.fee - expected.fee
    delta_refund = observed.refund - expected.refund
    if delta_gross == 0 and delta_refund == 0 and delta_fee != 0:
        logger.debug("Classified break as FEE_MISMATCH (fee-only drift).")
        return ExceptionCode.FEE_MISMATCH
    if delta_gross == 0 and delta_fee == 0 and delta_refund != 0:
        logger.debug("Classified break as PARTIAL_REFUND_ACCOUNTING_LAG.")
        return ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG
    if delta_gross == 0 and delta_fee == 0 and delta_refund == 0:
        raise InvariantViolation("classify requires legs with a component difference.")
    magnitude_refund = abs(delta_refund)
    magnitude_fee = abs(delta_fee)
    magnitude_gross = abs(delta_gross)
    if magnitude_refund >= magnitude_fee and magnitude_refund >= magnitude_gross:
        logger.debug("Classified mixed break as PARTIAL_REFUND_ACCOUNTING_LAG.")
        return ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG
    if magnitude_fee >= magnitude_gross:
        logger.debug("Classified mixed break as FEE_MISMATCH.")
        return ExceptionCode.FEE_MISMATCH
    logger.debug("Classified mixed break as PARTIAL_REFUND_ACCOUNTING_LAG.")
    return ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG
