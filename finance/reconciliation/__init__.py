"""P1 pure deterministic reconciliation core.

Implements Normalize (``normalizer``), Reconcile (``reconciler`` over
``matcher`` + ``tolerances``), Classify (``classifier``), and stable
identity (``fingerprints``) for the frozen reconciliation spec. Every
stage is pure: identical inputs always produce identical outputs with
no LLM, database, HTTP, clock, randomness, queue, or SDK involvement.

Only the Python standard library (plus ``decimal``/``dataclasses``/
``typing``/``hashlib``) is used. This package imports nothing from
``apps/`` or ``agents/``.
"""

from finance.reconciliation.classifier import classify
from finance.reconciliation.errors import (
    CurrencyMismatch,
    DuplicateError,
    FloatMoneyError,
    InvariantViolation,
    ReconciliationError,
    ToleranceError,
)
from finance.reconciliation.fingerprints import (
    canonical_payment,
    fingerprint_pair,
    fingerprint_payment,
)
from finance.reconciliation.matcher import (
    ensure_unique,
    exact_match,
    find_duplicates,
    find_match,
    within_tolerance,
)
from finance.reconciliation.models import (
    ExceptionCode,
    MaterialityVerdict,
    PaymentRecord,
    PaymentStatus,
    ReconciliationOutcome,
    ReconciliationResult,
)
from finance.reconciliation.normalizer import normalize
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

__all__ = [
    "CurrencyMismatch",
    "DuplicateError",
    "ExceptionCode",
    "FloatMoneyError",
    "InvariantViolation",
    "MaterialityVerdict",
    "PaymentRecord",
    "PaymentStatus",
    "ReconciliationError",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "ReconciliationTolerance",
    "ToleranceError",
    "canonical_payment",
    "classify",
    "ensure_unique",
    "exact_match",
    "find_duplicates",
    "find_match",
    "fingerprint_pair",
    "fingerprint_payment",
    "normalize",
    "reconcile",
    "within_tolerance",
]
