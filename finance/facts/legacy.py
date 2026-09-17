"""COBOL legacy posting fact (accepted vs rejected split).

``LegacyFact`` carries one legacy result-file outcome for a batch
window: the accepted total plus the rejected total with the verbatim
COBOL reason string (``None`` when the window posted clean). The
reason rides verbatim end to end; detection never paraphrases it.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal
from finance.facts._guards import (
    reject_non_decimal_money_value,
    require_inr_currency,
    require_tz_aware,
)
from finance.facts.provenance import FactProvenance


class LegacyFact(BaseModel):
    """One legacy result-file outcome for a batch window."""

    model_config = ConfigDict(frozen=True, strict=True)

    fact_id: str
    """Legacy record reference (batch id plus sequence)."""

    batch_id: str
    """Legacy batch key (``LEGACY-YYYYMMDD-NNNN`` shape family)."""

    accepted_total: MoneyDecimal
    """Accepted posting total, INR Decimal-only."""

    rejected_total: MoneyDecimal = Decimal("0")
    """Rejected posting total, INR Decimal-only (zero when clean)."""

    rejected_reason: str | None = None
    """Verbatim COBOL reason string; ``None`` when nothing rejected."""

    account_code: str | None = None
    """Posting account code under review, when the reason names one."""

    currency: str = "INR"
    """Always ``INR``; anything else is rejected, never converted."""

    posted_at: datetime
    """Timezone-aware result-file timestamp."""

    provenance: FactProvenance
    """S3 key plus result-file id plus run id; never anonymous."""

    @field_validator("fact_id", "batch_id")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Require non-empty fact and batch identifiers."""
        if not value.strip():
            raise ValueError("fact_id and batch_id must be non-empty.")
        return value.strip()

    @field_validator("accepted_total", "rejected_total", mode="before")
    @classmethod
    def _reject_float_money(cls, value: Any) -> Any:
        """Reject float/bool money before type narrowing."""
        return reject_non_decimal_money_value(value, "legacy money")

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        """Enforce the INR-only boundary."""
        return require_inr_currency(value)

    @field_validator("posted_at")
    @classmethod
    def _validate_posted_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware result-file timestamp."""
        return require_tz_aware(value, "posted_at")
