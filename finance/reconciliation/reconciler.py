"""Pure deterministic reconciliation entry point.

:func:`reconcile` compares one expected (processor-side) leg against one
observed (ledger-side) leg under a tenant-injected tolerance and
returns a :class:`ReconciliationResult`: exact agreement closes as
``MATCHED``, a boundary-inclusive fit closes as ``TOLERANCE_MATCHED``,
and anything beyond the window becomes ``EXCEPTION`` with a versioned
I-code from the classifier. Cross-currency pairs are incomparable and
raise instead of producing a verdict.

Pure and deterministic: identical inputs always yield identical
outputs; no LLM, database, network, clock reads, or randomness. Only
the Python standard library is used.
"""

import logging

from finance.reconciliation.classifier import classify
from finance.reconciliation.errors import (
    CurrencyMismatch,
    InvariantViolation,
    ToleranceError,
)
from finance.reconciliation.fingerprints import fingerprint_pair
from finance.reconciliation.matcher import exact_match, within_tolerance
from finance.reconciliation.models import (
    MaterialityVerdict,
    PaymentRecord,
    ReconciliationOutcome,
    ReconciliationResult,
)
from finance.reconciliation.tolerances import ReconciliationTolerance

logger = logging.getLogger(__name__)


def reconcile(
    processor: PaymentRecord,
    ledger: PaymentRecord,
    tolerance: ReconciliationTolerance,
    *,
    duplicate: bool = False,
) -> ReconciliationResult:
    """Reconcile a processor leg against a ledger leg deterministically.

    The processor intent is the expected leg and the ledger entry is the
    observed leg, so ``difference == ledger.net - processor.net``. The
    tolerance allowance derives from ``abs(processor.net)``; the
    materiality verdict is ``MATERIAL`` exactly when the absolute
    difference strictly exceeds that allowance.

    Args:
        processor: Expected (processor-side) payment leg.
        ledger: Observed (ledger-side) payment leg.
        tolerance: Tenant-injected tolerance (zero-default).
        duplicate: Set by the dedup layer when ``ledger`` reuses an
            already-reconciled ``idempotency_key``.

    Returns:
        The immutable :class:`ReconciliationResult`.

    Raises:
        InvariantViolation: For non-record inputs or a non-bool flag.
        ToleranceError: If ``tolerance`` is not a tolerance object.
        CurrencyMismatch: If the legs use different currencies.
    """
    processor_value: object = processor
    if not isinstance(processor_value, PaymentRecord):
        raise InvariantViolation(
            f"processor must be a PaymentRecord, got {type(processor_value).__name__}."
        )
    ledger_value: object = ledger
    if not isinstance(ledger_value, PaymentRecord):
        raise InvariantViolation(
            f"ledger must be a PaymentRecord, got {type(ledger_value).__name__}."
        )
    tolerance_value: object = tolerance
    if not isinstance(tolerance_value, ReconciliationTolerance):
        raise ToleranceError(
            "tolerance must be a ReconciliationTolerance, "
            f"got {type(tolerance_value).__name__}."
        )
    duplicate_value: object = duplicate
    if not isinstance(duplicate_value, bool):
        raise InvariantViolation(
            f"duplicate must be a bool, got {type(duplicate_value).__name__}."
        )
    if processor_value.currency != ledger_value.currency:
        raise CurrencyMismatch(
            processor_value.currency, ledger_value.currency, "reconcile"
        )

    base = abs(processor_value.net)
    difference = ledger_value.net - processor_value.net
    allowance = tolerance_value.apply(base)
    if exact_match(processor_value, ledger_value):
        outcome = ReconciliationOutcome.MATCHED
        exception_code: str | None = None
    elif within_tolerance(processor_value, ledger_value, tolerance_value):
        outcome = ReconciliationOutcome.TOLERANCE_MATCHED
        exception_code = None
    else:
        outcome = ReconciliationOutcome.EXCEPTION
        exception_code = classify(
            processor_value, ledger_value, duplicate=duplicate_value
        ).value
    materiality = (
        MaterialityVerdict.MATERIAL
        if abs(difference) > allowance
        else MaterialityVerdict.IMMATERIAL
    )
    result = ReconciliationResult(
        outcome=outcome,
        expected=processor_value.net,
        observed=ledger_value.net,
        difference=difference,
        variance=abs(difference),
        tolerance_applied=allowance,
        currency=processor_value.currency,
        exception_code=exception_code,
        fingerprint=fingerprint_pair(processor_value, ledger_value),
        materiality=materiality,
    )
    logger.info(
        "Reconciled processor=%s ledger=%s outcome=%s difference=%s",
        processor_value.payment_id,
        ledger_value.payment_id,
        result.outcome.value,
        result.difference,
    )
    return result
