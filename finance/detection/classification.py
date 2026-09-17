"""Eight-label classification catalog wrapping the frozen P1 codes.

Section 3 decides WHAT the numbers say with pure arithmetic. The
frozen P1 pairwise classifier owns exactly three codes (fee drift,
refund lag, duplicate); this module maps those onto catalog labels via
:func:`map_p1_code` and resolves every label to its spec I-code via
:func:`spec_code_for` through the frozen ``FinancialOntology``. The P1
classifier is wrapped and never extended.
"""

from enum import StrEnum

from finance.domain.ontology import (
    DiscrepancyType,
    FinancialOntology,
    LegacyRejectionReason,
)
from finance.reconciliation.classifier import classify
from finance.reconciliation.models import ExceptionCode, PaymentRecord

__all__ = [
    "CASE_CREATING_CLASSIFICATIONS",
    "DetectionClassification",
    "classify_pair",
    "map_p1_code",
    "spec_code_for",
]


class DetectionClassification(StrEnum):
    """The eight deterministic detection labels (contract section 3)."""

    MATCHED = "MATCHED"
    """Zero variance with full coverage; creates nothing."""

    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    """Residual inside tolerance; creates nothing."""

    PARTIAL_REFUND_LAG = "PARTIAL_REFUND_LAG"
    """Refund seen by the provider, missing in-window in books."""

    FEE_MISMATCH = "FEE_MISMATCH"
    """Provider fee slice differs from the booked fee slice."""

    DUPLICATE_LEDGER_ENTRY = "DUPLICATE_LEDGER_ENTRY"
    """Two books rows share one idempotency fingerprint."""

    LEGACY_POSTING_MISSING = "LEGACY_POSTING_MISSING"
    """Legacy RJ record or absent legacy leg for a posted book leg."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    """Coverage incomplete; unknown data never promotes to a case."""

    CONFLICTING_AUTHORITIES = "CONFLICTING_AUTHORITIES"
    """Same id, different bodies; investigate only, never overwrite."""


CASE_CREATING_CLASSIFICATIONS: frozenset[DetectionClassification] = frozenset(
    {
        DetectionClassification.PARTIAL_REFUND_LAG,
        DetectionClassification.FEE_MISMATCH,
        DetectionClassification.DUPLICATE_LEDGER_ENTRY,
        DetectionClassification.LEGACY_POSTING_MISSING,
        DetectionClassification.CONFLICTING_AUTHORITIES,
    }
)
"""Labels that create a FinancialSituation in DETECTED (section 4.1)."""

_P1_TO_CATALOG: dict[ExceptionCode, DetectionClassification] = {
    ExceptionCode.FEE_MISMATCH: DetectionClassification.FEE_MISMATCH,
    ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG: (
        DetectionClassification.PARTIAL_REFUND_LAG
    ),
    ExceptionCode.DUPLICATE_LEDGER_ENTRY: (
        DetectionClassification.DUPLICATE_LEDGER_ENTRY
    ),
}
"""The closed P1 vocabulary mapped onto catalog labels (no extension)."""

_SPEC_FALLBACK: dict[DetectionClassification, str] = {
    DetectionClassification.MATCHED: "MATCHED",
    DetectionClassification.WITHIN_TOLERANCE: "WITHIN_TOLERANCE",
    DetectionClassification.INSUFFICIENT_EVIDENCE: "UNKNOWN",
    DetectionClassification.CONFLICTING_AUTHORITIES: "CONFLICTING_AUTHORITIES",
}
"""Labels with no ontology counterpart keep their section 3 names."""


def map_p1_code(code: ExceptionCode) -> DetectionClassification:
    """Map one frozen P1 exception code onto its catalog label.

    Args:
        code: One of the three frozen P1 exception codes.

    Returns:
        The corresponding catalog label.

    Raises:
        KeyError: If the code is outside the frozen P1 vocabulary.
    """
    return _P1_TO_CATALOG[code]


def classify_pair(
    expected: PaymentRecord,
    observed: PaymentRecord,
    *,
    duplicate: bool = False,
) -> DetectionClassification:
    """Classify one leg pair through the frozen P1 classifier.

    Args:
        expected: The expected (provider-side) leg.
        observed: The observed (books-side) leg.
        duplicate: Dedup-layer flag for reused idempotency keys.

    Returns:
        The catalog label for the frozen P1 code.
    """
    return map_p1_code(classify(expected, observed, duplicate=duplicate))


def spec_code_for(classification: DetectionClassification) -> str:
    """Resolve a catalog label to its spec I-code via the ontology.

    Args:
        classification: The catalog label to resolve.

    Returns:
        The section 3 spec I-code (ontology-backed where one exists).
    """
    fallback = _SPEC_FALLBACK.get(classification)
    if fallback is not None:
        return fallback
    if classification is DetectionClassification.LEGACY_POSTING_MISSING:
        finding = FinancialOntology(
            discrepancy=DiscrepancyType.LEGACY_REJECTION,
            legacy_reason=LegacyRejectionReason.INVALID_ACCOUNT_CODE,
        )
        return finding.spec_code
    ontology_type = {
        DetectionClassification.FEE_MISMATCH: DiscrepancyType.FEE_MISMATCH,
        DetectionClassification.PARTIAL_REFUND_LAG: DiscrepancyType.REFUND_LAG,
        DetectionClassification.DUPLICATE_LEDGER_ENTRY: DiscrepancyType.DUPLICATE,
    }[classification]
    finding = FinancialOntology(discrepancy=ontology_type)
    return finding.spec_code
