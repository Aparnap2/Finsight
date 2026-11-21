"""P1 pure deterministic reconciliation core.

Implements Normalize (``normalizer`` + ``bank``), Reconcile (``reconciler``
over ``matcher`` + ``tolerances``, plus the deposit-to-charge edge in
``allocation``), Classify (``classifier``), and stable identity
(``fingerprints``) for the frozen reconciliation spec. Every stage is
pure: identical inputs always produce identical outputs with no LLM,
database, HTTP, clock, randomness, queue, or SDK involvement.

Only the Python standard library (plus ``decimal``/``dataclasses``/
``typing``/``hashlib``) is used. This package imports nothing from
``apps/`` or ``agents/``.
"""

from finance.reconciliation.allocation import (
    MAX_ALLOCATION_CANDIDATES,
    Allocation,
    AllocationLeg,
    CandidateAllocation,
    PayoutReason,
    allocate_deposit,
    reconcile_payout,
)
from finance.reconciliation.bank import (
    AmountUnit,
    BankDepositRecord,
    BankIngestResult,
    BankStatementMapping,
    RejectReason,
    RowReject,
    SignConvention,
    ensure_unique_deposits,
    find_duplicate_deposits,
    fingerprint_deposit,
    normalize_bank_statement,
)
from finance.reconciliation.classifier import classify
from finance.reconciliation.errors import (
    CurrencyMismatch,
    DuplicateError,
    FloatMoneyError,
    InvariantViolation,
    ReconciliationError,
    TenantIsolationError,
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
    PayoutOutcome,
    ReconciliationOutcome,
    ReconciliationResult,
)
from finance.reconciliation.normalizer import minor_unit_exponent, normalize
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

__all__ = [
    "MAX_ALLOCATION_CANDIDATES",
    "Allocation",
    "AllocationLeg",
    "AmountUnit",
    "BankDepositRecord",
    "BankIngestResult",
    "BankStatementMapping",
    "CandidateAllocation",
    "CurrencyMismatch",
    "DuplicateError",
    "ExceptionCode",
    "FloatMoneyError",
    "InvariantViolation",
    "MaterialityVerdict",
    "PaymentRecord",
    "PaymentStatus",
    "PayoutOutcome",
    "PayoutReason",
    "ReconciliationError",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "ReconciliationTolerance",
    "RejectReason",
    "RowReject",
    "SignConvention",
    "TenantIsolationError",
    "ToleranceError",
    "allocate_deposit",
    "canonical_payment",
    "classify",
    "ensure_unique",
    "ensure_unique_deposits",
    "exact_match",
    "find_duplicate_deposits",
    "find_duplicates",
    "find_match",
    "fingerprint_deposit",
    "fingerprint_pair",
    "fingerprint_payment",
    "minor_unit_exponent",
    "normalize",
    "normalize_bank_statement",
    "reconcile",
    "reconcile_payout",
    "within_tolerance",
]
