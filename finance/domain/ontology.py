"""Meridian financial ontology: the variance-type catalog and code mapper.

Wraps the frozen P1 :class:`ExceptionCode` (three I-codes) without
mutating it. The Meridian catalog holds six discrepancy types from
``docs/domain/meridian-process-model.md`` (section 3); only the three
classifiable by the P1 pairwise classifier map onto frozen codes, the
rest resolve to their section-3 spec I-codes with a ``None`` frozen
mapping. Legacy rejections additionally carry the COBOL reason string
verbatim plus the offending account code.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from finance.reconciliation.models import ExceptionCode

DISCREPANCY_CATALOG: tuple["DiscrepancyType", ...] = ()
"""Placeholder replaced below once ``DiscrepancyType`` is defined."""


class DiscrepancyType(StrEnum):
    """The six canonical Meridian variance types."""

    FEE_MISMATCH = "fee-mismatch"
    """Fee slice differs from expectation."""

    REFUND_LAG = "refund-lag"
    """Refund in provider state, missing in QuickBooks."""

    LEGACY_REJECTION = "legacy-rejection"
    """COBOL record rejected (e.g. bad account code)."""

    TIMING_DIFFERENCE = "timing-difference"
    """Period cut-off effect, not a real loss."""

    DUPLICATE = "duplicate"
    """Same action or fingerprint seen twice."""

    ADJUSTMENT = "adjustment"
    """Provider adjustment not yet in QuickBooks."""


DISCREPANCY_CATALOG = tuple(DiscrepancyType)
"""All six catalog types, in canonical order."""


class LegacyRejectionReason(StrEnum):
    """COBOL rejection reasons carried verbatim on ``I-LEGACY-REJECT``."""

    INVALID_ACCOUNT_CODE = "INVALID_ACCOUNT_CODE"
    """Record referenced an account code outside the mapping table."""


_SPEC_CODES: dict[DiscrepancyType, str] = {
    DiscrepancyType.FEE_MISMATCH: "I-FEE-DRIFT",
    DiscrepancyType.REFUND_LAG: "I-REFUND-LAG",
    DiscrepancyType.LEGACY_REJECTION: "I-LEGACY-REJECT",
    DiscrepancyType.TIMING_DIFFERENCE: "I-TIMING",
    DiscrepancyType.DUPLICATE: "I-DUPLICATE",
    DiscrepancyType.ADJUSTMENT: "I-ADJUSTMENT",
}
"""Section-3 spec I-codes for all six catalog types."""

_FROZEN_CODES: dict[DiscrepancyType, ExceptionCode] = {
    DiscrepancyType.FEE_MISMATCH: ExceptionCode.FEE_MISMATCH,
    DiscrepancyType.REFUND_LAG: ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
    DiscrepancyType.DUPLICATE: ExceptionCode.DUPLICATE_LEDGER_ENTRY,
}
"""Types the frozen P1 pairwise classifier can express.

Legacy rejection, timing difference and adjustment have no P1
counterpart (P1 legs carry only gross/fee/refund components), so they
map to ``None`` here and to their section-3 spec I-codes instead.
"""


class FinancialOntology(BaseModel):
    """One classified discrepancy finding for a FinancialSituation.

    ``legacy_reason`` (plus ``offending_account_code``) is mandatory
    exactly when the discrepancy is ``LEGACY_REJECTION``, mirroring the
    spec rule that ``I-LEGACY-REJECT`` carries the COBOL reason verbatim.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    discrepancy: DiscrepancyType
    """Which of the six catalog types this finding is."""

    legacy_reason: LegacyRejectionReason | None = None
    """COBOL reason verbatim; only set for legacy rejections."""

    offending_account_code: str | None = None
    """Account code on the rejected record; only for legacy rejections."""

    @model_validator(mode="after")
    def _validate_legacy_reason_coupling(self) -> "FinancialOntology":
        """Require the verbatim reason exactly for legacy rejections."""
        is_legacy = self.discrepancy is DiscrepancyType.LEGACY_REJECTION
        if is_legacy and self.legacy_reason is None:
            raise ValueError(
                "legacy_reason is required for LEGACY_REJECTION "
                "(I-LEGACY-REJECT carries the COBOL reason verbatim)."
            )
        if not is_legacy and self.legacy_reason is not None:
            raise ValueError(
                "legacy_reason is only valid for LEGACY_REJECTION findings."
            )
        return self

    @property
    def spec_code(self) -> str:
        """Return the section-3 spec I-code for this discrepancy."""
        return _SPEC_CODES[self.discrepancy]

    @property
    def exception_code(self) -> ExceptionCode | None:
        """Return the frozen P1 code, or ``None`` when P1 cannot express it."""
        return _FROZEN_CODES.get(self.discrepancy)
