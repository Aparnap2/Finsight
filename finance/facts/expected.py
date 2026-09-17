"""Advisory sheets expected-settlement fact (never authoritative).

``ExpectedFact`` carries the business view of one settlement window.
It feeds only the informational expected-books gap (section 2.3) and
never creates or sizes a case: timing cut-off effects live here,
separated from real provider-vs-books discrepancies.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from finance.domain._types import MoneyDecimal
from finance.facts._guards import (
    reject_non_decimal_money_value,
    require_inr_currency,
    require_tz_aware,
)
from finance.facts.provenance import FactProvenance


class ExpectedFact(BaseModel):
    """One advisory expected-settlement read for a batch window."""

    model_config = ConfigDict(frozen=True, strict=True)

    fact_id: str
    """Reader dedupe key (spreadsheet id, range, and content hash)."""

    batch_id: str
    """Settlement window key shared with provider and books legs."""

    source: str = "sheets"
    """Owning source; always ``sheets``."""

    expected_total: MoneyDecimal
    """Expected settlement total, INR Decimal-only."""

    currency: str = "INR"
    """Always ``INR``; anything else is rejected, never converted."""

    observed_at: datetime
    """Timezone-aware read timestamp."""

    provenance: FactProvenance
    """Ingest identity; anonymous reads never reconcile."""

    @field_validator("fact_id", "batch_id")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        """Require non-empty fact and batch identifiers."""
        if not value.strip():
            raise ValueError("fact_id and batch_id must be non-empty.")
        return value.strip()

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        """Pin the owning source to sheets."""
        if value != "sheets":
            raise ValueError(
                f"source must be 'sheets' for ExpectedFact, got {value!r}."
            )
        return value

    @field_validator("expected_total", mode="before")
    @classmethod
    def _reject_float_total(cls, value: Any) -> Any:
        """Reject float/bool totals before type narrowing."""
        return reject_non_decimal_money_value(value, "expected_total")

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        """Enforce the INR-only boundary."""
        return require_inr_currency(value)

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware read timestamp."""
        return require_tz_aware(value, "observed_at")
