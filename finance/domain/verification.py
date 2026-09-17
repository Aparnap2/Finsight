"""Deterministic post-execution verification report (P6-02 D1/D8 gates).

A ``VerificationReport`` is the deterministic post-execution re-reconcile
for one ``FinancialSituation`` (spec ``docs/domain/meridian-process-model.md``
section 1.10 and worked example section 4.5): the legacy total after the
correction leg is accepted plus the residual variance and a verdict. There
is no ``CLOSED`` without an accepted report bound to the same situation id
whose residual sits within the minor tolerance
(``CompanyConfiguration().tolerance_minor``).

Lifecycle state only: this module never writes ledgers, never calls the
network, never uses an LLM. Money is ``Decimal``-only; floats are rejected
at the Pydantic boundary via ``MoneyDecimal``.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal

__all__ = ["VerificationVerdict", "VerificationReport"]
"""Verification verdict enum and the frozen deterministic report."""


class VerificationVerdict(StrEnum):
    """Outcome of the deterministic post-execution re-reconcile."""

    VERIFIED = "VERIFIED"
    """Correction accepted; residual variance is within tolerance."""

    FAILED = "FAILED"
    """Correction not accepted; the situation must be re-investigated."""


class VerificationReport(BaseModel):
    """Deterministic re-reconcile verdict bound to one situation.

    The report binds ``situation_id`` (which situation was re-reconciled)
    to ``execution_id`` (which execution was verified) plus the observed
    post-execution legacy total, the residual variance, and the verdict.
    ``checked_at`` is timezone-aware. The aggregate stores the accepted
    report on the ``VERIFYING -> CLOSED`` transition; see
    ``finance/domain/lifecycle.py`` and
    ``finance/domain/financial_situation.py``.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    situation_id: str
    """Parent FinancialSituation id the re-reconcile was run for."""

    execution_id: str
    """Execution that was verified (non-blank idempotency binding)."""

    legacy_total_after: MoneyDecimal
    """Legacy accepted total after the correction, INR (Decimal only)."""

    variance_after: MoneyDecimal
    """Residual variance after the correction, INR (Decimal only)."""

    verdict: VerificationVerdict
    """``VERIFIED`` accepts the close; ``FAILED`` reopens investigation."""

    checked_at: datetime
    """Timezone-aware timestamp of the deterministic re-reconcile run."""

    @field_validator("execution_id")
    @classmethod
    def _validate_execution_id(cls, value: str) -> str:
        """Require a non-blank execution binding (unbound reports refuse)."""
        if not value.strip():
            raise ValueError(
                "execution_id must be non-blank: the report must bind "
                "to the execution it verifies."
            )
        return value

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps for checked_at."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "checked_at must be timezone-aware, got a naive datetime."
            )
        return value

    def is_accepted(self, tolerance: Decimal) -> bool:
        """Return True when the report accepts the close at ``tolerance``.

        Acceptance is the conjunction of the deterministic verdict
        (``VERIFIED``) and the residual bound (``abs(variance_after)``
        within ``tolerance``). A ``FAILED`` verdict never accepts, and an
        over-tolerance residual never accepts, regardless of verdict.

        Args:
            tolerance: Maximum acceptable absolute residual variance,
                normally ``CompanyConfiguration().tolerance_minor``.

        Returns:
            True only for ``VERIFIED`` with residual within tolerance.
        """
        return (
            self.verdict is VerificationVerdict.VERIFIED
            and abs(self.variance_after) <= tolerance
        )
